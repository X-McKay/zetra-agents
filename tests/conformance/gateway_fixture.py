"""Test doubles: JWT-shaped tokens, a TLS CA, a fake gateway and a fake agent image."""

import base64
import datetime
import ipaddress
import json
import re
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

SECRET_PATTERNS = [
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"Bearer [A-Za-z0-9._~+/=-]{20,}"),
]


def assert_redacted(*texts: str) -> None:
    for text in texts:
        for p in SECRET_PATTERNS:
            assert not p.search(text or ""), f"secret-shaped value leaked: {p.pattern}"


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def make_jwt(**claims) -> str:
    return f"{_b64({'alg': 'RS256', 'typ': 'JWT'})}.{_b64(claims)}.c2lnbmF0dXJlLXNpZ25hdHVyZQ"


def agent_token(
    n: int = 0, aud=("agent-gateway", "agent-policy-service"), ttl: int = 300
) -> str:
    now = int(time.time())
    return make_jwt(
        aud=list(aud),
        client_type="agent",
        jti=f"jti-{n}",
        iat=now,
        exp=now + ttl,
        agent_id="tenant-test/conformance",
    )


def projected_token(n: int = 0) -> str:
    return make_jwt(
        aud=["https://idp.example.com/realms/agents"],
        jti=f"proj-{n}",
        sub="system:serviceaccount:tenant-test:agent-conformance",
    )


def make_ca(directory: Path) -> tuple[Path, Path, Path]:
    """A CA and a server certificate for 127.0.0.1; returns (ca.crt, server.crt, server.key)."""
    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-ca")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(1)
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "agents")]))
        .issuer_name(ca_name)
        .public_key(key.public_key())
        .serial_number(2)
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    paths = directory / "ca.crt", directory / "server.crt", directory / "server.key"
    paths[0].write_bytes(ca.public_bytes(pem))
    paths[1].write_bytes(cert.public_bytes(pem))
    paths[2].write_bytes(
        key.private_bytes(
            pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    return paths


def chat_response(
    content: str | None = None, tool_calls: list | None = None, usage=(10, 5)
) -> dict:
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = [
            {
                "id": f"call-{i}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
            for i, (name, args) in enumerate(tool_calls)
        ]
    return {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "m",
        "choices": [
            {
                "index": 0,
                "message": msg,
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": usage[0],
            "completion_tokens": usage[1],
            "total_tokens": sum(usage),
        },
    }


class Gateway:
    """Synthetic token/model/MCP routes over a locally trusted TLS certificate."""

    def __init__(self, cert, key, tools, fixtures):
        self.chat_requests = []
        self.mcp_calls = []
        self.tools = list(tools)
        self.fixtures = fixtures
        gw = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, body):
                data = json.dumps(body).encode() if body is not None else b""
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self.reply(405, None)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                host = self.headers.get("Host")
                if host == "token.agents.internal" and self.path == "/v1/token":
                    self.reply(
                        200,
                        {
                            "access_token": agent_token(),
                            "expires_in": 300,
                            "token_type": "Bearer",
                        },
                    )
                    return
                if not self.headers.get("Authorization", "").startswith("Bearer "):
                    self.reply(401, {})
                    return
                body = json.loads(raw)
                if (
                    host == "inference.agents.internal"
                    and self.path == "/models/llm-main/v1/chat/completions"
                ):
                    gw.chat_requests.append(body)
                    if gw.tools:
                        op = gw.tools.pop(0)
                        response = chat_response(
                            tool_calls=[(op["executor"], op["arguments"])]
                        )
                    else:
                        response = chat_response("Completed.")
                    self.reply(200, response)
                elif host == "mcp.agents.internal" and self.path == "/kubernetes/mcp":
                    method = body["method"]
                    if method == "initialize":
                        result = {
                            "protocolVersion": body["params"]["protocolVersion"],
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "fixture", "version": "1"},
                        }
                    elif method == "tools/list":
                        result = {
                            "tools": [
                                {
                                    "name": item["tool"],
                                    "inputSchema": {"type": "object"},
                                }
                                for item in gw.fixtures["calls"]
                            ]
                        }
                    elif method == "tools/call":
                        params = body["params"]
                        match = [
                            item
                            for item in gw.fixtures["calls"]
                            if item["backend"] == "kubernetes"
                            and item["tool"] == params["name"]
                            and item["arguments"] == params["arguments"]
                        ]
                        if len(match) != 1:
                            self.reply(403, {})
                            return
                        gw.mcp_calls.append(params)
                        result = {
                            "content": [
                                {"type": "text", "text": match[0]["result"]["text"]}
                            ],
                            "isError": False,
                        }
                    elif method == "notifications/initialized":
                        self.reply(202, None)
                        return
                    else:
                        self.reply(400, {})
                        return
                    self.reply(
                        200, {"jsonrpc": "2.0", "id": body["id"], "result": result}
                    )
                else:
                    self.reply(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.url = f"https://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

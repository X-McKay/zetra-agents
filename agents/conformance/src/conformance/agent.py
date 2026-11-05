"""Adversarial probes for the conformance harness (spec 15.1).

This is the one agent allowed to import network modules: T1 and T8 need to attempt what
every other agent is forbidden to try. The sandbox's network policy and the gateway are
what stop it, which is what those tests prove. Results never include a token.
"""

import base64
import json
import os
import pathlib
import re
import socket
import time

import httpx
from agent_runtime.identity import BearerAuth, gateway_url, identity, tls_verify
from agent_runtime.tools import Tool

BACKEND = "kubernetes"
CONNECT_TIMEOUT = 2.0
MAX_BODY = 4096
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
# T3: where a token could be hiding.
TOKEN_ROOTS = ("/var/run/secrets", "/sandbox/state")


def claims_of(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def audiences(claims: list[dict]) -> list[str]:
    """The distinct `aud` values across claims, so a report can name the token kind in a few
    characters: the platform keeps only 512 characters of the agent's summary (T4)."""
    out: set[str] = set()
    for c in claims:
        aud = c.get("aud")
        for a in aud if isinstance(aud, list) else [aud]:
            if isinstance(a, str) and a:
                out.add(a)
    return sorted(out)


def redact(text: str) -> tuple[str, list[dict]]:
    """Replace every JWT with a marker and return the claims, so tests can check them."""
    found = []

    def mark(match: re.Match) -> str:
        try:
            found.append(claims_of(match.group(0)))
        except (IndexError, ValueError):
            found.append({})
        return "[jwt]"

    return JWT.sub(mark, text), found


def create_agent(ctx) -> dict:
    async def probe_connect(host: str, port: str, proto: str = "tcp") -> dict:
        """Try to reach host:port (T1). Reports whether it connected and how long it took."""
        kind = socket.SOCK_DGRAM if proto == "udp" else socket.SOCK_STREAM
        started = time.monotonic()
        with socket.socket(socket.AF_INET, kind) as sock:
            sock.settimeout(CONNECT_TIMEOUT)
            try:
                sock.connect((host, int(port)))
                if proto == "udp":  # connect is local for UDP; only an answer proves reach
                    sock.send(b"\0")
                    sock.recv(1)
                connected, error = True, None
            except OSError as e:
                connected, error = False, type(e).__name__
        return {
            "connected": connected,
            "error": error,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }

    async def probe_http(
        host_header: str,
        path: str,
        body: str = "",
        headers: str = "{}",
        auth: str = "bearer",
        form: str = "",
    ) -> dict:
        """Send one request to the gateway (T4, T5, T8, T19). JWTs in the reply become claims."""
        send = {"Host": host_header, **json.loads(headers)}
        kwargs: dict = {"headers": send}
        if form:
            kwargs["data"] = json.loads(form)
        elif body:
            kwargs["content"] = body
        client = httpx.Client(
            base_url=gateway_url(),
            verify=tls_verify(),
            timeout=30.0,
            follow_redirects=False,
            auth=BearerAuth(identity()) if auth == "bearer" else None,
        )
        with client:
            r = client.request("POST" if body or form else "GET", path, **kwargs)
        text, claims = redact(r.text[:MAX_BODY])
        return {"status": r.status_code, "body": text, "claims": claims}

    async def probe_env() -> dict:
        """List the environment (T3): names, and any variable that holds a JWT."""
        return {
            "names": sorted(os.environ),
            "jwt_in": sorted(k for k, v in os.environ.items() if JWT.search(v)),
        }

    async def probe_files() -> dict:
        """Find token-like files (T3): each path, its mode and the claims of any JWT in it."""
        files = []
        for root in TOKEN_ROOTS:
            for path in sorted(p for p in pathlib.Path(root).rglob("*") if p.is_file()):
                try:
                    _, claims = redact(path.read_text(encoding="utf-8", errors="ignore"))
                except OSError as e:
                    files.append({"path": str(path), "error": type(e).__name__})
                    continue
                if claims:
                    mode = oct(path.stat().st_mode & 0o777)
                    files.append(
                        {
                            "path": str(path),
                            "mode": mode,
                            "aud": audiences(claims),
                            "claims": claims,
                        }
                    )
        return {"files": files}

    async def list_pods(namespace: str) -> dict:
        """List pods through the gateway's MCP route (T8, T11, T12)."""
        result = await ctx.mcp(BACKEND, "pods_list_in_namespace", {"namespace": namespace})
        return {"text": result["text"][:MAX_BODY]}

    return {
        "tools": [
            Tool(probe_connect, "remote_read"),
            Tool(probe_http, "remote_read"),
            Tool(probe_env, "workspace_read"),
            Tool(probe_files, "workspace_read"),
            Tool(list_pods, "remote_read"),
        ]
    }

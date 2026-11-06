"""Credential-free transport negatives; only this signed fixture may use sockets.

No target is task-controlled. The foreign CA and private key exist only in a
private temporary directory inside this sandbox and are removed on every exit.
"""

import contextlib
import ipaddress
import socket
import ssl
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from agent_runtime.identity import AgentIdentity, gateway_url, write_private
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

GATEWAY = "10.43.250.10"
PORT = 443


def plaintext_request():
    return b"GET /v1/token HTTP/1.1\r\nHost: token.agents.internal\r\nConnection: close\r\n\r\n"


def classify_plaintext(data, *, reset):
    if not data:
        return "connection_reset" if reset else "closed_without_http"
    # An explicit TLS-only HTTP error is also valid, but an arbitrary 4xx is not.
    if data.startswith(b"HTTP/1.1 400 ") and b"plain HTTP request was sent to HTTPS port" in data:
        return "explicit_tls_required"
    # RFC 5246 sections 6.2.1 and 7.2: one alert record, TLS 1.2 legacy
    # version, exactly two bytes, fatal level. Intentionally allow only the
    # decode_error(50) / unexpected_message(10) refusals relevant before a
    # handshake. Close-notify, warning, unknown, trailing and partial data fail.
    if len(data) == 7 and data[:6] == bytes.fromhex("150303000202") and data[6] in {10, 50}:
        return "tls_fatal_alert"
    return "unexpected_http" if data.startswith(b"HTTP/") else "unexpected_response"


def plaintext(host=GATEWAY, port=PORT):
    if (host, port) != (GATEWAY, PORT):
        raise ValueError("transport fixture requires the exact gateway TLS endpoint")
    try:
        with socket.create_connection((host, port), timeout=3) as stream:
            stream.settimeout(3)
            stream.sendall(plaintext_request())
            try:
                data, reset = b"", False
                deadline = time.monotonic() + 3
                # TCP reads can split records. Require EOF/reset within the
                # existing timeout and bound, so a valid prefix cannot hide
                # trailing application bytes on a later read.
                while len(data) <= 4096:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("transport receive deadline")
                    stream.settimeout(remaining)
                    chunk = stream.recv(4097 - len(data))
                    if not chunk:
                        break
                    data += chunk
                if len(data) > 4096:
                    return {"result": "unexpected_response", "credential_free": True}
            except ConnectionResetError:
                reset = True
            return {"result": classify_plaintext(data, reset=reset), "credential_free": True}
    except OSError as exc:
        return {"result": "error", "error_type": type(exc).__name__, "credential_free": True}


def gateway_positive(client=None):
    """Same SDK identity HTTP client, without refresh/assertion/authentication."""
    if gateway_url() not in {f"https://{GATEWAY}", f"https://{GATEWAY}:443"}:
        raise ValueError("transport fixture gateway differs from the fixed endpoint")
    with contextlib.ExitStack() as stack:
        if client is None:
            client = stack.enter_context(AgentIdentity()._client())
        response = client.get("/v1/token", headers={"Host": "token.agents.internal"})
        return {
            "status": response.status_code,
            "tls_url": response.request.url.scheme == "https",
            "credential_free": "authorization" not in response.request.headers,
        }


def make_certificates(root):
    now = datetime.now(UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ephemeral-t27-foreign-ca")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=10))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(minutes=10))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    for filename, data in {
        "ca.pem": ca.public_bytes(serialization.Encoding.PEM),
        "cert.pem": cert.public_bytes(serialization.Encoding.PEM),
        "key.pem": key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    }.items():
        write_private(root / filename, data.decode())


def verify_code(exc):
    """Inspect typed causes only; arbitrary exception text is never evidence/output."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ssl.SSLCertVerificationError):
            return exc.verify_code
        exc = exc.__cause__ or exc.__context__
    return None


def foreign_ca():
    count = 0

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal count
            count += 1
            if self.headers.get("Authorization"):
                raise ValueError("transport control must never carry credentials")
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_):
            pass

    with tempfile.TemporaryDirectory(prefix="t27-", dir="/tmp") as directory:
        root = Path(directory)
        make_certificates(root)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(root / "cert.pem", root / "key.pem")
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"https://127.0.0.1:{server.server_port}/control"
        try:
            with httpx.Client(
                verify=ssl.create_default_context(cafile=root / "ca.pem"),
                timeout=3,
                trust_env=False,
            ) as positive:
                status = positive.get(url).status_code
            positive_requests = count
            code = None
            rejected = False
            # Exercise the exact SDK identity client/TLS constructor. Its client
            # carries no auth until _refresh(), which this probe never invokes.
            with AgentIdentity()._client() as ordinary:
                try:
                    ordinary.get(url, timeout=3)
                except httpx.ConnectError as exc:
                    code = verify_code(exc)
                    rejected = code in (20, 21)
            return {
                "positive_status": status,
                "positive_requests": positive_requests,
                "negative_requests": count - positive_requests,
                "verify_code": code,
                "rejected": rejected,
                "credential_free": True,
            }
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            if thread.is_alive():
                raise TimeoutError("loopback control did not stop")


def run():
    # TLS reachability first makes a plaintext timeout distinguishable from a
    # reachable TLS listener deliberately closing an invalid plaintext stream.
    return {
        "version": 1,
        "positive": gateway_positive(),
        "plaintext": plaintext(),
        "foreign_ca": foreign_ca(),
    }

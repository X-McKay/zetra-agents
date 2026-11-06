"""Signed deterministic budget fixture; explicitly replaces only this image's SDK step.

No model orchestrates these calls. Actual statuses are never retried, and arbitrary
response bodies, headers, exception messages and bearer tokens are never evidence.
"""

import concurrent.futures
import json
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from agent_runtime.identity import env, gateway_url, identity, tls_verify, write_private

BUDGET_FIXTURE_OVERRIDE = "budget-conformance-v1"
PATH = "/models/llm-budget-conformance/v1/chat/completions"
MODEL = "conformance-byte-v1"
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")


def load_manifest():
    from agent_runtime._budget_sdk_step import load_manifest as load

    return load()


def build_agent(manifest):
    from agent_runtime._budget_sdk_step import build_agent as build

    return build(manifest)


def now():
    return datetime.now(UTC).isoformat()


def call(label, hold_ms=0, *, client=None, token=None):
    if client is None:
        with httpx.Client(
            base_url=gateway_url(), verify=tls_verify(), timeout=25, follow_redirects=False
        ) as real:
            return call(label, hold_ms, client=real, token=identity().token())
    trace_id = uuid.uuid4().hex
    result = {
        "label": label,
        "trace_id": trace_id,
        "started_at": now(),
        "hold_ms": hold_ms,
        "status": None,
    }
    start = time.monotonic()
    try:
        response = client.post(
            PATH,
            headers={
                "Host": os.environ.get("AGENT_INFERENCE_HOST", "agents.almckay.io"),
                "Authorization": f"Bearer {token}",
                "traceparent": f"00-{trace_id}-{uuid.uuid4().hex[:16]}-01",
                "x-conformance-hold-ms": str(hold_ms),
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": "x" * 46}],
                "max_tokens": 50,
                "n": 1,
                "stream": False,
                "temperature": 0,
            },
        )
        result["status"] = response.status_code
        # Bound the only parsing performed; raw text is never stored or printed.
        if len(response.content) <= 8192:
            try:
                data = response.json()
            except ValueError:
                data = {}
            if isinstance(data, dict):
                if response.status_code == 200:
                    usage = data.get("usage", {})
                    if isinstance(usage, dict):
                        for source, target in (
                            ("prompt_tokens", "input_tokens"),
                            ("completion_tokens", "output_tokens"),
                            ("total_tokens", "total_tokens"),
                        ):
                            value = usage.get(source)
                            if type(value) is int and 0 <= value <= 300:
                                result[target] = value
                if data.get("reason") == "deny.budget_exhausted":
                    result["reason"] = "deny.budget_exhausted"
                decision = data.get("decision_id")
                if isinstance(decision, str) and UUID.fullmatch(decision):
                    result["decision_id"] = decision
    except httpx.HTTPError as exc:
        result["error"] = type(exc).__name__
    result.update(finished_at=now(), elapsed_ms=round((time.monotonic() - start) * 1000, 3))
    return result


def document(boundary, done, calls):
    return {
        "boundary": boundary,
        "kind": "tool",
        "done": done,
        "tool": "budget_fixture",
        "usage": {
            "input_tokens": sum(c.get("input_tokens", 0) for c in calls if c["status"] == 200),
            "output_tokens": sum(c.get("output_tokens", 0) for c in calls if c["status"] == 200),
        },
        "summary": "deterministic budget evidence committed",
    }


def execute(req, root, *, call_fn=call, sleep=time.sleep, hostname=None):
    case, boundary = req["task"]["budget_case"], req["boundary"]
    if (
        case not in {"day", "session", "control", "image_check"}
        or type(boundary) is not int
        or boundary < 0
    ):
        raise ValueError("invalid budget fixture task")
    state_file = root / "state/state.json"
    (root / "workspace").mkdir(parents=True, exist_ok=True)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    if case == "image_check":
        return document(boundary, True, []), 2
    if boundary == 0:
        state = {"next": 1, "usage": 0, "budget": {"schema": 1, "case": case, "calls": []}}
        write_private(state_file, json.dumps(state))
        sleep(20)  # trusted harness must observe zero before the first model request
        return document(0, False, []), 0
    state = json.loads(state_file.read_text())
    if state["next"] != boundary or state["budget"]["case"] != case:
        raise ValueError("checkpoint mismatch")
    report = state["budget"]
    calls = []
    done = False
    if case == "day" and boundary == 1:
        for i in range(18):
            calls.append(call_fn(f"spend-{i}"))
            sleep(6)  # every status is retained, including unexpected 429
    elif case == "day" and boundary == 2:
        calls.append(call_fn("exhausted"))
        sleep(120)  # external harness/operator replaces both gateway replicas
        calls.append(call_fn("after_restart"))
        done = True
    elif case == "control" and boundary == 1:
        calls.append(call_fn("control-before"))
        sleep(240)  # remain active throughout the primary session's recovery
        calls.append(call_fn("control-after"))
        sleep(6)
        done = True
    elif case == "session" and boundary == 1:
        calls.append(call_fn("warm"))
        sleep(6)
    elif case == "session" and boundary == 2:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            calls = list(pool.map(lambda i: call_fn(f"concurrent-{i}", 5000), range(10)))
        sleep(6)
    elif case == "session" and boundary == 3:
        for i in range(4):
            calls.append(call_fn(f"fill-{i}"))
            sleep(6)
        calls.append(call_fn("exhausted"))
    elif case == "session" and boundary == 4:
        report["tamper_before"] = state["usage"]
        state["usage"] = 0
        write_private(state_file, json.dumps(state))
        report["tamper_after"] = json.loads(state_file.read_text())["usage"]
        calls.append(call_fn("tampered"))
    elif case == "session" and boundary == 5:
        host = hostname if hostname is not None else env("HOSTNAME")
        if host.endswith("-g1"):
            # Unknown wire outcome -> normal runner delete/fence/create and snapshot restore.
            return None, 0
        if not host.endswith("-g2"):
            raise ValueError("unexpected fixture generation")
        report["restored_usage"] = state["usage"]
        calls.append(call_fn("restored"))
        done = True
    else:
        raise ValueError("unexpected fixture boundary")
    report["calls"].extend(calls)
    state["usage"] += sum(c.get("total_tokens", 0) for c in calls if c["status"] == 200)
    state["next"] = boundary + 1
    write_private(state_file, json.dumps(state))
    return document(boundary, done, calls), 2 if done else 0


def main():
    try:
        header = sys.stdin.buffer.readline(16)
        if not re.fullmatch(rb"[0-9]{1,6}\n", header) or not 0 < int(header) <= 65536:
            return 5
        body = sys.stdin.buffer.read(int(header))
        if len(body) != int(header):
            return 5
        result, code = execute(
            json.loads(body), Path(os.environ.get("AGENT_SANDBOX_DIR", "/sandbox"))
        )
        print(
            "{deliberately invalid budget fixture response"
            if result is None
            else json.dumps(result)
        )
        return code
    except Exception as exc:  # noqa: BLE001 - never leak arbitrary failure messages
        print(type(exc).__name__, file=sys.stderr)
        return 5


if __name__ == "__main__":
    sys.exit(main())

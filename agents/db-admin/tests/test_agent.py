import ast
import hashlib
import inspect
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from agent_runtime import step

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "inspect_instance",
    "inspect_connections",
    "inspect_database_stats",
    "inspect_blocking",
    "write_report",
}


def test_manifest_grants_only_fixed_diagnostics_without_delegation():
    manifest = yaml.safe_load((ROOT / "agent.yaml").read_text())
    cr = yaml.safe_load((ROOT / "deploy/agent.yaml").read_text())
    assert manifest["name"] == cr["metadata"]["name"] == "db-admin"
    assert cr["metadata"]["namespace"] == "tenant-test"
    assert cr["spec"]["identity"] == {"mode": "agent"}
    assert cr["spec"]["runtime"] == {"cpu": "1", "memory": "2Gi", "ttlSeconds": 900}
    assert cr["spec"]["capabilities"]["mcp"] == [
        {
            "backend": "postgres-admin",
            "effect": "remote_read",
            "tools": ["execute_sql"],
            "delegation": "inherit",
        }
    ]
    assert {t["name"] for t in manifest["tools"]} == TOOLS
    assert all(
        t["effect"] == ("workspace_write" if t["name"] == "write_report" else "remote_read")
        for t in manifest["tools"]
    )
    assert manifest["model"]["max_tokens"] == 1024
    assert cr["spec"]["capabilities"]["models"][0]["budget"] == {
        "tokensPerDay": 1000000,
        "tokensPerSession": 100000,
    }


NOW = datetime(2026, 11, 6, 21, 0, tzinfo=UTC)
STAMP = NOW.isoformat()
ROWS = {
    "instance": [
        {
            "observed_at": STAMP,
            "server_version_num": 180000,
            "in_recovery": False,
            "uptime_seconds": 500,
            "max_connections": 200,
            "database_count": 20,
        }
    ],
    "connections": [
        {
            "observed_at": STAMP,
            "state": "active",
            "wait_event_type": "none",
            "connections": 4,
            "total_groups": 1,
            "total_connections": 4,
            "max_transaction_age_seconds": 2,
            "max_query_age_seconds": 1,
        }
    ],
    "database_stats": [
        {
            "observed_at": STAMP,
            "database_name": "postgres",
            "size_bytes": 100000,
            "numbackends": 4,
            "xact_commit": 10,
            "xact_rollback": 1,
            "blks_read": 2,
            "blks_hit": 100,
            "deadlocks": 0,
            "temp_bytes": 0,
            "stats_reset": None,
        }
    ],
    "blocking": [
        {
            "observed_at": STAMP,
            "blocked_connections": 0,
            "blocking_edges": 0,
            "oldest_wait_seconds": None,
            "max_blocked_query_age_seconds": None,
            "max_blocked_transaction_age_seconds": None,
        }
    ],
}
VIEW = {
    "instance": "instance_health",
    "connections": "connection_summary",
    "database_stats": "database_stats",
    "blocking": "blocking_summary",
}


class Mcp:
    def __init__(self, rows=None, text=None, error=None):
        self.rows = rows
        self.text = text
        self.error = error
        self.calls = []

    async def __call__(self, backend, tool, arguments):
        self.calls.append((backend, tool, arguments))
        if self.error:
            raise self.error
        key = next(k for k, v in VIEW.items() if f".{v} AS result" in arguments["sql"])
        rows = self.rows if self.rows is not None else ROWS[key]
        text = (
            self.text
            if self.text is not None
            else repr([{"payload": json.dumps(row)} for row in rows])
        )
        return {"backend": backend, "tool": tool, "text": text}


def tools(tmp_path, monkeypatch, mcp):
    from db_admin import agent

    monkeypatch.setattr(agent, "now_utc", lambda: NOW)
    ctx = SimpleNamespace(workspace=tmp_path, instructions="", mcp=mcp)
    return {t.fn.__name__: t.fn for t in agent.create_agent(ctx)["tools"]}


@pytest.fixture
def app(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    shutil.copy(ROOT / "agent.yaml", app / "agent.yaml")
    shutil.copytree(ROOT / "src/db_admin", app / "db_admin")
    monkeypatch.setenv("AGENT_APP_DIR", str(app))
    monkeypatch.setenv("AGENT_SANDBOX_DIR", str(tmp_path / "sandbox"))
    return app


def test_packaged_factory_and_manifest_use_normal_sdk(app):
    instructions, built = step.build_agent(step.load_manifest())
    assert set(built) == TOOLS and "untrusted" in instructions
    for name in TOOLS - {"write_report"}:
        assert inspect.signature(built[name].fn).parameters == {}
    assert set(inspect.signature(built["write_report"].fn).parameters) == {
        "findings",
        "advice",
        "unknowns",
    }


async def test_each_diagnostic_is_one_exact_fixed_view_query(tmp_path, monkeypatch):
    mcp = Mcp()
    fns = tools(tmp_path, monkeypatch, mcp)
    for key in VIEW:
        result = await fns["inspect_" + key]()
        assert result["status"] == "available"
        assert result["check"] == key and result["rows"] == ROWS[key]
    assert mcp.calls == [
        (
            "postgres-admin",
            "execute_sql",
            {
                "sql": f"SELECT row_to_json(result)::text AS payload FROM db_admin_monitor.{v} AS result LIMIT 16;"
            },
        )
        for v in VIEW.values()
    ]
    for name in TOOLS - {"write_report"}:
        with pytest.raises(TypeError):
            await fns[name](sql="DELETE FROM application")
    assert len(mcp.calls) == 4


async def test_raw_server_errors_and_sql_never_enter_evidence(tmp_path, monkeypatch):
    mcp = Mcp(error=RuntimeError("private query SELECT sensitive_value FROM account"))
    result = await tools(tmp_path, monkeypatch, mcp)["inspect_instance"]()
    assert result["status"] == "unavailable" and result["error"] == "mcp_unavailable"
    data = (tmp_path / result["evidence"]).read_text()
    assert "sensitive_value" not in data and "SELECT" not in data and "RuntimeError" not in data


@pytest.mark.parametrize(
    "text",
    [
        "not structured output",
        "__import__('os').system('whoami')",
        repr([{"payload": "{}", "query": "private"}]),
        repr([{"payload": '{"observed_at":"x","observed_at":"y"}'}]),
        repr([{"payload": '{"observed_at": NaN}'}]),
        "x" * 16001,
        repr([{"payload": json.dumps(ROWS["instance"][0])}] * 17),
    ],
)
async def test_invalid_outer_transport_or_payload_is_explicitly_unavailable(
    tmp_path, monkeypatch, text
):
    result = await tools(tmp_path, monkeypatch, Mcp(text=text))["inspect_instance"]()
    assert result["status"] == "unavailable" and result["rows"] == []
    assert result["error"] == "invalid_result"
    assert text not in (tmp_path / result["evidence"]).read_text()


@pytest.mark.parametrize(
    "change",
    [
        {"max_connections": True},
        {"database_count": -1},
        {"query": "private SQL"},
        {"observed_at": "2020-01-01T00:00:00+00:00"},
        {"observed_at": "2026-11-06T21:00:00"},
        {"observed_at": "2026-11-07T21:00:00+00:00"},
        {"uptime_seconds": None},
    ],
)
async def test_unexpected_columns_types_and_stale_timestamps_are_not_health(
    tmp_path, monkeypatch, change
):
    result = await tools(tmp_path, monkeypatch, Mcp(rows=[{**ROWS["instance"][0], **change}]))[
        "inspect_instance"
    ]()
    assert result["status"] == "unavailable"


async def test_evidence_is_timestamped_hash_addressed_and_changed_values_preserve_prior(
    tmp_path, monkeypatch
):
    mcp = Mcp()
    fns = tools(tmp_path, monkeypatch, mcp)
    first = await fns["inspect_instance"]()
    mcp.rows = [{**ROWS["instance"][0], "database_count": 21}]
    second = await fns["inspect_instance"]()
    assert first["evidence"] != second["evidence"]
    for value in (first, second):
        path = tmp_path / value["evidence"]
        raw = path.read_bytes()
        assert path.stem.endswith(hashlib.sha256(raw).hexdigest())
        assert json.loads(raw)["collected_at"] == STAMP
    assert json.loads((tmp_path / first["evidence"]).read_text())["rows"][0]["database_count"] == 20


async def test_report_has_automatic_provenance_partial_coverage_and_scope_limits(
    tmp_path, monkeypatch
):
    fns = tools(tmp_path, monkeypatch, Mcp())
    result = await fns["write_report"](
        "Not enough data", "Collect the fixed diagnostics", "Database observations missing"
    )
    assert result["status"] == "unavailable"
    observation = await fns["inspect_database_stats"]()
    result = await fns["write_report"](
        "One database snapshot observed",
        "Review counters with the operator",
        "Other checks unavailable",
    )
    assert result["path"] == "report.md"
    report = (tmp_path / "report.md").read_text()
    assert STAMP in report and "Findings" in report and "Advice" in report and "Unknowns" in report
    assert observation["evidence"] in report and "incomplete" in report.lower()
    assert "16" in report and "cumulative" in report and "backup" in report.lower()
    assert "instance" in report and "blocking" in report and "connections" in report


async def test_report_rejects_forged_evidence_paths_raw_sql_and_healthy_claims(
    tmp_path, monkeypatch
):
    fns = tools(tmp_path, monkeypatch, Mcp())
    await fns["inspect_instance"]()
    for findings in ("See evidence/fake.json", "SELECT * FROM accounts", "The instance is healthy"):
        result = await fns["write_report"](findings, "Human review only", "Other checks missing")
        assert result["status"] == "unavailable"
    assert not (tmp_path / "report.md").exists()


def test_agent_source_has_no_direct_network_process_or_dynamic_sql_imports():
    names = set()
    for path in (ROOT / "src").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names.update(x.name.split(".")[0] for x in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
    assert not names & {
        "httpx",
        "requests",
        "urllib",
        "socket",
        "aiohttp",
        "subprocess",
        "os",
        "sys",
        "psycopg",
        "psycopg2",
    }


async def test_connection_coverage_is_exact_and_zero_blocking_nulls_are_not_missing(
    tmp_path, monkeypatch
):
    mcp = Mcp(
        rows=[
            {
                **ROWS["connections"][0],
                "state": "idle",
                "total_groups": 20,
                "total_connections": 50,
                "max_query_age_seconds": None,
                "max_transaction_age_seconds": None,
            }
        ]
    )
    fns = tools(tmp_path, monkeypatch, mcp)
    connections = await fns["inspect_connections"]()
    assert connections["status"] == "available"
    assert any("omitted groups: 19" in note for note in connections["unknowns"])
    assert any("not applicable to non-active" in note for note in connections["unknowns"])
    mcp.rows = None
    blocking = await fns["inspect_blocking"]()
    assert blocking["status"] == "available" and any(
        "Zero blocked connections" in n for n in blocking["unknowns"]
    )
    assert not any("Unavailable values" in n for n in blocking["unknowns"])


async def test_reset_timestamp_null_preserves_available_cumulative_statistics(
    tmp_path, monkeypatch
):
    result = await tools(tmp_path, monkeypatch, Mcp())["inspect_database_stats"]()
    assert result["status"] == "available"
    assert any(
        "no recorded reset timestamp, not missing cumulative counters" in n
        for n in result["unknowns"]
    )


async def test_inconsistent_connection_totals_are_refused(tmp_path, monkeypatch):
    result = await tools(
        tmp_path, monkeypatch, Mcp(rows=[{**ROWS["connections"][0], "total_connections": 1}])
    )["inspect_connections"]()
    assert result["status"] == "unavailable"

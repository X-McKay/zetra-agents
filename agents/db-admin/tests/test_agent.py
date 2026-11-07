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
        "tokensPerSession": 200000,
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
    assert inspect.signature(built["write_report"].fn).parameters == {}
    assert step.schema(built["write_report"])["function"]["parameters"]["properties"] == {}
    assert step.schema(built["write_report"])["function"]["parameters"]["required"] == []


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


async def collect_all(fns):
    return {key: await fns["inspect_" + key]() for key in VIEW}


async def test_report_requires_all_four_attempts_and_names_missing_tool(tmp_path, monkeypatch):
    fns = tools(tmp_path, monkeypatch, Mcp())
    for key in ("instance", "connections", "database_stats"):
        await fns["inspect_" + key]()
    result = await fns["write_report"]()
    assert result["error"] == "missing_checks" and result["missing_tools"] == ["inspect_blocking"]
    assert "inspect_blocking" in result["hint"]
    assert not (tmp_path / "report.md").exists()
    await fns["inspect_blocking"]()
    assert (await fns["write_report"]())["coverage"] == "bounded_snapshot"


async def test_legacy_freeform_false_no_blocking_claim_cannot_be_written(tmp_path, monkeypatch):
    fns = tools(tmp_path, monkeypatch, Mcp())
    for key in ("instance", "connections", "database_stats"):
        await fns["inspect_" + key]()
    with pytest.raises(TypeError):
        await fns["write_report"](
            "No blocking detected", "Review with operator", "Other checks missing"
        )
    assert not (tmp_path / "report.md").exists()


async def test_report_is_derived_only_from_latest_observations_with_scope_limits(
    tmp_path, monkeypatch
):
    fns = tools(tmp_path, monkeypatch, Mcp())
    observations = await collect_all(fns)
    result = await fns["write_report"]()
    report = (tmp_path / "report.md").read_text()
    assert result["path"] == "report.md"
    assert STAMP in report and "Findings" in report and "Advice" in report and "Unknowns" in report
    assert all(r["evidence"] in report for r in observations.values())
    assert "16" in report and "cumulative" in report and "backup" in report.lower()
    assert "No blocking detected" not in report and "since deployment" not in report


async def test_unavailable_blocking_attempt_writes_honest_incomplete_report(tmp_path, monkeypatch):
    mcp = Mcp()
    fns = tools(tmp_path, monkeypatch, mcp)
    for key in ("instance", "connections", "database_stats"):
        await fns["inspect_" + key]()
    mcp.error = RuntimeError("private query text")
    await fns["inspect_blocking"]()
    result = await fns["write_report"]()
    report = (tmp_path / "report.md").read_text()
    assert result["coverage"] == "incomplete"
    assert "blocking: unavailable" in report and "mcp_unavailable" in report
    assert "No blocking detected" not in report and "private query text" not in report


async def test_latest_error_never_falls_back_to_old_success(tmp_path, monkeypatch):
    mcp = Mcp()
    fns = tools(tmp_path, monkeypatch, mcp)
    observations = await collect_all(fns)
    mcp.error = RuntimeError("unavailable")
    latest = await fns["inspect_blocking"]()
    result = await fns["write_report"]()
    report = (tmp_path / "report.md").read_text()
    assert result["coverage"] == "incomplete" and "blocking: unavailable" in report
    assert latest["evidence"] in report and observations["blocking"]["evidence"] not in report


async def test_positive_blocking_is_reported_as_facts_not_absence(tmp_path, monkeypatch):
    mcp = Mcp()
    fns = tools(tmp_path, monkeypatch, mcp)
    await collect_all(fns)
    mcp.rows = [
        {
            **ROWS["blocking"][0],
            "blocked_connections": 2,
            "blocking_edges": 3,
            "oldest_wait_seconds": 4,
        }
    ]
    await fns["inspect_blocking"]()
    await fns["write_report"]()
    report = (tmp_path / "report.md").read_text()
    assert '"blocked_connections": 2' in report and '"oldest_wait_seconds": 4' in report
    assert "No blocking detected" not in report
    assert "investigate the observed blocking" in report


async def test_stale_saved_success_is_unknown_at_report_time(tmp_path, monkeypatch):
    from datetime import timedelta

    from db_admin import agent

    fns = tools(tmp_path, monkeypatch, Mcp())
    await collect_all(fns)
    monkeypatch.setattr(agent, "now_utc", lambda: NOW + timedelta(minutes=6))
    result = await fns["write_report"]()
    report = (tmp_path / "report.md").read_text()
    assert result["coverage"] == "incomplete" and "stale_or_invalid_saved_result" in report
    assert '"blocked_connections": 0' not in report


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
    mcp = Mcp(rows=grouped_connections(20, 100))
    fns = tools(tmp_path, monkeypatch, mcp)
    connections = await fns["inspect_connections"]()
    assert connections["status"] == "available"
    assert any("omitted groups: 4" in note for note in connections["unknowns"])
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


def grouped_connections(groups, total, returned=None):
    return [
        {
            **ROWS["connections"][0],
            "state": "idle",
            "wait_event_type": f"wait{i}",
            "total_groups": groups,
            "total_connections": total,
            "max_query_age_seconds": None,
            "max_transaction_age_seconds": None,
        }
        for i in range(min(groups, 16) if returned is None else returned)
    ]


@pytest.mark.parametrize(
    "rows",
    [
        grouped_connections(1, 1000),
        grouped_connections(20, 1000, returned=1),
        grouped_connections(2, 8, returned=1),
        [{**ROWS["connections"][0], "connections": 0}],
        grouped_connections(20, 64),
    ],
)
async def test_impossible_connection_group_cardinality_and_totals_are_unavailable(
    tmp_path, monkeypatch, rows
):
    result = await tools(tmp_path, monkeypatch, Mcp(rows=rows))["inspect_connections"]()
    assert result["status"] == "unavailable" and result["error"] == "invalid_result"
    assert result["rows"] == []


@pytest.mark.parametrize(
    "change",
    [
        {
            "blocking_edges": 100,
            "oldest_wait_seconds": 3,
            "max_blocked_query_age_seconds": 5,
            "max_blocked_transaction_age_seconds": 8,
        },
        {"oldest_wait_seconds": 0},
        {"max_blocked_query_age_seconds": 1},
        {"max_blocked_transaction_age_seconds": 1},
        {"blocked_connections": 2, "blocking_edges": 1},
    ],
)
async def test_contradictory_blocking_counts_and_absence_are_unavailable(
    tmp_path, monkeypatch, change
):
    result = await tools(tmp_path, monkeypatch, Mcp(rows=[{**ROWS["blocking"][0], **change}]))[
        "inspect_blocking"
    ]()
    assert result["status"] == "unavailable" and result["error"] == "invalid_result"
    assert not any("Zero blocked connections" in note for note in result["unknowns"])


async def test_positive_blocking_allows_transient_missing_age_and_counts_prepared_edges(
    tmp_path, monkeypatch
):
    result = await tools(
        tmp_path,
        monkeypatch,
        Mcp(rows=[{**ROWS["blocking"][0], "blocked_connections": 2, "blocking_edges": 2}]),
    )["inspect_blocking"]()
    assert result["status"] == "available"
    assert any("actual wait age is unknown" in note for note in result["unknowns"])


async def test_connection_totals_allow_exact_complete_and_minimal_omitted_groups(
    tmp_path, monkeypatch
):
    for groups, total in ((2, 8), (16, 64), (20, 68)):
        result = await tools(tmp_path, monkeypatch, Mcp(rows=grouped_connections(groups, total)))[
            "inspect_connections"
        ]()
        assert result["status"] == "available"


async def test_missing_check_does_not_overwrite_existing_report(tmp_path, monkeypatch):
    fns = tools(tmp_path, monkeypatch, Mcp())
    for key in ("instance", "connections", "database_stats"):
        await fns["inspect_" + key]()
    (tmp_path / "report.md").write_text("preserved prior report")
    assert (await fns["write_report"]())["missing_tools"] == ["inspect_blocking"]
    assert (tmp_path / "report.md").read_text() == "preserved prior report"


async def test_latest_invalid_saved_rows_do_not_resurrect_an_older_success(tmp_path, monkeypatch):
    fns = tools(tmp_path, monkeypatch, Mcp())
    observations = await collect_all(fns)
    record = json.loads((tmp_path / observations["blocking"]["evidence"]).read_text())
    record["observation_index"] = 5
    record["rows"][0]["blocking_edges"] = 100
    raw = json.dumps(record, sort_keys=True, indent=2).encode()
    name = "blocking-" + hashlib.sha256(raw).hexdigest() + ".json"
    (tmp_path / "evidence" / name).write_bytes(raw)
    result = await fns["write_report"]()
    report = (tmp_path / "report.md").read_text()
    assert result["coverage"] == "incomplete"
    assert "blocking: unavailable" in report and "stale_or_invalid_saved_result" in report
    assert observations["blocking"]["evidence"] not in report
    assert '"blocking_edges": 100' not in report

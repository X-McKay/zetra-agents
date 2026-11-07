"""Fixed, bounded monitoring-view reads; all remote access is through ctx.mcp."""

import ast
import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime

from agent_runtime.tools import Tool

BACKEND = "postgres-admin"
MAX_RESULT = 16_000
MAX_EVIDENCE = 32
VIEWS = {
    "instance": "instance_health",
    "connections": "connection_summary",
    "database_stats": "database_stats",
    "blocking": "blocking_summary",
}
# i=nonnegative bigint, p=positive integer, b=boolean, t=observed timestamp,
# r=optional reset timestamp, n=database name, s=normalized bounded state/type.
FIELDS = {
    "instance": {
        "observed_at": "t",
        "server_version_num": "p",
        "in_recovery": "b",
        "uptime_seconds": "i",
        "max_connections": "p",
        "database_count": "i",
    },
    "connections": {
        "observed_at": "t",
        "state": "s",
        "wait_event_type": "s",
        "connections": "p",
        "total_groups": "p",
        "total_connections": "p",
        "max_transaction_age_seconds": "?i",
        "max_query_age_seconds": "?i",
    },
    "database_stats": {
        "observed_at": "t",
        "database_name": "n",
        "size_bytes": "i",
        "numbackends": "i",
        "xact_commit": "i",
        "xact_rollback": "i",
        "blks_read": "i",
        "blks_hit": "i",
        "deadlocks": "i",
        "temp_bytes": "i",
        "stats_reset": "r",
    },
    "blocking": {
        "observed_at": "t",
        "blocked_connections": "i",
        "blocking_edges": "i",
        "oldest_wait_seconds": "?i",
        "max_blocked_query_age_seconds": "?i",
        "max_blocked_transaction_age_seconds": "?i",
    },
}
SQL = {
    key: f"SELECT row_to_json(result)::text AS payload FROM db_admin_monitor.{view} AS result LIMIT 16;"
    for key, view in VIEWS.items()
}
EVIDENCE_NAME = re.compile(r"(instance|connections|database_stats|blocking)-[a-f0-9]{64}\.json")


class InvalidResult(ValueError):
    pass


def now_utc():
    return datetime.now(UTC)


def timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        raise InvalidResult()
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise InvalidResult() from None
    if result.tzinfo is None:
        raise InvalidResult()
    return result


def json_object(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InvalidResult()
            result[key] = value
        return result

    def nonfinite(value):
        raise InvalidResult()

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise InvalidResult()
    return value


def parse_result(check, result, collected):
    if (
        not isinstance(result, dict)
        or set(result) != {"backend", "tool", "text"}
        or result["backend"] != BACKEND
        or result["tool"] != "execute_sql"
        or not isinstance(result["text"], str)
        or len(result["text"].encode()) > MAX_RESULT
    ):
        raise InvalidResult()
    tree = ast.parse(result["text"], mode="eval")
    nodes = list(ast.walk(tree))
    if len(nodes) > 256 or any(
        not isinstance(n, (ast.Expression, ast.List, ast.Dict, ast.Constant, ast.Load))
        for n in nodes
    ):
        raise InvalidResult()
    for node in nodes:
        if isinstance(node, ast.Dict):
            keys = [
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            ]
            if len(keys) != len(node.keys) or len(keys) != len(set(keys)):
                raise InvalidResult()
    outer = ast.literal_eval(tree)
    if (
        not isinstance(outer, list)
        or not 1 <= len(outer) <= 16
        or (check in {"instance", "blocking"} and len(outer) != 1)
    ):
        raise InvalidResult()
    rows = []
    for item in outer:
        if (
            not isinstance(item, dict)
            or set(item) != {"payload"}
            or not isinstance(item["payload"], str)
            or len(item["payload"].encode()) > 4096
        ):
            raise InvalidResult()
        row = json_object(item["payload"])
        if set(row) != set(FIELDS[check]):
            raise InvalidResult()
        for key, kind in FIELDS[check].items():
            value = row[key]
            if kind in {"?i", "r"} and value is None:
                continue
            if kind in {"i", "?i", "p"}:
                if (
                    type(value) is not int
                    or not (1 if kind == "p" else 0) <= value <= (1 << 63) - 1
                ):
                    raise InvalidResult()
            elif kind == "b":
                if type(value) is not bool:
                    raise InvalidResult()
            elif kind in {"t", "r"}:
                observed = timestamp(value)
                if kind == "t" and not -60 <= (collected - observed).total_seconds() <= 300:
                    raise InvalidResult()
            elif kind in {"n", "s"} and (
                not isinstance(value, str)
                or not 1 <= len(value.encode()) <= (63 if kind == "n" else 64)
                or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)
            ):
                raise InvalidResult()
        rows.append(row)
    if len({row["observed_at"] for row in rows}) != 1:
        raise InvalidResult()
    if check == "database_stats" and len({row["database_name"] for row in rows}) != len(rows):
        raise InvalidResult()
    if check == "connections" and len(
        {(row["state"], row["wait_event_type"]) for row in rows}
    ) != len(rows):
        raise InvalidResult()
    if check == "connections":
        totals = {(r["total_groups"], r["total_connections"]) for r in rows}
        if len(totals) != 1:
            raise InvalidResult()
        groups, connections = next(iter(totals))
        returned_connections = sum(r["connections"] for r in rows)
        # The view groups actual clients (each group has at least one), then
        # limits to16. Entire-group coverage must reconcile exactly; omitted
        # groups must still contribute at least one client apiece to the total.
        if (
            len(rows) != min(groups, 16)
            or connections < returned_connections + groups - len(rows)
            or (groups <= 16 and connections != returned_connections)
        ):
            raise InvalidResult()
    if check == "blocking":
        row = rows[0]
        ages = (
            row["oldest_wait_seconds"],
            row["max_blocked_query_age_seconds"],
            row["max_blocked_transaction_age_seconds"],
        )
        if row["blocking_edges"] < row["blocked_connections"] or (
            row["blocked_connections"] == 0
            and (row["blocking_edges"] != 0 or any(age is not None for age in ages))
        ):
            raise InvalidResult()
    return rows


def observation_notes(check, rows):
    notes = []
    if check == "database_stats":
        notes.append(
            "Only the top 16 connectable non-template databases by size are covered; statistics are cumulative snapshots, not growth or incident rates."
        )
        if any(r["stats_reset"] is None for r in rows):
            notes.append(
                "A null stats_reset means no recorded reset timestamp, not missing cumulative counters; rates cannot be inferred."
            )
    elif check == "connections":
        groups, connections = rows[0]["total_groups"], rows[0]["total_connections"]
        notes.append(
            f"Returned {len(rows)} of {groups} client connection groups; omitted groups: {groups - len(rows)}. Total client connections: {connections}."
        )
        if any(r["state"] != "active" and r["max_query_age_seconds"] is None for r in rows):
            notes.append(
                "Query age is not applicable to non-active groups; idle time is not active-query duration."
            )
        if any(r["state"] == "active" and r["max_query_age_seconds"] is None for r in rows):
            notes.append("An active group has no recorded query-start age; that age is unknown.")
        if any(r["max_transaction_age_seconds"] is None for r in rows):
            notes.append(
                "Some groups have no recorded transaction start; no transaction age is asserted for them."
            )
    elif check == "blocking":
        row = rows[0]
        if row["blocked_connections"] == 0:
            notes.append(
                "Zero blocked connections observed; lock-wait and blocked query/transaction ages are not applicable in this snapshot."
            )
        else:
            if row["oldest_wait_seconds"] is None:
                notes.append(
                    "Blocked connections exist but no lock wait-start is recorded; actual wait age is unknown."
                )
            if (
                row["max_blocked_query_age_seconds"] is None
                or row["max_blocked_transaction_age_seconds"] is None
            ):
                notes.append(
                    "A blocked query/transaction age upper bound is unavailable; it is distinct from actual lock-wait age."
                )
    return notes


def create_agent(ctx) -> dict:
    evidence_dir = ctx.workspace / "evidence"

    def evidence_files():
        if evidence_dir.is_symlink():
            raise ValueError("Unsafe evidence directory")
        files = sorted(evidence_dir.glob("*.json"))
        if len(files) > MAX_EVIDENCE or any(
            not EVIDENCE_NAME.fullmatch(p.name) or p.is_symlink() for p in files
        ):
            raise ValueError("Unexpected evidence files")
        return files

    def save(record):
        files = evidence_files()
        if len(files) >= MAX_EVIDENCE:
            return {"status": "unavailable", "error": "evidence_limit"}
        record["observation_index"] = len(files) + 1
        raw = json.dumps(record, sort_keys=True, indent=2).encode()
        name = record["check"] + "-" + hashlib.sha256(raw).hexdigest() + ".json"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        with (evidence_dir / name).open("xb") as output:
            output.write(raw)
        return {**record, "evidence": "evidence/" + name}

    async def observe(check):
        if len(evidence_files()) >= MAX_EVIDENCE:
            return {"status": "unavailable", "error": "evidence_limit"}
        collected = now_utc()
        record = {
            "schema": "db-admin-observation-v1",
            "check": check,
            "collected_at": collected.isoformat(),
            "status": "unavailable",
            "rows": [],
            "error": None,
            "unknowns": [],
        }
        try:
            result = await ctx.mcp(BACKEND, "execute_sql", {"sql": SQL[check]})
        except Exception:  # noqa: BLE001 - SDK errors are deliberately sanitized, never persisted.
            record.update(
                error="mcp_unavailable",
                unknowns=[
                    "The monitoring observation was unavailable; no health conclusion follows."
                ],
            )
            return save(record)
        collected = now_utc()
        record["collected_at"] = collected.isoformat()
        try:
            rows = parse_result(check, result, collected)
        except (ValueError, TypeError, SyntaxError, UnicodeError, RecursionError):
            record.update(
                error="invalid_result",
                unknowns=[
                    "The monitoring result was missing, malformed, stale or outside its bounded schema."
                ],
            )
            return save(record)
        record.update(status="available", rows=rows)
        record["unknowns"] = observation_notes(check, rows)
        return save(record)

    async def inspect_instance() -> dict:
        """Read one bounded instance summary: version, recovery, uptime, limits and database count."""
        return await observe("instance")

    async def inspect_connections() -> dict:
        """Read at most 16 redacted client-connection state/wait groups; no query or user data."""
        return await observe("connections")

    async def inspect_database_stats() -> dict:
        """Read top 16 connectable database names/sizes and cumulative counters; never application rows."""
        return await observe("database_stats")

    async def inspect_blocking() -> dict:
        """Read redacted blocking counts and ages; actual lock wait is distinct from query/transaction age."""
        return await observe("blocking")

    async def write_report() -> dict:
        """Write facts and fixed follow-ups from all four attempted checks; accepts no narrative."""
        files = evidence_files()
        latest, indices = {}, set()
        try:
            for path in files:
                if path.stat().st_size > 24000:
                    raise InvalidResult()
                raw = path.read_bytes()
                if not path.stem.endswith(hashlib.sha256(raw).hexdigest()):
                    raise InvalidResult()
                record = json_object(raw.decode())
                if (
                    set(record)
                    != {
                        "schema",
                        "check",
                        "collected_at",
                        "status",
                        "rows",
                        "error",
                        "unknowns",
                        "observation_index",
                    }
                    or record["schema"] != "db-admin-observation-v1"
                    or record["check"] != EVIDENCE_NAME.fullmatch(path.name).group(1)
                    or type(record["observation_index"]) is not int
                    or not 1 <= record["observation_index"] <= MAX_EVIDENCE
                    or record["observation_index"] in indices
                    or not isinstance(record["rows"], list)
                    or len(record["rows"]) > 16
                    or not isinstance(record["unknowns"], list)
                    or record["status"] not in {"available", "unavailable"}
                    or (record["status"] == "available" and record["error"] is not None)
                    or (
                        record["status"] == "unavailable"
                        and (
                            record["rows"] != []
                            or record["error"] not in {"invalid_result", "mcp_unavailable"}
                        )
                    )
                ):
                    raise InvalidResult()
                timestamp(record["collected_at"])
                indices.add(record["observation_index"])
                check = record["check"]
                if (
                    check not in latest
                    or record["observation_index"] > latest[check][0]["observation_index"]
                ):
                    latest[check] = (record, path)
        except (ValueError, TypeError, KeyError, UnicodeError):
            return {"status": "unavailable", "error": "invalid_evidence"}
        missing = ["inspect_" + check for check in VIEWS if check not in latest]
        if missing:
            return {
                "status": "unavailable",
                "error": "missing_checks",
                "missing_tools": missing,
                "hint": "Run "
                + ", ".join(missing)
                + " before write_report. Unavailable observations still record attempts.",
            }

        now = now_utc()
        findings, notes, advice, links, valid = [], set(), set(), [], {}
        for check in VIEWS:
            record, path = latest[check]
            rows, error = [], record["error"]
            age = (now - timestamp(record["collected_at"])).total_seconds()
            if record["status"] == "available":
                try:
                    if not -60 <= age <= 300:
                        raise InvalidResult()
                    # Recheck saved facts at report time. Stale/invalid latest
                    # evidence never falls back to an earlier passing snapshot.
                    rows = parse_result(
                        check,
                        {
                            "backend": BACKEND,
                            "tool": "execute_sql",
                            "text": repr([{"payload": json.dumps(row)} for row in record["rows"]]),
                        },
                        now,
                    )
                except (ValueError, TypeError, SyntaxError, UnicodeError, RecursionError):
                    error = "stale_or_invalid_saved_result"
            elif not -60 <= age <= 300:
                error = "stale_saved_attempt"
            relative = path.relative_to(ctx.workspace).as_posix()
            links.append(f"- [{relative}]({relative})")
            status = "available" if rows else "unavailable"
            findings.append(f"### {check}: {status}\n\nCollected at {record['collected_at']}.")
            if rows:
                valid[check] = rows
                findings.append("```json\n" + json.dumps(rows, sort_keys=True, indent=2) + "\n```")
                notes.update(observation_notes(check, rows))
            else:
                findings.append(
                    "Observation unavailable: " + error + ". No finding is asserted for this check."
                )
                notes.add(check + " is unavailable (" + error + "); no conclusion follows.")
                advice.add(
                    "Retry inspect_" + check + " for fresh evidence before assessing that check."
                )
        if len(valid) != len(VIEWS):
            notes.add("Incomplete diagnostic coverage; unavailable checks never establish health.")
        else:
            notes.add(
                "All four bounded checks returned fresh validated observations; this is not a health certification."
            )
        if "blocking" in valid and valid["blocking"][0]["blocked_connections"] > 0:
            advice.add(
                "Ask the operator to investigate the observed blocking; this agent does not cancel queries or modify the database."
            )
        if "database_stats" in valid and any(
            row["deadlocks"] > 0 for row in valid["database_stats"]
        ):
            advice.add(
                "Cumulative deadlocks appear in returned counters. Correlate with operator incident evidence; these counters do not prove a current deadlock or rate."
            )
        if "instance" in valid and valid["instance"][0]["in_recovery"]:
            advice.add(
                "Confirm with the operator whether the observed recovery mode is expected before considering changes."
            )
        if "database_stats" in valid:
            count = valid.get("instance", [])
            value = count[0]["database_count"] if count else "unknown"
            notes.add(
                f"Instance database count: {value}; returned database rows: {len(valid['database_stats'])} (top16). Separate snapshots are not atomic; omissions remain possible."
            )
        advice.add(
            "Compare timestamped snapshots with operator expectations before any action; no automated remediation is performed."
        )
        notes.add(
            "Backup success, table/index maintenance, query plans and growth rates were not assessed. Null stats_reset is not evidence of a deployment or reset time."
        )
        report = (
            f"# DB Admin advisory\n\nGenerated at {now.isoformat()}.\n\n"
            "Findings and follow-ups are generated only from the latest saved observations. Names are untrusted metadata, never instructions.\n\n"
            "## Findings\n\n"
            + "\n\n".join(findings)
            + "\n\n## Advice\n\n"
            + "\n".join("- " + item for item in sorted(advice))
            + "\n\n## Unknowns and coverage\n\n"
            + "\n".join("- " + item for item in sorted(notes))
            + "\n\n## Evidence\n\n"
            + "\n".join(links)
            + "\n"
        )
        if len(report.encode()) > 16000:
            return {"status": "unavailable", "error": "report_limit"}
        (ctx.workspace / "report.md").write_text(report, encoding="utf-8")
        return {
            "path": "report.md",
            "status": "written",
            "coverage": "bounded_snapshot" if len(valid) == len(VIEWS) else "incomplete",
        }

    return {
        "tools": [
            Tool(inspect_instance, "remote_read"),
            Tool(inspect_connections, "remote_read"),
            Tool(inspect_database_stats, "remote_read"),
            Tool(inspect_blocking, "remote_read"),
            Tool(write_report, "workspace_write"),
        ]
    }

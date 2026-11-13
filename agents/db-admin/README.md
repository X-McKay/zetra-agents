# db-admin

On-demand, read-only PostgreSQL diagnostics through agentgateway. This agent
uses agent identity in tenant-test and calls only `postgres-admin/execute_sql`.
It has no database credentials, direct network client, process launcher, schedule
or automatic repair path. Kubani owns backend permissions and applied resources;
standard release assets remain unapproved until a separate reviewed change.
The model budget is1,000,000tokens/day and200,000/session. The session limit
covers llm-main's existing131,072-token first-request reservation; reservation
and ledger enforcement are unchanged.

Four argument-free tools read only `db_admin_monitor.instance_health`,
`connection_summary`, `database_stats` and `blocking_summary`. Each SQL string is
fixed in source, selects `row_to_json(result)::text AS payload` from its one view,
and ends with `LIMIT 16`. No user/model SQL, database/schema/table parameters,
application rows, raw query text or EXPLAIN ANALYZE are accepted. The dedicated
MCP login must have only the independently reviewed monitoring-view grants; it
must not inherit pg_monitor/pg_read_all_stats/admin. Backend restricted mode and
database permissions remain required independently of the fixed agent tools.

The stock MCP server returns Python's representation of a list of dictionaries,
not JSON. The views project JSON text into one `payload` field to avoid raw
Python datetime/Decimal representations. The agent accepts at most16000UTF-8
bytes, a bounded literal list with at most16 exact payload dictionaries, and
strict JSON with known columns, scalar types, fresh timezone-aware observation
timestamps and no duplicate keys. It saves only validated redacted rows or fixed
unavailability codes. Raw results, SQL and arbitrary exception text are not saved.
The SDK's larger truncation boundary cannot turn an oversized result into a pass.

Instance and blocking views require one row. Database names are allowed metadata,
but all returned strings are untrusted data. Database statistics cover the top16
connectable non-template databases by size; instance database_count covers that
population before the limit. Separate snapshots are not atomic. Connection totals
cover all client state/wait groups before the limit, making omitted group counts
explicit. Counters are cumulative, not growth or incident rates. A null reset
timestamp means no recorded reset; zero blocked connections makes blocked ages
inapplicable. Actual lock wait age and query/transaction age bounds remain distinct.
Missing fields, errors, stale/malformed results and absent active measurements
remain unknown; none establishes an overall health certification.

`write_report()` accepts no arguments and requires all four diagnostic checks to
have recorded an attempt. A missing attempt refuses the write and names the
exact missing tools. Unavailable attempts may produce an explicitly incomplete
report. Findings, unknowns and a small set of conditional operator follow-ups are
generated only from the latest saved observations, revalidated for freshness,
schema and cross-field consistency at report time. A latest error/stale result
never falls back to an earlier success. Prior observations remain saved, but only
the latest records are cited as current evidence. No model-authored prose enters
the report, and the model-facing SDK schema has zero parameters.

Reports retain timestamps, SHA-256 citations and the16KiB bound. Evidence remains
bounded to32 records; no backup-success, table/index-maintenance, query-plan or
overall health claims are made. v0.1.1 corrects v0.1.0's ability to write freeform
findings before all four checks were attempted. Source/fake-MCP tests do not
establish live gateway/role behavior; root owns normal-session smoke, source/image
verification, release and separate approval. No live operation or publication is
performed by this package's diagnostic tools.

v0.1.2 changes no agent code. It is the same agent rebuilt on the SDK at zetra `67c908a`.

# skill-rehearsal

Rehearsal agent for skills with scripts. It has no model: its `decide` writes `report.md`,
runs the script of the skill `report-check` on it through the platform's launcher
(`skill_run`), and writes the outcome into the report as `check: passed` or `check: failed`.
Its suite expects `check: passed`, so a passing evaluation shows that a skill's script ran
in a session.

It asks for the effect `sandbox_execute`, so its release is Ready only in a tenant whose
Namespace grants that effect. It uses no tool server and no model route.

Edit `agent.yaml` only; `zetra-agents render` writes `deploy/agent.yaml` and `skills.lock`.
The skill is at `skills/report-check/` in the repository root, where `db-admin` can list it
too; both then pin it by the same digest.

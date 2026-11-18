---
name: report-check
description: Checks that the report in the workspace is there, is within the size the platform reads, and has the heading lines the task needs. Use after report.md is written and before saying the work is done.
metadata:
  version: "1.0"
---

# Checking the report

A session's result is `report.md` in the workspace. The platform reads at most 16000 bytes
of it, as UTF-8 text. A report that is missing, larger than that, or without the headings
the task asked for is not a finished report, whatever was said about it.

## When

Run the check once, after `report.md` is written and before the final answer.

## How

Call `skill_run` with this skill, the script `scripts/check_report.py`, and one argument
for each line the report must hold, written exactly as the line appears:

```json
{"skill": "report-check", "script": "scripts/check_report.py", "arguments": ["## Findings", "## Advice"]}
```

With no arguments only the file itself is checked.

The script prints one line of JSON:

```json
{"report": "report.md", "ok": true, "bytes": 812, "missing": [], "problem": null}
```

- Exit status `0` and `"ok": true`: the report is in order.
- Exit status `1`: it is not. `missing` lists the lines that were not found; `problem` is
  `absent`, `not_a_file`, `too_large` or `not_text` when the file itself is at fault.
- Exit status `2`: an argument was empty or held a line break. Fix the arguments.

## Then

If the check fails, write the report again with what was missing and run the check once
more. Do not say the report is ready until the check passes. The script only reads the
report; it changes nothing and may be run any number of times.

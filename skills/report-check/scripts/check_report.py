"""Check `report.md` in the current directory, which is the session's workspace.

Each argument is a line the report must hold, compared whole after trailing spaces are
dropped. Prints one line of JSON and exits 0 when the report is in order, 1 when it is not
and 2 when an argument cannot be a line. Reads one file and writes nothing, so running it
again gives the same answer.
"""

import json
import os
import stat
import sys

REPORT = "report.md"
MAX_BYTES = 16000  # what the platform reads of a report


def check(lines):
    answer = {"report": REPORT, "ok": False, "bytes": None, "missing": [], "problem": None}
    try:
        found = os.lstat(REPORT)
    except OSError:
        answer["problem"] = "absent"
        return answer
    if not stat.S_ISREG(found.st_mode):  # a link is never followed out of the workspace
        answer["problem"] = "not_a_file"
        return answer
    answer["bytes"] = found.st_size
    if found.st_size > MAX_BYTES:
        answer["problem"] = "too_large"
        return answer
    try:
        with open(REPORT, "rb") as report:
            text = report.read(MAX_BYTES + 1).decode("utf-8")
    except (OSError, UnicodeDecodeError):
        answer["problem"] = "not_text"
        return answer
    held = {line.rstrip() for line in text.splitlines()}
    answer["missing"] = [line for line in lines if line.rstrip() not in held]
    answer["ok"] = not answer["missing"]
    return answer


def main(arguments):
    if any(not a.strip() or "\n" in a or "\r" in a for a in arguments):
        print(json.dumps({"report": REPORT, "ok": False, "problem": "arguments"}))
        return 2
    answer = check(arguments)
    print(json.dumps(answer))
    return 0 if answer["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

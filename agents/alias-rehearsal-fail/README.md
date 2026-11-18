# alias-rehearsal-fail

Rehearsal agent for moving the model alias `fast` from one model release to another. It is
built to fail after the rehearsed move and must not be "fixed": its failure is the result the
rehearsal looks for.

Its one tool, `answer(word)`, writes `word: <word>` to `report.md`, asks the gateway one more
question itself and appends `model: <the name the gateway answered with>`. If that call
raises, the line is `model: unavailable (<exception class>)`, and the suite fails.

The suite expects `model: Qwen/Qwen3.5-0.8B`, the served name of the release `fast` points
at when the rehearsal starts. The second release differs from it only in that name, so the
agent passes before the move and fails after it. The pattern is anchored on both ends because
the second name may begin with the first. Its pair is `alias-rehearsal-pass`.

It uses no tool server. Edit `agent.yaml` only; `zetra-agents render` writes
`deploy/agent.yaml`.

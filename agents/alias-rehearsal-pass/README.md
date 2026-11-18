# alias-rehearsal-pass

Rehearsal agent for moving the model alias `fast` from one model release to another. It
passes before and after the move: its one tool, `answer(word)`, writes `word: <word>` to
`report.md`, and its suite expects the word `kestrel` and nothing about the model.

It uses no tool server. Edit `agent.yaml` only; `zetra-agents render` writes
`deploy/agent.yaml`. Its pair is `alias-rehearsal-fail`.

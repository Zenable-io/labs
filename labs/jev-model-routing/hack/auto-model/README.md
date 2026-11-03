<!-- Copyright (c) 2026 Zenable, Inc. -->

# auto-model (alpha hack)

A Claude Code mod that picks the model once per session. On the first prompt it
asks haiku one question, "is this task haiku-, sonnet- or opus-grade?", and
sends every later request of the main agent to that model:

- `haiku` when the task is well specified
- `sonnet` when it is straightforward but may have gotchas
- `opus` for everything else, and whenever the classifier fails or cannot decide

The choice is sticky. The prompt cache is tied to the model, so switching
mid-session makes the new model reread the whole conversation and costs more
than it saves. Subagents keep their own model.

No lab step uses this folder; it is here to read and to try.

## Try it

Needs Claude Code 2.1.287 or later.

```sh
claude --plugin-dir ~/zenable-labs/labs/jev-model-routing/hack/auto-model
```

The chosen model shows under the prompt as `auto-model: haiku`. `/automodel why`
prints the choice and its reason; `/automodel off` stops the mod touching
requests, so they go to the session model again.

`turn.step` takes a resolved model id, not an alias, so the mod maps `haiku`
and `sonnet` to ids the way Claude Code does: `ANTHROPIC_DEFAULT_HAIKU_MODEL`
and `ANTHROPIC_DEFAULT_SONNET_MODEL` when set, else the first-party ids pinned
in `hooks/register.js`. `opus` leaves the session's own model in place.

Check it without a session:

```sh
claude plugin validate ~/zenable-labs/labs/jev-model-routing/hack/auto-model
claude plugin test ~/zenable-labs/labs/jev-model-routing/hack/auto-model
```

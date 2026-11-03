// Copyright (c) 2026 Zenable, Inc.

// The prompt cache is keyed by model: switching mid-session makes the new
// model reread the whole conversation, so the choice is made once, on the
// first prompt, and kept until /automodel off.

const CLASSIFIER_SYSTEM = `You pick which Claude model should handle a coding task. Reply with exactly one word and nothing else:
haiku - the task is well specified: it says exactly what to change, where, and how; no judgment calls.
sonnet - the task is straightforward but may have gotchas: a clear goal, routine work, with details or edge cases to get right.
opus - anything else: unclear, open-ended, large, needs design or research, or you cannot decide.`;

// turn.step takes a resolved model id, not an alias, so the mod resolves the
// two cheaper tiers as the engine does: the ANTHROPIC_DEFAULT_*_MODEL override
// first, else the first-party id. opus means "leave the session's model alone".
// shortcut: the ids are Claude Code 2.1.302's; set the env override when they age.
const FIRST_PARTY = { haiku: "claude-haiku-5-5", sonnet: "claude-sonnet-5-5" };

let choice = null; // { tier, model, reason } once the first prompt is classified
let isOn = true;

async function resolveModel($, tier) {
  if (tier === "haiku")
    return (await $.env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL")) || FIRST_PARTY.haiku;
  if (tier === "sonnet")
    return (await $.env.get("ANTHROPIC_DEFAULT_SONNET_MODEL")) || FIRST_PARTY.sonnet;
  return null;
}

async function classify($, text) {
  let reply;
  try {
    reply = await $.model.complete({
      model: "haiku",
      system: CLASSIFIER_SYSTEM,
      prompt: text.slice(0, 4000),
      maxTokens: 10,
      timeoutMs: 8000,
    });
  } catch (error) {
    return { tier: "opus", reason: `classifier call refused: ${error.message}` };
  }
  if (!reply.isAnswered)
    return { tier: "opus", reason: `classifier gave no answer (${reply.reason})` };
  const word = reply.text.trim().toLowerCase().split(/\W+/)[0];
  if (!(word in FIRST_PARTY) && word !== "opus") {
    return {
      tier: "opus",
      reason: `classifier said "${reply.text.trim()}", which is no tier`,
    };
  }
  return { tier: word, reason: `classifier read the first prompt as ${word}-grade` };
}

export function register(on) {
  on("session.start", async ($, e, next) => {
    await $.command.register({
      name: "automodel",
      description: "Show why this session got its model, or stop switching",
      argumentHint: "why|off",
    });
    return next(e);
  });

  on("command.run", { command: "automodel" }, ($, e) => {
    if (e.args.trim() === "off") {
      isOn = false;
      $.ui.status(undefined);
      return { text: "auto-model off: requests go to the session model again." };
    }
    if (!choice)
      return { text: "auto-model: no choice yet; the first prompt decides." };
    return {
      text: `auto-model: ${choice.tier} -> ${choice.model ?? "the session model"} (${choice.reason})`,
    };
  });

  on("prompt.submit", async ($, e, next) => {
    if (!isOn || choice || e.command || e.isMeta) return next(e);
    const picked = await classify($, e.text);
    choice = { ...picked, model: await resolveModel($, picked.tier) };
    $.ui.status(choice.tier);
    $.ui.log(`auto-model: ${choice.tier} (${choice.reason})`);
    return next(e);
  });

  on("turn.step", async function* ($, e, next) {
    if (!isOn || !choice?.model || e.agentId !== undefined) return yield* next(e);
    const result = yield* next({ ...e, model: choice.model });
    if (result.usage && !choice.answeredBy) {
      choice.answeredBy = result.usage.model;
      $.ui.log(`auto-model: ${result.usage.model} answered`);
    }
    return result;
  });
}

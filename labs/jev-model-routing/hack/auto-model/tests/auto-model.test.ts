// Copyright (c) 2026 Zenable, Inc.
import { expect, test } from "claude-code/testing";

const usage = {
  input_tokens: 1,
  output_tokens: 1,
  cache_read_input_tokens: 0,
  cache_creation_input_tokens: 0,
};

function stubs(
  on,
  classifierReply: string,
  sent: string[],
  env: Record<string, string> = {},
) {
  const classified: string[] = [];
  on("model.complete", ($, e) => {
    classified.push(e.prompt);
    return { value: { isAnswered: true, text: classifierReply, usage } };
  });
  on("env.get", ($, e) => ({ value: env[e.name] }));
  on("prompt.submit", ($, e) => ({ text: e.text }));
  on("ui.status", () => ({ value: undefined }));
  on("ui.log", () => ({ value: undefined }));
  on("turn.step", async function* ($, e) {
    sent.push(e.model);
    return {
      turnId: "t",
      index: e.index,
      answer: "",
      toolUses: [],
      stopReason: "end_turn",
      usage: { ...usage, model: e.model },
    };
  });
  return classified;
}

async function step($, e) {
  const stream = $.turn.step({ turnId: "t", messageCount: 1, ...e });
  let s = await stream.next();
  while (s.done !== true) s = await stream.next();
  return s.value;
}

test("the first prompt picks the tier once; main steps follow it, subagent steps do not", async ($, on) => {
  const sent: string[] = [];
  const classified = stubs(on, "Haiku\n", sent, {
    ANTHROPIC_DEFAULT_HAIKU_MODEL: "openrouter/haiku",
  });

  await $.prompt.submit({ text: "Rename foo to bar in x.py" });
  await step($, { index: 0, model: "claude-session" });
  await step($, { index: 1, model: "claude-session", agentId: "sub-1" });
  await $.prompt.submit({ text: "Design a billing system" });
  await step($, { index: 0, model: "claude-session" });

  expect(classified).toEqual(["Rename foo to bar in x.py"]);
  expect(sent).toEqual(["openrouter/haiku", "claude-session", "openrouter/haiku"]);
  const why = await $.command.run({ command: "automodel", args: "why" });
  expect(why.text).toMatch(/^auto-model: haiku -> openrouter\/haiku \(classifier read/);

  await $.command.run({ command: "automodel", args: "off" });
  await step($, { index: 0, model: "claude-session" });
  expect(sent[sent.length - 1]).toBe("claude-session");
});

test("without the env override the first-party id is used", async ($, on) => {
  const sent: string[] = [];
  stubs(on, "sonnet", sent);

  await $.prompt.submit({ text: "Parse ISO dates from this CSV" });
  await step($, { index: 0, model: "claude-session" });

  expect(sent).toEqual(["claude-sonnet-5-5"]);
});

test("a reply that is no tier leaves the session model alone", async ($, on) => {
  const sent: string[] = [];
  stubs(on, "I would say sonnet or opus", sent);

  await $.prompt.submit({ text: "Make it better" });
  await step($, { index: 0, model: "claude-session" });

  expect(sent).toEqual(["claude-session"]);
  const why = await $.command.run({ command: "automodel", args: "" });
  expect(why.text).toBe(
    'auto-model: opus -> the session model (classifier said "I would say sonnet or opus", which is no tier)',
  );
});

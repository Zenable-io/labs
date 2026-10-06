"""Copyright (c) 2026 Zenable, Inc. Two cache keys over one chat-completions request.

`exact` is a hash of the normalised newest message. Two requests share it only
when a learner sent the same text twice, so it is safe by construction and rare
in natural traffic.

`bucket` is a coarsening of the request into features that plausibly track the
routing axis: what the message asks for, how big it is, whether it carries code,
how many tools are on offer, and how deep the conversation is. Two requests
share it when they look alike, which is common -- and whether Jev then *agrees*
within a bucket is a measurement, not an assumption. Nothing here decides a
route; these only decide which previously decided route may be reused.
"""

import hashlib
import re
import unicodedata

from pydantic import BaseModel, ConfigDict

# Leading verbs, grouped by the work the verb names. The grouping is the claim
# the bucket key makes; the agreement measurement is what tests it.
_INTENT_LEXICON: dict[str, tuple[str, ...]] = {
    "edit": (
        "rename",
        "refactor",
        "rewrite",
        "reformat",
        "format",
        "inline",
        "extract",
        "move",
        "delete",
        "remove",
        "replace",
        "update",
        "bump",
        "sort",
        "indent",
    ),
    "convert": (
        "convert",
        "translate",
        "port",
        "migrate",
        "serialize",
        "serialise",
        "parse",
        "transform",
        "encode",
        "decode",
    ),
    "read": (
        "what",
        "which",
        "who",
        "when",
        "where",
        "list",
        "show",
        "print",
        "find",
        "locate",
        "count",
        "read",
        "summarize",
        "summarise",
        "describe",
    ),
    "write": (
        "write",
        "add",
        "implement",
        "create",
        "generate",
        "build",
        "make",
        "draft",
        "produce",
    ),
    "reason": (
        "why",
        "how",
        "should",
        "design",
        "compare",
        "choose",
        "decide",
        "evaluate",
        "plan",
        "explain",
        "diagnose",
        "debug",
        "investigate",
        "review",
        "assess",
        "recommend",
        "propose",
        "troubleshoot",
    ),
    "fix": ("fix", "repair", "resolve", "correct", "patch", "handle", "prevent"),
}

_VERB_TO_INTENT: dict[str, str] = {
    verb: intent for intent, verbs in _INTENT_LEXICON.items() for verb in verbs
}

_WORD = re.compile(r"[a-z]+")
_WHITESPACE = re.compile(r"\s+")
_FENCE = re.compile(r"```|\bdef \b|\bclass \b|\bfunction \b|[{};]\s*$", re.MULTILINE)
# Digits, quoted strings and hex blobs are the parts of a prompt most likely to
# differ between two requests that ask for the same work.
_VOLATILE = re.compile(r"\b(?:0x)?[0-9a-f]{8,}\b|\b\d+\b")


class RequestFeatures(BaseModel):
    """Everything the two cache keys are derived from."""

    model_config = ConfigDict(frozen=True, strict=True)

    newest_message: str
    prior_turns: int
    tool_names: tuple[str, ...]
    intent: str
    length_bucket: str
    has_code: bool
    tools_bucket: str
    depth_bucket: str

    @property
    def bucket_key(self) -> str:
        return "|".join(
            (
                self.intent,
                self.length_bucket,
                "code" if self.has_code else "prose",
                self.tools_bucket,
                self.depth_bucket,
            )
        )

    @property
    def exact_key(self) -> str:
        """Hashes everything that reaches Jev's state, not only the message.

        `prior_turns` and `tools_offered` are in the state, so a key that
        ignored them would serve one request an answer computed from a
        different state and call that an exact hit.
        """
        material = "\x1f".join(
            (_normalise(self.newest_message), str(self.prior_turns), *self.tool_names)
        )
        return hashlib.sha256(material.encode()).hexdigest()[:24]


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).strip().lower()
    return _WHITESPACE.sub(" ", _VOLATILE.sub("#", folded))


def _length_bucket(text: str) -> str:
    size = len(text)
    if size < 80:
        return "xs"
    if size < 320:
        return "s"
    if size < 1200:
        return "m"
    if size < 4000:
        return "l"
    return "xl"


def _intent(text: str) -> str:
    """The intent named by the first lexicon word in the first sentence.

    Not the first word: developers open with "please", "can you", "in
    `src/app.py`," far more often than with a bare imperative.
    """
    head = _normalise(text)[:240]
    for word in _WORD.findall(head):
        intent = _VERB_TO_INTENT.get(word)
        if intent is not None:
            return intent
    return "other"


def _bucket(count: int, small: int, large: int, names: tuple[str, str, str]) -> str:
    if count <= small:
        return names[0]
    if count <= large:
        return names[1]
    return names[2]


def extract(body: dict[str, object]) -> RequestFeatures | None:
    """Features of an OpenAI chat-completions body, or None if it has no user turn."""
    raw_messages = body.get("messages")
    if not isinstance(raw_messages, list):
        return None

    user_indexes = [
        index
        for index, message in enumerate(raw_messages)
        if isinstance(message, dict) and message.get("role") == "user"
    ]
    if not user_indexes:
        return None

    newest = raw_messages[user_indexes[-1]]
    content = newest.get("content") if isinstance(newest, dict) else None
    if isinstance(content, list):
        # Multimodal content is a list of parts; only the text parts are routable.
        content = " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    if not isinstance(content, str) or not content.strip():
        return None

    raw_tools = body.get("tools")
    tool_names: tuple[str, ...] = ()
    if isinstance(raw_tools, list):
        tool_names = tuple(
            str(tool.get("function", {}).get("name", ""))
            for tool in raw_tools
            if isinstance(tool, dict)
        )

    prior_turns = user_indexes[-1]
    return RequestFeatures(
        newest_message=content,
        prior_turns=prior_turns,
        tool_names=tool_names,
        intent=_intent(content),
        length_bucket=_length_bucket(content),
        has_code=bool(_FENCE.search(content)),
        tools_bucket=_bucket(len(tool_names), 0, 4, ("none", "few", "many")),
        depth_bucket=_bucket(prior_turns, 0, 4, ("first", "short", "long")),
    )


def build_state(features: RequestFeatures, max_chars: int) -> dict[str, object]:
    """The `state` of a `/v1/systemone` request.

    Small on purpose: Jev's accuracy falls as irrelevant detail grows, and the
    routing judgment is about the newest message. Prior turns are a count, not a
    transcript, so a long conversation costs the same as a short one.
    """
    message = features.newest_message
    if len(message) > max_chars:
        # Keep both ends: the ask is usually at the top and the constraint at
        # the bottom, and a middle-out trim keeps the token cost flat.
        head = max_chars * 2 // 3
        tail = max_chars - head
        message = f"{message[:head]}\n...\n{message[-tail:]}"
    return {
        "request": {
            "newest_message": message,
            "prior_turns": features.prior_turns,
            "tools_offered": list(features.tool_names),
        }
    }

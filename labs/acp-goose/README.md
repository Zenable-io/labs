<!-- Generated from src/lib/labs/content/labs/acp-agent-client.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# ACP: The Protocol Between Your Editor and Your Agent

Speak the Agent Client Protocol to a real agent by hand, then watch the agent reach back for your filesystem and your shell, and put a policy on the wire that refuses it.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=acp-agent-client&utm_source=github&utm_medium=labs_repo&utm_campaign=acp-agent-client_readme)** — fully hosted sandbox environment, progress tracking, and a full-featured lab workspace.

**Duration** 70 minutes · **Difficulty** Intermediate

**Topics** `ACP` · `Agent Client Protocol` · `goose` · `JSON-RPC` · `Editor Integration` · `Least Privilege` · `Open Source` · `Python`

**Prerequisites**

- Python 3.11+ and comfort reading a dict
- A terminal (no Docker, no accounts, no API key for most of this lab)
- Curiosity about what your editor's AI agent is allowed to do

---

_This README is only the hands-on lab. The concept walk-through (What we're digging into · Terminology · The traffic reverses · Conclusion) lives on the [Learning Hub](https://www.zenable.app/learn?lab=acp-agent-client&utm_source=github&utm_medium=labs_repo&utm_campaign=acp-agent-client_readme)._

## Getting started

_~6 min · Hands-on_

We'll talk to [goose](https://github.com/aaif-goose/goose), an open-source agent governed by the [Agentic AI Foundation](https://aaif.io/projects/goose/), which speaks ACP natively. Install it pinned, so your output matches ours:

```bash
if ! command -v bzip2 >/dev/null 2>&1; then
  sudo apt-get update -qq && sudo apt-get install -y -qq bzip2
fi
curl -fsSL https://github.com/aaif-goose/goose/releases/download/stable/download_cli.sh | CONFIGURE=false GOOSE_VERSION=v1.46.0 bash
export PATH="$HOME/.local/bin:$PATH"
goose --version
```

```console
goose 1.46.0
```

> [!TIP]
> **Pro tip: run that version check every time.** The installer extracts with `tar -xjf`, which needs `bzip2`, a dependency it never checks for, and when extraction fails it still exits 0 with no binary on disk. We hit exactly that while building this lab. `CONFIGURE=false` matters too: without it the installer waits forever on an interactive provider setup. And `~/.local/bin` usually isn't on `PATH` in a fresh shell, which is why the blocks below keep re-exporting it.

Now clone the lab rig:

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
  || git -C ~/zenable-labs pull --ff-only
cd ~/zenable-labs/labs/acp-goose
ls
```

```console
acp_handshake.py
acp_policy_proxy.py
demanding_agent.py
evidence
permissive_client.py
README.md
```

Four Python files, standard library only, plus `evidence/` holding captured output from a known-good run so you can `diff` your results against ours.

## Speak the handshake yourself

_~10 min · Hands-on_

Nothing teaches a protocol like writing a client for it. `goose acp` runs goose as an ACP agent on stdio, and `acp_handshake.py` is a JSON-RPC peer in about a hundred lines. The part worth reading closely is what our client volunteers about itself:

```python
reply = conn.request(
    "initialize",
    {
        "protocolVersion": PROTOCOL_VERSION,
        # Claiming a capability is a promise the agent may call back on.
        "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": True}},
    },
)
```

Read the rest before running it. `AcpConnection.request` writes one JSON line and reads one back, and `_read` does the read on a thread it can abandon, because `readline()` has no timeout and a silent agent would otherwise hang us with nothing on screen.

Run it:

```bash
cd ~/zenable-labs/labs/acp-goose && export PATH="$HOME/.local/bin:$PATH" && python3 acp_handshake.py
```

```console
agent                goose 1.46.0
protocolVersion      1
loadSession          True
prompt content       embeddedContext, image
mcp transports       http
authMethods          1
  - goose-provider: Configure Provider
      Run `goose configure` to set up your AI provider and API key
```

Success! We just negotiated capabilities with a real agent, by hand.

Notice what we never needed: an API key, a local model, or a network connection. `initialize` is answered before goose resolves a provider, so we can inspect any ACP agent this way for free. The highlighted lines are goose saying auth comes later, through ACP's own `authenticate` step. And `mcp transports http` is goose declaring which MCP transports it accepts when we hand it servers.

Question: our client claimed `{"fs": {"readTextFile": True, "writeTextFile": True}}`. What did we just agree to?

<details>
<summary>Answer</summary>

We granted authority. That one object tells the agent it may call back into us to read and write files, and the rest of this lab is what happens when it does. A client that claims a capability it doesn't police has volunteered its filesystem, much like running a container as root because it was easier.

</details>

So where does the free part end? Let's find the line by opening a session:

```bash
cd ~/zenable-labs/labs/acp-goose && export PATH="$HOME/.local/bin:$PATH" && python3 - <<'PYEOF'
import json, subprocess
p = subprocess.Popen(["goose", "acp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
for i, (m, params) in enumerate([
    ("initialize", {"protocolVersion": 1, "clientCapabilities": {"fs": {}}}),
    ("session/new", {"cwd": "/tmp", "mcpServers": []}),
], start=1):
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": m, "params": params}) + "\n")
    p.stdin.flush()
    reply = json.loads(p.stdout.readline())
    print(f"{m:16} -> {'error: ' + reply['error']['data'] if 'error' in reply else 'ok'}")
p.terminate()
raise SystemExit(1)
PYEOF
```

With no provider configured, `initialize` reports ok and `session/new` comes back as a JSON-RPC error naming the missing `GOOSE_PROVIDER` configuration. The handshake is protocol plumbing; a session is where the model starts. Knowing which of the two failed is half of debugging any ACP integration.

<details>
<summary>Seeing a sqlite panic instead?</summary>

On a machine with an older goose install you may see `panicked at sqlx-sqlite … index out of bounds` rather than a clean error. That's stale local session state, and you can confirm by running against a clean profile: `HOME=$(mktemp -d) goose acp`. We spent a while blaming our own client for this one.

</details>

## An agent that only asks

_~9 min · Hands-on_

We could run the callbacks with goose and a model, but then the interesting call only happens if the model decides to make it. So we take the model out. `demanding_agent.py` answers `session/new` and immediately asks for the two things worth governing:

```python
def probe(peer: Peer) -> None:
    write = peer.call("fs/write_text_file",
                      {"path": TARGET, "content": "the agent reached the filesystem\n"})
    print(f"fs/write_text_file   {verdict(write)}", file=sys.stderr, flush=True)
    shell = peer.call("terminal/create", {"command": "id", "args": []})
    print(f"terminal/create      {verdict(shell)}", file=sys.stderr, flush=True)
```

Those calls always happen, so whether they succeed is a property of the client and nothing else. `permissive_client.py` plays the editor that grants everything, and its writes and commands are real:

```python
def _handle(self, req_id: object, method: str, params: dict) -> None:
    if method == "fs/write_text_file":
        path = pathlib.Path(params["path"])
        path.write_text(params.get("content", ""), encoding="utf-8")
        ...
    elif method == "terminal/create":
        argv = [params["command"], *params.get("args", [])]
        done = subprocess.run(argv, capture_output=True, text=True, check=False)
```

Run them together:

```bash
cd ~/zenable-labs/labs/acp-goose && rm -f /tmp/acp-demanding-agent.txt && python3 permissive_client.py -- python3 demanding_agent.py; echo "--- did the file appear? ---"; cat /tmp/acp-demanding-agent.txt
```

```console
[client] wrote /tmp/acp-demanding-agent.txt
fs/write_text_file   ALLOWED
[client] ran id -> uid=0(root) gid=0(root) groups=0(root)
terminal/create      ALLOWED
--- did the file appear? ---
the agent reached the filesystem
```

An agent with no model and no credential wrote to the filesystem and ran a command. It didn't exploit anything; it asked, and the client said yes, because we said it could during `initialize`.

> [!TIP]
> **Pro tip: read the `id` output, then the ALLOWED.** We captured this run inside the lab VM, which is why it reports root; on your laptop it reports you, with your SSH keys, cloud credentials, and git push rights. The client executes on the agent's behalf, so the client's privilege becomes the agent's privilege. Nothing sandboxes this picture unless you add one.

Question: which process actually wrote that file and ran `id`, the agent or the client?

<details>
<summary>Answer</summary>

The client. The agent only ever sent JSON lines; `permissive_client.py` did the `write_text` and the `subprocess.run`. That's the whole ACP trust model in one run: agents change the machine by asking, and the client decides what asking achieves.

</details>

## Put a policy on the wire

_~10 min · Hands-on_

Everything on this wire is ordinary line-delimited JSON-RPC, so anything sitting between the two processes can answer on the client's behalf. `acp_policy_proxy.py` forwards every frame, records it, and refuses the methods we name. The decision is one branch, on the agent-to-client leg:

```python
if is_request and method in denied:
    refusal = {
        "jsonrpc": "2.0",
        "id": frame["id"],
        "error": {
            "code": REFUSED,
            "message": f"{method} refused by client policy",
        },
    }
    agent_stdin.write(json.dumps(refusal) + "\n")
    agent_stdin.flush()
    auditor.record("agent->client", frame, "DENIED")
```

First, let's confirm it's transparent. Run the handshake through it and compare against the eight lines we got earlier; they should be identical:

```bash
cd ~/zenable-labs/labs/acp-goose && export PATH="$HOME/.local/bin:$PATH" && python3 acp_handshake.py -- python3 acp_policy_proxy.py --audit /tmp/acp-audit.jsonl -- goose acp 2>/dev/null
```

Now the same experiment as the previous section, with one difference: the proxy in the middle, denying.

```bash
cd ~/zenable-labs/labs/acp-goose && rm -f /tmp/acp-demanding-agent.txt /tmp/acp-deny.jsonl && python3 permissive_client.py -- python3 acp_policy_proxy.py --deny fs/write_text_file --deny terminal/create --audit /tmp/acp-deny.jsonl -- python3 demanding_agent.py 2>&1 | grep -v '^\[acp\]'; echo "--- did the file appear? ---"; cat /tmp/acp-demanding-agent.txt 2>/dev/null || echo "(absent -- never written)"
```

```console
fs/write_text_file   REFUSED -- fs/write_text_file refused by client policy
terminal/create      REFUSED -- terminal/create refused by client policy
--- did the file appear? ---
(absent -- never written)
```

Same agent, same client, same requests, opposite outcome, and the file never existed. Success!

The audit log is the other half of the value:

```bash
cat /tmp/acp-deny.jsonl
```

```console
{"direction": "client->agent", "method": "initialize", "id": 1, "verdict": "forwarded"}
{"direction": "client->agent", "method": "session/new", "id": 2, "verdict": "forwarded"}
{"direction": "agent->client", "method": null, "id": 1, "verdict": "forwarded"}
{"direction": "agent->client", "method": null, "id": 2, "verdict": "forwarded"}
{"direction": "agent->client", "method": "fs/write_text_file", "id": 1001, "verdict": "DENIED"}
{"direction": "agent->client", "method": "terminal/create", "id": 1002, "verdict": "DENIED"}
```

Every attempt is recorded whether it succeeded or was refused. This log is how you find out an agent has been trying to write outside its lane for a week.

Question: two entries carry `"method": null`. What are those frames? 🤔

<details>
<summary>Answer</summary>

Responses. A JSON-RPC response carries an `id` and a result, with no `method`, and these two travel agent → client because they answer the `initialize` and `session/new` requests the client sent (see the matching ids 1 and 2). The proxy logs both directions, so answers show up alongside requests.

</details>

> [!TIP]
> **Pro tip: refuse, don't drop.** The proxy answers with a well-formed JSON-RPC error instead of swallowing the frame. An agent waiting on a response that never comes hangs, a hung agent looks like a broken editor, and a broken-feeling control is a control someone turns off. A refusal is a state the agent already handles.

Before we add a model, let's be clear about what we built: a teaching rig. It matches on method names only, so `--deny fs/write_text_file` is all-or-nothing where real rules say "nothing outside the workspace". Nothing authenticates the agent, and the audit log is a plain file the audited party could edit. A production deployment layers per-path and per-command rules, an attributable identity, and a log the agent can't reach on top of exactly the shape you just built.

## Drive the real thing

_~9 min · Hands-on_

Everything so far ran with no model. To watch a real agent take a real turn we need inference, and there are two ways to get it.

**Adventure A: bring an API key.** The fastest path if you already have one:

```bash
export PATH="$HOME/.local/bin:$PATH"
export ANTHROPIC_API_KEY="sk-ant-..."     # or OPENAI_API_KEY, etc.
goose configure                            # choose the matching provider
```

**Adventure B: run a local model with Ollama.** Free, no accounts, and it's the path our CI runs. Install it and wait for its API to answer:

```bash
curl -fsSL https://ollama.com/install.sh | sh
pgrep -x ollama >/dev/null || (nohup ollama serve >/tmp/ollama.log 2>&1 &)
timeout 90 bash -c 'until curl -fsS http://localhost:11434/api/version >/dev/null 2>&1; do sleep 2; done' \
  || { echo "ollama never came up"; cat /tmp/ollama.log; exit 1; }
ollama --version
```

Pull the model. `qwen3:1.7b` is a 1.4 GB download, and it's the smallest model we found that reliably emits well-formed tool calls:

```bash
ollama pull qwen3:1.7b
ollama list
```

Before wiring it to goose, confirm the model can do the one thing this section depends on, which is asking for a tool:

```bash
curl -sS http://localhost:11434/api/chat -d '{
  "model": "qwen3:1.7b",
  "stream": false,
  "think": false,
  "messages": [{"role": "user", "content": "Create a file called notes.txt containing the word hello. Use the tool."}],
  "tools": [{"type": "function", "function": {
    "name": "write_file",
    "description": "Write text to a file",
    "parameters": {"type": "object",
      "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
      "required": ["path", "content"]}}}]
}' | python3 -c '
import json, sys
calls = json.load(sys.stdin)["message"].get("tool_calls")
if not calls:
    sys.exit("no tool call: this model answered in prose, so goose will never reach your proxy")
print(json.dumps(calls, indent=2))
'
```

You should get a `write_file` call carrying `notes.txt` and `hello`. That JSON is the model's half of everything that follows: goose turns a call like it into an ACP `fs/write_text_file` request, and your proxy decides what happens next.

> [!WARNING]
> `qwen3:0.6b` still fires the tool but garbles the schema, and an agent wired to a model like that fails in ways that look like protocol bugs. Tool-calling fidelity is a model property; check it before you blame the wire.

goose reads its provider from the environment, and a new shell knows none of this:

```bash
export GOOSE_PROVIDER=ollama
export OLLAMA_HOST=http://localhost:11434
export GOOSE_MODEL=qwen3:1.7b
export OLLAMA_CONTEXT_LENGTH=32768
```

> [!TIP]
> `OLLAMA_CONTEXT_LENGTH` matters. Ollama defaults to a 4096-token context, a tool-calling agent blows past that on tool definitions alone, and goose then appears to ignore its own instructions because the context was silently truncated.

Either way, we end up in the same place: our proxy in front of real goose, denying writes while the model works.

```bash
cd ~/zenable-labs/labs/acp-goose && export PATH="$HOME/.local/bin:$PATH"
python3 permissive_client.py -- \
  python3 acp_policy_proxy.py --deny fs/write_text_file --audit /tmp/acp-real.jsonl -- \
  goose acp
```

Watch `/tmp/acp-real.jsonl` as the session runs: the `session/update` notifications carry the agent's plan, and the `fs/*` requests are a model deciding to change your files. Same wire, same proxy, same audit log; the new part is that something on the far end is choosing.

> [!TIP]
> **Pro tip: this is where `mcpServers` earns its place.** Every MCP server we pass to `session/new` becomes a tool the agent can call, and we chose that list. ACP decides *which* MCP servers a session gets, and MCP's authorization layer decides what the agent may do with each one; our [MCP Enterprise Authorization 101](https://www.zenable.app/learn?lab=mcp-authorization-101&utm_source=github&utm_medium=labs_repo&utm_campaign=acp-agent-client_readme) workshop covers that half.

## Cleanup

_~5 min · Hands-on_

If you took Adventure B and want the model gone:

```bash
command -v ollama >/dev/null 2>&1 && ollama rm qwen3:1.7b || true
```

Everything else we made lives in three places: temp files, the goose binary, and the cloned rig. Step out of the rig directory first (removing the directory you're standing in leaves your shell in a deleted location), then remove them all:

```bash
cd ~
rm -f /tmp/acp-demanding-agent.txt /tmp/acp-audit.jsonl /tmp/acp-deny.jsonl /tmp/acp-real.jsonl
rm -f "$HOME/.local/bin/goose"
rm -rf ~/zenable-labs
```

Thanks for exploring the wire with us!

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=acp-agent-client&utm_source=github&utm_medium=labs_repo&utm_campaign=acp-agent-client_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=acp-agent-client_readme), or open an issue on this repo if something is broken._

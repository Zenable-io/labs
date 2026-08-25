<!-- Generated from src/lib/labs/content/labs/acp-agent-client.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# ACP: The Protocol Between Your Editor and Your Agent

Speak the Agent Client Protocol to a real agent by hand, then watch the agent reach back for your filesystem and your shell — and put a policy on the wire that refuses it.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=acp-agent-client&utm_source=github&utm_medium=labs_repo&utm_campaign=acp-agent-client_readme)** — fully hosted sandbox environment, progress tracking, and a full-featured lab workspace.

**Duration** 115 minutes · **Difficulty** Intermediate

**Topics** `ACP` · `Agent Client Protocol` · `goose` · `JSON-RPC` · `Editor Integration` · `Least Privilege` · `Open Source` · `Python`

**Prerequisites**

- Python 3.11+ and comfort reading a dict
- A terminal — no Docker, no accounts, no API key for most of this lab
- Curiosity about what your editor's AI agent is allowed to do

---

_This README is only the hands-on lab. The concept walk-through (First: which ACP is this? · What the protocol is for · The direction nobody expects · Where this rig stops) lives on the [Learning Hub](https://www.zenable.app/learn?lab=acp-agent-client&utm_source=github&utm_medium=labs_repo&utm_campaign=acp-agent-client_readme)._

## Speak the handshake yourself

_~18 min · Hands-on_

Nothing teaches a protocol like writing a client for it. We are going to talk to a real agent — [goose](https://github.com/block/goose), Block's open-source agent, which implements ACP natively — using nothing but the standard library.

Install goose. We pin the version so your output matches the lab. The Linux release ships as a `.tar.bz2`, so make sure `bzip2` is present before you start — read the Pro Tip below before you skip that line.

```bash
if ! command -v bzip2 >/dev/null 2>&1; then
  sudo apt-get update -qq && sudo apt-get install -y -qq bzip2
fi
curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | CONFIGURE=false GOOSE_VERSION=v1.46.0 bash
export PATH="$HOME/.local/bin:$PATH"
goose --version
```

> [!TIP]
> **Pro tip — that `goose --version` is not decoration.** The installer checks that `tar` exists, then extracts with `tar -xjf`, which shells out to `bzip2` — a dependency it never checks for. On a minimal Linux image you get this:

```console
tar (child): bzip2: Cannot exec: No such file or directory
Error: Failed to extract goose-...-linux-gnu.tar.bz2
```

and then **the installer exits 0 anyway**. A script that installs and moves on would sail past this with no binary on disk and fail later somewhere confusing. We hit exactly this building the lab, on a machine where the local dry run had passed — because that machine happened to have `bzip2` already. Verify the thing you just installed actually runs; a zero exit code is not evidence.

> [!TIP]
> **Pro tip — `CONFIGURE=false` is doing real work.** Without it the installer drops into an interactive provider setup and waits for input forever, which is exactly the kind of thing that wedges a CI job or a workshop. The installer also honours `GOOSE_BIN_DIR`; the default is `~/.local/bin`, which is **not** on `PATH` in a fresh shell on most Linux images. Every block below re-exports it for that reason — a new terminal means a new `export`.

`goose acp` runs goose as an ACP agent server on stdio. Clone the rig and talk to it:

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
  || git -C ~/zenable-labs pull --ff-only
cd ~/zenable-labs/labs/acp-goose
ls
```

Four files, standard library only. `acp_handshake.py` is a JSON-RPC peer in about a hundred lines; the part that carries the lesson is what the client volunteers about itself:

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

Read the rest before running it. `AcpConnection.request` writes one JSON line and reads one back; `_read` does that read on a thread it can abandon, because `readline()` has no timeout and an agent that never answers would otherwise hang the lab with no output at all.

Run it:

```bash
cd ~/zenable-labs/labs/acp-goose && export PATH="$HOME/.local/bin:$PATH" && python3 acp_handshake.py
```

You should see something very close to this:

```console
agent                goose 1.46.0
protocolVersion      1
loadSession          True
prompt content       embeddedContext, image
mcp transports       http
authMethods          1
  - goose-provider: Configure Provider
```

Stop and look at what just happened, because three things in that output are the whole lesson.

**No model was involved.** You have no API key configured and no local model downloaded, and the handshake still completed. `initialize` is answered before the agent resolves a provider. Capability negotiation is a protocol-layer conversation, and you can inspect any ACP agent this way for free.

**The agent advertised `authMethods`.** ACP has its own authentication step — `authenticate` — that the client calls when the agent says it needs one. Here goose is telling you it has no provider configured yet. This is a real seam: the agent can require the client to establish identity before doing work.

**The agent advertised `mcpCapabilities`.** goose is saying which MCP transports it can accept when the client hands it MCP servers. The editor is the one that decides what tools exist.

> [!TIP]
> **Pro tip — capabilities are promises, not preferences.** Look at what our client sent: `clientCapabilities: {fs: {readTextFile: true, writeTextFile: true}}`. We just told the agent it may call back and ask us to read and write files. That is not a request for a feature — it is a grant of authority, and the next section is what the agent does with it. Claiming a capability you do not intend to police is the ACP equivalent of running a container as root because it was easier.

### Where the model actually becomes necessary

Try opening a session and the boundary shows up precisely:

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

```console
initialize       -> ok
session/new      -> error: Failed to resolve provider: Configuration value not found: GOOSE_PROVIDER
```

`initialize` needs no model. `session/new` does. That line is where the free part of ACP ends, and it is a useful thing to know when you are debugging an integration: a failing handshake and a failing session are different problems with different causes.

> [!TIP]
> **Pro tip — if you get a sqlite panic instead.** On a machine with an older goose install you may see `panicked at sqlx-sqlite … index out of bounds` rather than a clean error. That is stale local session state, not the protocol. Run against a clean profile to confirm: `HOME=$(mktemp -d) goose acp`. We hit exactly this while building the lab, and spent a while blaming our client for it.

## Prove it: an agent that only asks

_~20 min · Hands-on_

We could demonstrate this with goose and a model, but that would make the experiment nondeterministic — the interesting callback happens only if the model decides to make it. So we remove the model from the experiment entirely.

`demanding_agent.py` does nothing except ask for the two things worth governing.

Its entire behaviour is four lines — it answers `session/new`, then immediately probes:

```python
def probe(peer: Peer) -> None:
    write = peer.call("fs/write_text_file",
                      {"path": TARGET, "content": "the agent reached the filesystem\n"})
    print(f"fs/write_text_file   {verdict(write)}", file=sys.stderr, flush=True)
    shell = peer.call("terminal/create", {"command": "id", "args": []})
    print(f"terminal/create      {verdict(shell)}", file=sys.stderr, flush=True)
```

No model decides whether those calls happen. They always happen, so whether they *succeed* is a property of the client and nothing else.

`permissive_client.py` grants everything — the way an editor behaves when nobody has thought about this yet. The writes and commands are **real**, so "allowed" means the agent actually reached the machine:

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

That is the whole policy: none. Note also `IDLE_EXIT_SECONDS` and the watchdog thread — the agent never closes the stream, so the client ends the run once the wire goes quiet.

Run them together:

Run them together.

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

An agent with no model, no credential, and no identity wrote to your filesystem and ran a command as you. It did not exploit anything. It asked, and the client said yes — because we told it during `initialize` that it could.

> [!TIP]
> **Pro tip — look at the `id` output, not the ALLOWED.** Whatever that line says is the privilege level your agent inherits. In a container it says root. On your laptop it says you, with your SSH keys, your cloud credentials, and your git push rights. ACP does not grant the agent anything it can reach directly — but the client executes on its behalf, so the client's privilege *is* the agent's privilege. There is no sandbox in this picture unless you put one there.

## Put a policy on the wire

_~20 min · Hands-on_

Here is the useful consequence of everything being ordinary JSON-RPC: anything on the wire can answer on the client's behalf. `acp_policy_proxy.py` audits every frame and refuses the calls you name.

The decision is one branch, on the agent-to-client leg:

```python
if method in denied:
    reply = {"jsonrpc": "2.0", "id": frame["id"], "error": {
        "code": -32000,
        "message": f"{method} refused by client policy",
    }}
    auditor.record("agent->client", frame, "DENIED")
```

It answers with a well-formed JSON-RPC error rather than dropping the frame, and it records every frame either way. Read `Auditor.record` and the forwarding loop before you run it.

First confirm it is transparent — the handshake through the proxy should be identical to the handshake without it.

```bash
cd ~/zenable-labs/labs/acp-goose && export PATH="$HOME/.local/bin:$PATH" && python3 acp_handshake.py -- python3 acp_policy_proxy.py --audit /tmp/acp-audit.jsonl -- goose acp 2>/dev/null
```

Now the same experiment as before, one difference: the proxy in the middle, denying.

```bash
cd ~/zenable-labs/labs/acp-goose && rm -f /tmp/acp-demanding-agent.txt /tmp/acp-deny.jsonl && python3 permissive_client.py -- python3 acp_policy_proxy.py --deny fs/write_text_file --deny terminal/create --audit /tmp/acp-deny.jsonl -- python3 demanding_agent.py 2>&1 | grep -v '^\[acp\]'; echo "--- did the file appear? ---"; cat /tmp/acp-demanding-agent.txt 2>/dev/null || echo "(absent -- never written)"
```

```console
fs/write_text_file   REFUSED -- fs/write_text_file refused by client policy
terminal/create      REFUSED -- terminal/create refused by client policy
--- did the file appear? ---
(absent -- never written)
```

Same agent. Same client. Same request. Opposite outcome — and the file the agent tried to write never existed.

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

Every attempt is recorded whether or not it succeeded. A denied action you cannot see is worth much less than a denied action you can — the log is what tells you an agent has been trying to write outside its lane for a week.

> [!TIP]
> **Pro tip — refuse, don't drop.** The proxy answers the agent with a proper JSON-RPC error rather than swallowing the frame. That matters: an agent waiting on a response it will never receive hangs, and a hung agent looks like a broken editor, which is how "security" becomes the thing everyone turns off. A well-formed refusal is a state the agent already knows how to handle. Any policy layer you build should be loud and fast, never silent.

> [!TIP]
> **Diving deeper — why this works at all.** The proxy is possible because ACP is symmetric line-delimited JSON-RPC with no transport-level authentication and no message integrity. That is a deliberate design choice for a protocol between a parent process and its own child — on a single machine, the process boundary *is* the trust boundary, and adding crypto between them would be theatre. The consequence is that a local proxy is trivial to build, which cuts both ways: it is also trivial for anything that can start your editor's agent subprocess to sit in that position. Whoever controls the agent command line controls the conversation. That is the thing to protect.

## Drive the real thing

_~12 min · Hands-on_

Everything so far worked with no model at all. To watch a real agent take a real turn you need inference, and there are two ways to get it — pick whichever fits your situation.

**Adventure A — bring an API key.** Fastest path, and it is how most people run goose day to day.

```bash
export PATH="$HOME/.local/bin:$PATH"
export ANTHROPIC_API_KEY="sk-ant-..."     # or OPENAI_API_KEY, etc.
goose configure                            # choose the matching provider
```

**Adventure B — run a local model with Ollama.** No account, nothing to sign up for, and the whole lab stays free. Slower, and the model is less capable — but this is the path CI runs, so it is the one we know works.

Install Ollama and wait for its API to answer. The Linux installer registers a systemd service; anywhere else you start the server yourself, which is what the fallback below is for:

```bash
curl -fsSL https://ollama.com/install.sh | sh
pgrep -x ollama >/dev/null || (nohup ollama serve >/tmp/ollama.log 2>&1 &)
timeout 90 bash -c 'until curl -fsS http://localhost:11434/api/version >/dev/null 2>&1; do sleep 2; done' \
  || { echo "ollama never came up"; cat /tmp/ollama.log; exit 1; }
ollama --version
```

Pull the model. `qwen3:1.7b` is a 1.4 GB download — small enough for a modest VM, and the smallest one we found that reliably emits **well-formed** tool calls:

```bash
ollama pull qwen3:1.7b
ollama list
```

Before wiring it to goose, confirm the model can do the one thing the rest of this section depends on — ask for a tool:

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

You should get a `write_file` call carrying `notes.txt` and `hello`. That JSON is the model's half of everything that follows: goose turns a call like it into an ACP `fs/write_text_file` request, and your proxy is what decides whether it lands.

> [!WARNING]
> Try `qwen3:0.6b` if you want to see the floor. It still *fires* the tool, but it garbles the schema — nesting `content` inside itself — and an agent wired to a model like that fails in ways that look like protocol bugs and are not. Tool-calling fidelity is a model property, and it is worth checking before you blame the wire.

goose reads its provider from the environment. A new shell knows none of this, so every block below re-exports it:

```bash
export GOOSE_PROVIDER=ollama
export OLLAMA_HOST=http://localhost:11434
export GOOSE_MODEL=qwen3:1.7b
export OLLAMA_CONTEXT_LENGTH=32768
```

> [!TIP]
> `OLLAMA_CONTEXT_LENGTH` is not optional padding. Ollama defaults to a 4096-token context, and a tool-calling agent blows past that on the tool definitions alone — goose then starts ignoring its own instructions in ways that read as the model being stupid rather than the context being truncated.

Either way, the payoff is the same: run your **proxy** in front of real goose, give it a task that wants to touch the filesystem, and watch the governed calls appear in your audit log as the model works.

```bash
cd ~/zenable-labs/labs/acp-goose && export PATH="$HOME/.local/bin:$PATH"
python3 permissive_client.py -- \
  python3 acp_policy_proxy.py --deny fs/write_text_file --audit /tmp/acp-real.jsonl -- \
  goose acp
```

Now the `session/update` notifications carry the agent's plan and tool calls, and the `fs/*` requests are a model deciding to change your files. Same wire, same proxy, same audit log — the only new thing is that something on the other end is thinking.

> [!TIP]
> **Pro tip — this is where `mcpServers` earns its place.** Once you have a session running, look at what you passed to `session/new`. Every MCP server listed there becomes a tool the agent can call, and you chose that list. If you have done our [MCP Enterprise Authorization lab](https://www.zenable.app/learn?lab=mcp-authorization-101&utm_source=github&utm_medium=labs_repo&utm_campaign=acp-agent-client_readme), this is where the two protocols meet: ACP decides *which* MCP servers exist for this session, and the MCP authorization layer decides what the agent may do with each one. Neither is sufficient alone.

## What to take away

_~5 min · Discussion_

Three things worth keeping:

**ACP is agent↔editor, and the acronym is contested.** If someone says ACP and means agent-to-agent, they mean the IBM protocol that merged into A2A. Different problem, different lineage.

**The interesting traffic goes the other way.** The editor calling the agent is the boring half. The agent calling back for your filesystem and your shell is where the consequences live, and every one of those is an inbound request something can refuse.

**Capability grants are the real configuration.** Your client tells the agent what it may ask for during `initialize`. Everything downstream is a consequence of that one object. If you are integrating an agent into anything that matters, that is the line to review first.

The tree you cloned is yours to keep. `evidence/` holds captured output from a known-good run, so `diff` tells you whether a change you made is why something stopped working.

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=acp-agent-client&utm_source=github&utm_medium=labs_repo&utm_campaign=acp-agent-client_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=acp-agent-client_readme), or open an issue on this repo if something is broken._

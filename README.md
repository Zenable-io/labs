# Zenable Labs

Hands-on lab environments for the [Zenable Learning Hub](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=labs_readme).

Each directory under `labs/` is a self-contained environment for one lab — the containers, scripts, and sample services a lab needs, so you can run the real thing on your own machine instead of reading about it.

## Why we publish these

We think information should be free. Companies are complex, and everyone's AI adoption journey is different. A rising tide lifts all ships, so we're committed to helping people learn this well enough to make good decisions, whether or not they ever use Zenable.

## Getting started

The Learning Hub runs each lab with per-section timing, progress tracking, and copy buttons on every command:

**[zenable.app/learn](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=labs_getting_started)**

You can also clone this repository and follow a lab from here. Every lab directory carries the whole walkthrough in its README — the same content the Hub serves, generated from it.

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs
cd ~/zenable-labs/labs/<lab>
```

## Labs

| Lab | What you'll do |
|---|---|
| [`mcp-get-started`](labs/mcp-get-started) | Write an MCP server with FastMCP, drive it with a scripted client, move it into a container on Streamable HTTP, then point goose at it without changing a line of server code. |
| [`ema-mcp`](labs/ema-mcp) | Stand up an enterprise IdP, a vendor authorization server, and a protected MCP server, then watch an AI agent get authorized with no consent screen — and try to break the security properties that make it safe. |
| [`a2a`](labs/a2a) | Build two agents that discover and call each other over the A2A protocol, with Keycloak issuing every credential — then send a rogue agent at them and watch each check reject it. |
| [`acp-goose`](labs/acp-goose) | Speak the Agent Client Protocol to a real agent by hand, then watch the agent reach back for your filesystem and your shell — and put a policy on the wire that refuses it. |

## A note on running these

These environments are built for learning, not production. They use demo credentials, self-signed trust, and deliberately weakened configurations so you can see what happens when things go wrong. Run them locally or on a throwaway VM, never somewhere that matters.

## Contributing

Please open an issue if you found something broken, unclear, or out of date

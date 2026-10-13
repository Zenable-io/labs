<!-- Copyright (c) 2026 Zenable, Inc. -->
# Refactoring for the Next Change

Public worked examples and exercises for an intermediate software-design lab. Python, Go and Java implement one expense contract. `history` reconstructs a deliberately unsafe sequence of changes; `design` is the openly discussed design example. Neither starts a server or connects to a real account.

Read the workshop guide in the Learning Hub or the public lab README. Start with `./lab build`, then `./lab run python history three-changes --check` (expected exit 1). Substitute `go` or `java` throughout. `./lab test python` tests the design example; `./lab test python history` tests your refactoring of the historical implementation. `./lab metrics python` measures complexity and prints explicitly assumed coverage scenarios.

The image contains all three toolchains. Runtime commands have no network and mount source read-only, so edit files on the host between runs. Compilation uses temporary directories. The image build needs network access; `--network=host` supports sandboxes with IPv6-only egress.

`task test` builds the image and checks all languages. With toolchains already installed, `task unit-test LANGUAGE=python` runs the same contract through the locked Python environment. Native requirements: Python 3.11+, Go 1.24+, JDK 11+, uv and Task. The Docker path supplies its own pinned toolchains and needs only Docker.

## Contract

Inputs are tab-separated: channel, authenticated tenant, authenticated actor, role, requested tenant, account, amount in cents, policy, request identifier. The CLI injects an authenticated principal as a test fixture. A deployed transport must derive that principal from verified identity; never trust tenant or role fields supplied by a client.

Each process starts with synthetic tenants `alpha` (10,000 cents) and `beta` (20,000 cents), both with account `shared`. Output is diagnostic status, both remaining balances and total audit events. The global snapshot is test observation, never a tenant-facing endpoint.

- Only an approver in the requested tenant may submit.
- Standard reimburses the request, up to 5,000 cents. Travel reimburses 80%, rounded down to integer cents, for requests up to 10,000 cents.
- A payment must be positive and cannot exceed its request or available budget.
- An accepted submission changes the budget and appends one audit event together. Rejection changes neither.
- Within a tenant, the same actor, payload and request identifier replay without another debit or policy evaluation. Changed actor or payload conflicts before policy or account lookup. Authorisation still precedes replay.

`ExpenseService` owns submission invariants and private state. `ExpensePolicy` is the Strategy interface; the policies calculate reimbursement without access to accounts or identity. Web and batch entrypoints delegate to the service.

This is a process-local model for studying design. Locks and immutable state publication make its in-process operation atomic. Durable storage, multiple processes, external payments and identity verification need separate production designs: transactional uniqueness and balance checks, and an outbox or equivalent when effects leave that transaction. Nothing here guarantees distributed exactly-once execution.

## Extend the lab

Each language lives under `languages/<id>/`; its `runtime.json` declares compilation, execution and metric source files. `scenarios.json` owns the language-neutral expected behaviour. The harness discovers runtimes, compiles them and runs the same scenarios. Add a language by implementing that protocol, adding a runtime manifest and its container toolchain, then passing the entire contract. The guide must supply the corresponding language variant.

The learner exercises change the historical implementation, extend a policy and write a short maintenance brief. There is no supplied implementation for the final extension.

CRAP uses measured cyclomatic complexity and an explicitly hypothetical coverage input here. The metric tool does not collect coverage and does not present statement or branch coverage as basis-path coverage. Compare functions and changed paths within a language; parser conventions differ across languages.

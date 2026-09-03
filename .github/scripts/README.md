# Dependency update tooling

Weekly automation that refreshes every pinned dependency in this repository —
container image tags, `uv.lock` files, and GitHub Action SHAs — behind a
supply-chain cooldown and an upstream-provenance check.

Driven by [`.github/workflows/update.yml`](../workflows/update.yml) every Tuesday
at 03:16 UTC. Run it yourself the same way CI does:

```bash
bash .github/scripts/update-pins.sh
```

It needs `uv` and a GitHub token; without `GITHUB_TOKEN` set it falls back to
`gh auth token`, and without either it runs unauthenticated into GitHub's
60-requests-per-hour limit almost immediately.

## What it guarantees

**A 7-day cooldown on every adopted version.** Nothing published in the last
week is adopted, so a compromised upstream release has time to be noticed by
someone else first ([context](https://github.com/aquasecurity/trivy/discussions/10425)).
Candidates are walked newest-first and the first one past the window is taken —
a 3-day-old release is skipped while an 8-day-old one is still picked up, rather
than the whole pin stalling. For Python dependencies the cooldown is declarative
instead: `exclude-newer = "7 days"` in each project's `[tool.uv]`, which the
resolver enforces for `uv lock --upgrade` and for a reader's `uv sync` alike.

**Provenance for every GitHub-sourced version.** The tag must exist as a ref in
the repository it claims to come from, and must resolve (through an annotated
tag, if there is one) to a commit. Git refs are repo-scoped — a fork's tags never
appear in the parent's refs — which is what the
[imposter-commit attack](https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23)
lacks, since it references a bare SHA with no ref behind it.

**Hash-pinned Actions, verified twice.** `pinact run -u` re-pins to the newest
release past its own 7-day cooldown; `pinact run --check --verify-comment`
confirms each `# vX.Y.Z` comment still names the pinned SHA; and
`verify_action_pins.py` confirms that SHA is reachable from a branch upstream,
which is the check pinact has no equivalent for. That last one also fails on any
`uses:` that is not SHA-pinned at all, so it doubles as the gate a per-PR
`zizmor unpinned-uses` rule would otherwise provide.

## Layout

| Path | Purpose |
| --- | --- |
| `update-pins.sh` | The pin list. One commented block per pin — start here. |
| `update_file.py` | Resolve a version, gate it, rewrite it into files. |
| `verify_action_pins.py` | Confirm pinned Action commits exist upstream. |
| `check_doc_drift.py` | Report docs quoting a superseded version. |
| `supply_chain/` | Cooldown, GitHub verification, Docker Hub tag discovery. |

`supply_chain/` is a trimmed vendoring of `zenable_monorepo` from
`Zenable-io/next-gen-governance`, which is private while this repository is
public. The security-relevant logic is kept behaviourally close to upstream so a
fix there ports as a readable diff. **If a third repository needs this, extract
these modules into a package all three consume rather than vendoring again.**

## Adding a pin

Append a block to `update-pins.sh`. Both regexes are required — there is no
inferred default, because every pin here is a bespoke line in a compose file or
Dockerfile and a guessed pattern is how an update silently becomes a no-op.

```bash
"${UPDATE_FILE[@]}" \
  --file "${GIT_ROOT}/labs/example/compose.yaml" \
  --source-type github-release \
  --github-owner someone --github-repo something \
  --pin-level patch \
  --no-downgrade \
  --search-pattern 'ghcr\.io/someone/something:v[0-9]+\.[0-9]+\.[0-9]+' \
  --replacement-pattern 'ghcr.io/someone/something:{version}'
```

Prefer `--source-type github-release` even when the image lives on quay.io or
ghcr.io, as both Keycloak and agentgateway do here: GitHub releases carry a real
publish date and a verifiable tag, and those registries offer neither.

Use `--source-type docker-hub` when there is no GitHub release to read, and pass
`--version-line` whenever a major bump would mean a *different artifact* rather
than a newer one — `jaegertracing/all-in-one` is held to `1` because Jaeger v2
is a different image with a different CLI, and an unrestricted pin would
"update" that lab into something that does not start.

## Known gaps

These are deliberate. Each is a decision, not an oversight.

- **`labs/ema-mcp/run.sh` is digest-pinned, not automated.**
  `ceposta/keycloak:id-jag` is a mutable tag on a third party's personal Docker
  Hub account, with no version in it and no release feed behind it, so there is
  nothing for a cooldown to measure or an update to move it to. It is pinned by
  digest so the bytes are at least fixed; refreshing it is a manual decision
  about whether the new contents are trustworthy, and the command to resolve a
  new digest is in the comment above the pin.
- **`FROM python:3.13-slim` is not automated.** A floating tag: rebuilt whenever
  its base OS changes, so the labs already get those patches on every build, and
  its `last_updated` is perpetually a day old — which makes a release cooldown
  structurally unmeasurable. What the pin actually controls is 3.13 versus 3.14,
  a compatibility decision that belongs in a human PR that re-runs the labs.
- **Recorded output is reported, never rewritten.** READMEs and `evidence/` hold
  captured terminal transcripts. Regex-editing one to name a version nobody ran
  would be fabricating evidence, and `docker compose ps` column alignment would
  not survive it. `check_doc_drift.py` annotates them instead, and names which of
  the two homes applies — see below. It matches two shapes: a full `repo:tag`
  reference, and a bare product name plus version (`kc.sh --version` prints
  `Keycloak 26.7.2`, which has no registry path to match on). The second only
  applies to plain-semver pins, because a templated tag like python's
  `3.13-slim` has no clean version to compare against and the labs legitimately
  print a fuller `Python 3.13.12`.
- **`labs/*/README.md` is not editable here.** Each one is generated from that
  lab's `.mdx` in `Zenable-io/next-gen-governance`
  (`services/ui_frontend/src/lib/labs/content/labs/`) and carries a "Do not edit
  by hand" banner. A stale transcript in a README is fixed *there*, then
  re-exported with
  `node services/ui_frontend/scripts/export-lab-readme.js --all <this repo>`.
  An edit committed here is silently reverted by the next export. `evidence/`,
  the rig code, and the compose/Dockerfile pins the automation touches are all
  owned by this repository, which is why they are safe to rewrite.
- **Nothing here runs the labs.** These PRs are not proof a bump works. That is
  `next-gen-governance`'s `task e2e`.
- **Branch reachability is advisory for tag-sourced pins**, and a hard failure
  only for Action SHAs. Release tooling routinely tags a commit that never lands
  on a branch — Keycloak's `Set version to 26.7.2` is tagged and then superseded
  on `release/26.7` — so failing on it would block correctly-published releases.
  The tag-ref check above is what carries the guarantee there; for an Action pin
  there is no ref to lean on, so reachability stays mandatory.

#!/usr/bin/env bash
#
# Refresh every pinned dependency in this repository.
#
# Each block below is one pin: the upstream it comes from, the files that carry
# it, and the regex that finds it. Explicit and repetitive on purpose — a pin is
# reviewed by reading it, and a table-driven loop would hide the one field that
# ever matters (the search pattern) behind indirection.
#
# Run it locally the same way CI does:
#   bash .github/scripts/update-pins.sh
#
# Every version bump is gated on a 7-day cooldown, and GitHub-sourced versions
# additionally have their tag -> commit -> reachable-from-branch chain verified
# before anything is written. See supply_chain/cooldown.py and supply_chain/github.py.

set -euo pipefail

GIT_ROOT="$(git rev-parse --show-toplevel)"
SCRIPTS_DIR="${GIT_ROOT}/.github/scripts"

# --frozen so a run cannot silently resolve the tooling's own dependencies to
# something newer than the committed lock.
UPDATE_FILE=(uv run --directory "${SCRIPTS_DIR}" --frozen python update_file.py)

# ---------------------------------------------------------------------------
# Container images
# ---------------------------------------------------------------------------

# Keycloak. The image lives on quay.io, which publishes no usable release feed,
# but the upstream GitHub releases carry the same version numbers and give us a
# real publish date plus the tag/commit integrity check quay cannot.
# Both labs run the same Keycloak, so one lookup updates both files.
"${UPDATE_FILE[@]}" \
  --file "${GIT_ROOT}/labs/a2a/docker-compose.yml" \
  --file "${GIT_ROOT}/labs/agent-identity/docker-compose.yml" \
  --source-type github-release \
  --github-owner keycloak \
  --github-repo keycloak \
  --no-v-prefix \
  --pin-level patch \
  --no-downgrade \
  --search-pattern 'quay\.io/keycloak/keycloak:[0-9]+\.[0-9]+\.[0-9]+' \
  --replacement-pattern 'quay.io/keycloak/keycloak:{version}'

# agentgateway. Image on ghcr.io, versions from GitHub releases.
# Note the anchored tag pattern is doing real work here: agentgateway ships
# `v1.4.0-beta.1` with `prerelease: false`, so release metadata alone would let a
# beta through.
#
# Held at v1.4.1 on purpose as of 2026-09-03, and this pin is still automated so
# the next run proposes v1.5.0 again. Read that PR before merging it: v1.5.0
# renames the trace spans this lab teaches. `POST /*` disappears, `delete_session`
# and `get_stream` become `DELETE get-started` / `GET get-started`, and
# `tools/call get-started` splits per tool into `tools/call get-started_add`.
# That invalidates two recorded transcripts, the sentence about a tool call
# naming its target, and the instruction to click a `POST /*` row to find the
# parent span — all of which live in agentgateway-mcp.mdx in
# next-gen-governance. It is a lab-content change needing an author, not a
# version bump, which is why it was not taken here.
"${UPDATE_FILE[@]}" \
  --file "${GIT_ROOT}/labs/agentgateway-mcp/compose.yaml" \
  --source-type github-release \
  --github-owner agentgateway \
  --github-repo agentgateway \
  --pin-level patch \
  --no-downgrade \
  --search-pattern 'ghcr\.io/agentgateway/agentgateway:v[0-9]+\.[0-9]+\.[0-9]+' \
  --replacement-pattern 'ghcr.io/agentgateway/agentgateway:{version}'

# Jaeger all-in-one, held to the 1.x line. Jaeger v2 is a different image
# (`jaegertracing/jaeger`) with a different CLI, so an unrestricted pin would
# "update" this lab into something that does not start.
"${UPDATE_FILE[@]}" \
  --file "${GIT_ROOT}/labs/agentgateway-mcp/compose.yaml" \
  --source-type docker-hub \
  --image jaegertracing/all-in-one \
  --version-line 1 \
  --pin-level patch \
  --no-downgrade \
  --search-pattern 'jaegertracing/all-in-one:[0-9]+\.[0-9]+\.[0-9]+' \
  --replacement-pattern 'jaegertracing/all-in-one:{version}'

# NOT automated: `FROM python:3.13-slim`, in every lab Dockerfile.
#
# `3.13-slim` is a floating tag. Docker Hub rebuilds it whenever its base OS gets
# security updates, so the labs already receive those on every build with no pin
# change at all, and the tag's `last_updated` is perpetually a day old — which
# makes a release cooldown structurally unmeasurable for it. (get_matching_tags
# would return candidates that are all "too recent" forever, so this would fail
# closed and silently do nothing, but a pin that can never move should not be
# here pretending to.)
#
# What the pin actually controls is 3.13 versus 3.14, which is a compatibility
# decision for the labs' dependencies, not a supply-chain one. That belongs in a
# human PR that also re-runs the labs, so it is left out on purpose.
#
# The supply chain for this image is the digest, not the tag. If that matters
# more than the READMEs staying readable, pin `python:3.13-slim@sha256:...` and
# revisit.

# ---------------------------------------------------------------------------
# Python lockfiles
# ---------------------------------------------------------------------------
#
# The cooldown for these is declarative: `exclude-newer = "7 days"` in each
# project's [tool.uv]. `uv lock --upgrade` honours it, so a package published
# yesterday is not resolvable here regardless of what this script does.

echo "==> Refreshing uv lockfiles"
while IFS= read -r project; do
  echo "--> ${project}"
  uv lock --directory "${project}" --upgrade
done < <(git -C "${GIT_ROOT}" ls-files '*pyproject.toml' | xargs -n1 dirname | sed "s|^|${GIT_ROOT}/|")

# ---------------------------------------------------------------------------
# Documentation drift
# ---------------------------------------------------------------------------
#
# Recorded terminal output is evidence, not configuration: rewriting a
# `docker compose ps` transcript to name a version nobody ran would be
# fabricating it. So the transcripts are reported, never edited, and a human
# regenerates them by running the lab.

echo "==> Checking for documentation quoting superseded versions"
uv run --directory "${SCRIPTS_DIR}" --frozen python check_doc_drift.py

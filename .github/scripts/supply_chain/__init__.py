"""Supply-chain primitives for the Zenable Labs dependency automation.

A deliberately small subset of ``zenable_monorepo`` from Zenable-io/next-gen-governance,
carrying only what this repository's pins need: a release cooldown, GitHub release
and tag->commit integrity verification, Docker Hub tag discovery, and CI annotations.

Vendored rather than depended on because next-gen-governance is private and this
repository is public. The security-relevant logic — the cooldown window, the
release -> tag ref -> commit -> reachable-from-branch chain — is kept behaviourally
identical to upstream so a fix there ports here as a readable diff. When a third
repository needs this, extract these modules into a package both can consume
rather than vendoring a second copy.
"""

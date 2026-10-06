# Copyright (c) 2026 Zenable, Inc. The same agent, in a container, so Docker's seccomp profile applies to it.
# Same userland as the sandbox host on purpose: the lab generates its profile
# from a trace taken on the host, and a newer glibc in the container would
# reach for syscalls (clone3, rseq) the trace never saw. Built with
# --network=host on the sandbox: Docker's build network is IPv4-only there and
# the RUN steps below fetch from the internet.
FROM rockylinux:8
ARG GOOSE_VERSION=v1.46.0
RUN dnf install -y -q bzip2 ca-certificates curl && dnf clean all
# The tarball's one member is ./goose, so it is extracted by that name.
RUN curl -fsSL "https://github.com/aaif-goose/goose/releases/download/${GOOSE_VERSION}/goose-x86_64-unknown-linux-gnu.tar.bz2" \
  | tar -xj -C /usr/local/bin ./goose \
  && goose --version
WORKDIR /lab
COPY goose/config /lab/goose/config
COPY workspace /lab/workspace
COPY decoys /lab/decoys
COPY run-agent.sh /lab/run-agent.sh
ENV HOME=/lab
ENTRYPOINT ["/lab/run-agent.sh"]

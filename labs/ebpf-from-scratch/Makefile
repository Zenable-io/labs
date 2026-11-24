# Copyright (c) 2026 Zenable, Inc. Compile the BPF programs. vmlinux.h is generated from the running kernel's
# BTF, so the structs the programs read match this kernel exactly (CO-RE).
CLANG ?= clang
BPFTOOL ?= bpftool
ARCH := $(shell uname -m | sed 's/x86_64/x86/;s/aarch64/arm64/')

BPF_SRC := $(wildcard bpf/*.bpf.c)
BPF_OBJ := $(BPF_SRC:.bpf.c=.bpf.o)

all: $(BPF_OBJ)

bpf/vmlinux.h:
	$(BPFTOOL) btf dump file /sys/kernel/btf/vmlinux format c > $@

# Kernel BTF has tagged anonymous members; match the kernel's C dialect
# so those members contribute to struct layout.
bpf/%.bpf.o: bpf/%.bpf.c bpf/vmlinux.h bpf/policy.h
	$(CLANG) -O2 -g -target bpf -D__TARGET_ARCH_$(ARCH) -Wall -fms-extensions -Ibpf -c $< -o $@

clean:
	rm -f $(BPF_OBJ) bpf/vmlinux.h

.PHONY: all clean

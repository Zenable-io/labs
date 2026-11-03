// Copyright (c) 2026 Zenable, Inc. agentdeny: the same credential check as agentwatch, on an LSM hook.
//
// A tracepoint runs beside the syscall and can only react; an LSM hook runs
// inside the kernel's permission check and its return value IS the decision.
// Needs `bpf` in /sys/kernel/security/lsm. Built and loaded separately so the
// watch-only program works on a kernel without it.
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include "policy.h"

char LICENSE[] SEC("license") = "GPL";

#define EPERM 1

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, __u64);
} denied_count SEC(".maps");

SEC("lsm/file_open")
int BPF_PROG(deny_credential_open, struct file *file, int ret)
{
    // The final argument carries any earlier BPF LSM decision.
    if (ret || !in_scope())
        return ret;
    char path[PATH_MAX_BYTES] = {};
    long resolved = bpf_d_path((struct path *)&file->f_path, path, sizeof(path));
    if (resolved >= 0 && !is_credential_path(path))
        return 0;
    __u32 key = 0;
    __u64 *count = bpf_map_lookup_elem(&denied_count, &key);
    if (count)
        __sync_fetch_and_add(count, 1);
    return -EPERM;
}

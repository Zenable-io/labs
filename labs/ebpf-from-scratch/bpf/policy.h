// Copyright (c) 2026 Zenable, Inc.
#ifndef AGENTWATCH_POLICY_H
#define AGENTWATCH_POLICY_H

#define PATH_MAX_BYTES 256

struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 2);
    __type(key, __u32);
    __type(value, __u64);
} scope_config SEC(".maps");

static __always_inline int in_scope(void)
{
    __u32 key = 0;
    __u64 *id = bpf_map_lookup_elem(&scope_config, &key);
    return id && *id && bpf_get_current_cgroup_id() == *id;
}

static const char CREDENTIAL_MARK[] = "/.aws/";

// True when the path contains "/.aws/". A bounded scan the verifier accepts;
// the kernel offers no strstr, and a credential path can sit at any depth.
static __always_inline int is_credential_path(const char *path)
{
    for (int i = 0; i < PATH_MAX_BYTES - sizeof(CREDENTIAL_MARK); i++) {
        if (path[i] == '\0')
            return 0;
        int hit = 1;
        for (int j = 0; j < sizeof(CREDENTIAL_MARK) - 1; j++) {
            if (path[i + j] != CREDENTIAL_MARK[j]) {
                hit = 0;
                break;
            }
        }
        if (hit)
            return 1;
    }
    return 0;
}

#endif

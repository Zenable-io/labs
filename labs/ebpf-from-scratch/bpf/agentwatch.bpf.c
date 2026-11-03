// Copyright (c) 2026 Zenable, Inc.
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>
#include "policy.h"

char LICENSE[] SEC("license") = "GPL";

#define COMM_BYTES 16
#define SIGKILL 9

enum event_kind {
    EVENT_FORK = 1,
    EVENT_EXEC = 2,
    EVENT_OPEN = 3,
    EVENT_CONNECT = 4,
    EVENT_DENIED = 5,
};

// The wire shape agentwatch.py decodes. Keep the Python Struct in step.
struct event {
    __u32 kind;
    __u32 pid;
    __u32 ppid;
    __u32 uid;
    char comm[COMM_BYTES];
    // openat/execve: the path. connect: the sockaddr, raw. fork: the child pid
    // as text is not needed; ppid/pid carry it.
    char data[PATH_MAX_BYTES];
};

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 1 << 20);
} events SEC(".maps");

// Index 0: 1 = send SIGKILL to a process that opens a credential path.
struct {
    __uint(type, BPF_MAP_TYPE_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, __u32);
} watch_config SEC(".maps");

static __always_inline int should_observe(void)
{
    __u32 key = 1;
    __u64 *all = bpf_map_lookup_elem(&scope_config, &key);
    return (all && *all) || in_scope();
}

static __always_inline struct event *reserve(__u32 kind)
{
    struct event *e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return NULL;
    __builtin_memset(e, 0, sizeof(*e));
    __u64 pid_tgid = bpf_get_current_pid_tgid();
    struct task_struct *task = (struct task_struct *)bpf_get_current_task();
    e->kind = kind;
    e->pid = pid_tgid >> 32;
    e->ppid = BPF_CORE_READ(task, real_parent, tgid);
    e->uid = bpf_get_current_uid_gid() & 0xffffffff;
    bpf_get_current_comm(&e->comm, sizeof(e->comm));
    e->data[0] = '\0';
    return e;
}

static __always_inline int kill_wanted(void)
{
    __u32 key = 0;
    __u32 *flag = bpf_map_lookup_elem(&watch_config, &key);
    return flag && *flag;
}

SEC("tracepoint/sched/sched_process_fork")
int on_fork(struct trace_event_raw_sched_process_fork *ctx)
{
    if (!should_observe())
        return 0;
    struct event *e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;
    __builtin_memset(e, 0, sizeof(*e));
    e->kind = EVENT_FORK;
    e->pid = ctx->child_pid;
    e->ppid = ctx->parent_pid;
    e->uid = bpf_get_current_uid_gid() & 0xffffffff;
    // The tracepoint runs in the parent, and a fresh child carries its
    // parent's comm until it execs, so the current comm is the child's too.
    bpf_get_current_comm(&e->comm, sizeof(e->comm));
    e->data[0] = '\0';
    bpf_ringbuf_submit(e, 0);
    return 0;
}

SEC("tracepoint/syscalls/sys_enter_execve")
int on_execve(struct trace_event_raw_sys_enter *ctx)
{
    if (!should_observe())
        return 0;
    struct event *e = reserve(EVENT_EXEC);
    if (!e)
        return 0;
    const char *filename = (const char *)ctx->args[0];
    bpf_probe_read_user_str(e->data, sizeof(e->data), filename);
    bpf_ringbuf_submit(e, 0);
    return 0;
}

SEC("tracepoint/syscalls/sys_enter_openat")
int on_openat(struct trace_event_raw_sys_enter *ctx)
{
    if (!should_observe())
        return 0;
    char path[PATH_MAX_BYTES] = {};
    const char *filename = (const char *)ctx->args[1];
    bpf_probe_read_user_str(path, sizeof(path), filename);
    int killed = in_scope() && kill_wanted() && is_credential_path(path);
    // Enforcement cannot depend on space in the telemetry ring.
    if (killed)
        bpf_send_signal(SIGKILL);
    struct event *e = reserve(killed ? EVENT_DENIED : EVENT_OPEN);
    if (!e)
        return 0;
    __builtin_memcpy(e->data, path, sizeof(path));
    bpf_ringbuf_submit(e, 0);
    return 0;
}

SEC("tracepoint/syscalls/sys_enter_connect")
int on_connect(struct trace_event_raw_sys_enter *ctx)
{
    if (!should_observe())
        return 0;
    struct event *e = reserve(EVENT_CONNECT);
    if (!e)
        return 0;
    const void *addr = (const void *)ctx->args[1];
    __u64 len = ctx->args[2];
    if (len > 128)
        len = 128;
    if (len)
        bpf_probe_read_user(e->data, len, addr);
    bpf_ringbuf_submit(e, 0);
    return 0;
}

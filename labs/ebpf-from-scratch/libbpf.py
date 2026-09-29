"""Copyright (c) 2026 Zenable, Inc. The few libbpf calls this lab needs, through ctypes.

libbpf is the C library that opens a compiled BPF object, loads its programs
and maps into the kernel, attaches the programs, and reads ring buffers back.
There is no Python binding worth depending on, and the API surface a loader
needs is small enough to declare by hand.
"""

import ctypes
import ctypes.util
import errno
import os
from collections.abc import Callable
from functools import cache
from types import TracebackType


def _load() -> ctypes.CDLL:
    name = ctypes.util.find_library("bpf")
    if name is None:
        raise RuntimeError("libbpf 1.x not found; install the sandbox eBPF toolchain")
    result = ctypes.CDLL(name, use_errno=True)
    if not hasattr(result, "bpf_object__next_program"):
        raise RuntimeError(
            "libbpf 1.x is required for current-kernel BTF; upgrade the toolchain"
        )
    return result


# Opaque handles; only ever passed back to libbpf.
BpfObject = ctypes.c_void_p
BpfProgram = ctypes.c_void_p
BpfMap = ctypes.c_void_p
BpfLink = ctypes.c_void_p
RingBuffer = ctypes.c_void_p

RING_BUFFER_SAMPLE_FN = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t
)


@cache
def library() -> ctypes.CDLL:
    _lib = _load()
    _lib.bpf_object__open_file.restype = BpfObject
    _lib.bpf_object__open_file.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
    _lib.bpf_object__load.restype = ctypes.c_int
    _lib.bpf_object__load.argtypes = [BpfObject]
    _lib.bpf_object__close.restype = None
    _lib.bpf_object__close.argtypes = [BpfObject]
    _lib.bpf_object__next_program.restype = BpfProgram
    _lib.bpf_object__next_program.argtypes = [BpfObject, BpfProgram]

    _lib.bpf_program__name.restype = ctypes.c_char_p
    _lib.bpf_program__name.argtypes = [BpfProgram]
    _lib.bpf_program__attach.restype = BpfLink
    _lib.bpf_program__attach.argtypes = [BpfProgram]
    _lib.bpf_object__find_map_by_name.restype = BpfMap
    _lib.bpf_object__find_map_by_name.argtypes = [BpfObject, ctypes.c_char_p]
    _lib.bpf_map__fd.restype = ctypes.c_int
    _lib.bpf_map__fd.argtypes = [BpfMap]
    _lib.bpf_map_update_elem.restype = ctypes.c_int
    _lib.bpf_map_update_elem.argtypes = [
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint64,
    ]
    _lib.bpf_map_lookup_elem.restype = ctypes.c_int
    _lib.bpf_map_lookup_elem.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
    _lib.ring_buffer__new.restype = RingBuffer
    _lib.ring_buffer__new.argtypes = [
        ctypes.c_int,
        RING_BUFFER_SAMPLE_FN,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    _lib.ring_buffer__poll.restype = ctypes.c_int
    _lib.ring_buffer__poll.argtypes = [RingBuffer, ctypes.c_int]
    _lib.ring_buffer__free.restype = None
    _lib.ring_buffer__free.argtypes = [RingBuffer]
    _lib.libbpf_get_error.restype = ctypes.c_long
    _lib.libbpf_get_error.argtypes = [ctypes.c_void_p]

    _lib.bpf_link__destroy.restype = ctypes.c_int
    _lib.bpf_link__destroy.argtypes = [BpfLink]
    return _lib


def _errno_text() -> str:
    code = ctypes.get_errno()
    return f"{os.strerror(code)} (errno {code})"


class Object:
    """A compiled BPF object and the links that keep its policies attached."""

    def __init__(self, path: str) -> None:
        self.lib = library()
        self.handle = self.lib.bpf_object__open_file(path.encode(), None)
        if not self.handle or self.lib.libbpf_get_error(self.handle):
            raise RuntimeError(f"could not open {path}: {_errno_text()}")
        self.links: list[BpfLink] = []

    def __enter__(self) -> "Object":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def load(self) -> None:
        if self.lib.bpf_object__load(self.handle) != 0:
            raise RuntimeError(f"kernel rejected the object: {_errno_text()}")

    def _next_program(self, program: BpfProgram | None) -> BpfProgram:
        return self.lib.bpf_object__next_program(self.handle, program)

    def attach_all(self) -> list[str]:
        names = []
        program = self._next_program(None)
        while program:
            name = self.lib.bpf_program__name(program).decode()
            link = self.lib.bpf_program__attach(program)
            if not link or self.lib.libbpf_get_error(link):
                raise RuntimeError(f"could not attach {name}: {_errno_text()}")
            self.links.append(link)
            names.append(name)
            program = self._next_program(program)
        return names

    def map_fd(self, name: str) -> int:
        bpf_map = self.lib.bpf_object__find_map_by_name(self.handle, name.encode())
        if not bpf_map:
            raise RuntimeError(f"no map named {name} in the object")
        fd = self.lib.bpf_map__fd(bpf_map)
        if fd < 0:
            raise RuntimeError(f"map {name} is not loaded")
        return fd

    def close(self) -> None:
        errors = []
        while self.links:
            result = self.lib.bpf_link__destroy(self.links.pop())
            if result:
                errors.append(os.strerror(-result))
        if self.handle:
            self.lib.bpf_object__close(self.handle)
            self.handle = None
        if errors:
            raise RuntimeError(f"could not detach BPF links: {', '.join(errors)}")


def map_set_u32(fd: int, key: int, value: int) -> None:
    k = ctypes.c_uint32(key)
    v = ctypes.c_uint32(value)
    if library().bpf_map_update_elem(fd, ctypes.byref(k), ctypes.byref(v), 0) != 0:
        raise RuntimeError(f"map update failed: {_errno_text()}")


def map_set_u64(fd: int, key: int, value: int) -> None:
    k = ctypes.c_uint32(key)
    v = ctypes.c_uint64(value)
    if library().bpf_map_update_elem(fd, ctypes.byref(k), ctypes.byref(v), 0) != 0:
        raise RuntimeError(f"map update failed: {_errno_text()}")


def map_get_u64(fd: int, key: int) -> int:
    k = ctypes.c_uint32(key)
    v = ctypes.c_uint64(0)
    if library().bpf_map_lookup_elem(fd, ctypes.byref(k), ctypes.byref(v)) != 0:
        raise RuntimeError(f"map lookup failed: {_errno_text()}")
    return v.value


class Ring:
    """A ring buffer whose callback failures propagate through poll."""

    def __init__(self, fd: int, on_record: Callable[[bytes], None]) -> None:
        self.lib = library()
        self.error: BaseException | None = None
        self.on_record = on_record
        # ctypes otherwise swallows callback exceptions and continues polling.
        self._callback = RING_BUFFER_SAMPLE_FN(self._sample)
        self.handle = self.lib.ring_buffer__new(fd, self._callback, None, None)
        if not self.handle or self.lib.libbpf_get_error(self.handle):
            raise RuntimeError(f"could not open the ring buffer: {_errno_text()}")

    def __enter__(self) -> "Ring":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.free()

    def _sample(self, _ctx: int, data: int, size: int) -> int:
        try:
            self.on_record(ctypes.string_at(data, size))
        except BaseException as error:
            self.error = error
            return -errno.EIO
        return 0

    def poll(self, timeout_ms: int) -> int:
        result = self.lib.ring_buffer__poll(self.handle, timeout_ms)
        if self.error is not None:
            raise self.error
        if result == -errno.EINTR:
            return 0
        if result < 0:
            raise OSError(-result, os.strerror(-result))
        return result

    def free(self) -> None:
        if self.handle:
            self.lib.ring_buffer__free(self.handle)
            self.handle = None

# Copyright (c) 2026 Zenable, Inc.
import ctypes
import errno
from unittest.mock import Mock, call

import libbpf
import pytest


@pytest.fixture
def native(monkeypatch: pytest.MonkeyPatch) -> Mock:
    library = Mock()
    library.bpf_object__open_file.return_value = 100
    library.libbpf_get_error.return_value = 0
    library.bpf_object__load.return_value = 0
    library.bpf_object__next_program.side_effect = [1, 2, None]
    library.bpf_program__name.side_effect = [b"first", b"second"]
    library.bpf_program__attach.side_effect = [11, 12]
    library.bpf_link__destroy.return_value = 0
    library.ring_buffer__new.return_value = 200
    monkeypatch.setattr(libbpf, "library", lambda: library)
    return library


@pytest.mark.unit
def test_close_detaches_all_links_before_closing_object(native: Mock) -> None:
    with libbpf.Object("test.o") as obj:
        obj.load()
        assert obj.attach_all() == ["first", "second"]
    assert native.mock_calls[-3:] == [
        call.bpf_link__destroy(12),
        call.bpf_link__destroy(11),
        call.bpf_object__close(100),
    ]
    obj.close()
    assert native.bpf_object__close.call_count == 1


@pytest.mark.unit
def test_partial_attach_failure_releases_the_successful_link(native: Mock) -> None:
    native.bpf_program__attach.side_effect = [11, None]
    with pytest.raises(RuntimeError, match="could not attach second"):
        with libbpf.Object("test.o") as obj:
            obj.attach_all()
    native.bpf_link__destroy.assert_called_once_with(11)
    native.bpf_object__close.assert_called_once_with(100)


@pytest.mark.unit
def test_detach_failure_does_not_leak_other_handles(native: Mock) -> None:
    native.bpf_link__destroy.side_effect = [-errno.EIO, 0]
    with pytest.raises(RuntimeError, match="could not detach"):
        with libbpf.Object("test.o") as obj:
            obj.attach_all()
    assert native.bpf_link__destroy.call_count == 2
    native.bpf_object__close.assert_called_once_with(100)


@pytest.mark.unit
def test_load_failure_closes_object(native: Mock) -> None:
    native.bpf_object__load.return_value = -errno.EPERM
    with pytest.raises(RuntimeError, match="kernel rejected"):
        with libbpf.Object("test.o") as obj:
            obj.load()
    native.bpf_object__close.assert_called_once_with(100)


@pytest.mark.unit
def test_ring_callback_exception_propagates_and_frees_ring(native: Mock) -> None:
    record = ctypes.create_string_buffer(b"bad event")

    def fail(_record: bytes) -> None:
        raise ValueError("invalid event")

    with pytest.raises(ValueError, match="invalid event"):
        with libbpf.Ring(1, fail) as ring:
            native.ring_buffer__poll.side_effect = lambda *_: ring._callback(
                None, ctypes.addressof(record), len(record)
            )
            ring.poll(1)
    native.ring_buffer__free.assert_called_once_with(200)
    ring.free()
    assert native.ring_buffer__free.call_count == 1


@pytest.mark.unit
def test_ring_poll_propagates_native_failure(native: Mock) -> None:
    native.ring_buffer__poll.side_effect = [-errno.EINTR, -errno.EBADF]
    with libbpf.Ring(1, lambda _: None) as ring:
        assert ring.poll(1) == 0
        with pytest.raises(OSError) as error:
            ring.poll(1)
    assert error.value.errno == errno.EBADF


@pytest.mark.unit
def test_cgroup_id_is_written_as_full_64_bit_value(native: Mock) -> None:
    def update(_fd: int, _key: object, value: object, _flags: int) -> int:
        assert (
            ctypes.cast(value, ctypes.POINTER(ctypes.c_uint64)).contents.value
            == (1 << 40) + 123
        )
        return 0

    native.bpf_map_update_elem.side_effect = update
    libbpf.map_set_u64(1, 0, (1 << 40) + 123)

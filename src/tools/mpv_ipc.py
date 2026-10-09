"""Connection helpers for mpv's Unix socket and Windows named-pipe IPC."""

from __future__ import annotations

import os
import socket
import time
from typing import Any


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _OPEN_EXISTING = 3
    _ERROR_PIPE_BUSY = 231
    _ERROR_FILE_NOT_FOUND = 2
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    _kernel32.WaitNamedPipeW.restype = wintypes.BOOL
    _kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    _kernel32.WriteFile.restype = wintypes.BOOL
    _kernel32.ReadFile.argtypes = _kernel32.WriteFile.argtypes
    _kernel32.ReadFile.restype = wintypes.BOOL
    _kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    _kernel32.PeekNamedPipe.restype = wintypes.BOOL

    class WindowsPipeClient:
        def __init__(self, address: str, handle: int, timeout: float) -> None:
            self.address = address
            self.handle = handle
            self.timeout = timeout

        def __enter__(self) -> "WindowsPipeClient":
            return self

        def __exit__(self, *_exc: Any) -> None:
            _kernel32.CloseHandle(self.handle)

        def settimeout(self, timeout: float) -> None:
            self.timeout = timeout

        def sendall(self, data: bytes) -> None:
            sent = 0
            while sent < len(data):
                written = wintypes.DWORD()
                buffer = ctypes.create_string_buffer(data[sent:])
                ok = _kernel32.WriteFile(
                    self.handle,
                    buffer,
                    len(data) - sent,
                    ctypes.byref(written),
                    None,
                )
                if not ok or not written.value:
                    raise OSError("Could not write to mpv named pipe.")
                sent += written.value

        def recv(self, size: int) -> bytes:
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                available = wintypes.DWORD()
                if not _kernel32.PeekNamedPipe(
                    self.handle, None, 0, None, ctypes.byref(available), None
                ):
                    raise OSError("mpv named pipe was closed.")
                if available.value:
                    buffer = ctypes.create_string_buffer(min(size, available.value))
                    received = wintypes.DWORD()
                    if not _kernel32.ReadFile(
                        self.handle,
                        buffer,
                        len(buffer),
                        ctypes.byref(received),
                        None,
                    ):
                        raise OSError("Could not read from mpv named pipe.")
                    return buffer.raw[: received.value]
                time.sleep(0.01)
            raise TimeoutError("Timed out waiting for mpv IPC response.")


def mpv_ipc_address(session_id: str) -> str:
    if os.name == "nt":
        return rf"\\.\pipe\sonex-mpv-{session_id}"
    import tempfile

    return os.path.join(tempfile.gettempdir(), f"sonex-mpv-{session_id}.sock")


def connect_mpv(address: str, timeout: float = 1.0) -> Any:
    if os.name != "nt":
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(address)
        return client

    deadline = time.monotonic() + timeout
    while True:
        handle = _kernel32.CreateFileW(
            address,
            _GENERIC_READ | _GENERIC_WRITE,
            0,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle != _INVALID_HANDLE_VALUE:
            return WindowsPipeClient(address, handle, timeout)
        error = ctypes.get_last_error()
        if error not in {_ERROR_PIPE_BUSY, _ERROR_FILE_NOT_FOUND} or time.monotonic() >= deadline:
            raise OSError(error, "Could not connect to mpv named pipe.")
        _kernel32.WaitNamedPipeW(address, 50)

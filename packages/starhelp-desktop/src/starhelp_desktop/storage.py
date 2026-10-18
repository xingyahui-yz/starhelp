from __future__ import annotations

import ctypes
import json
import os
import tempfile
from ctypes import POINTER, Structure, byref, c_uint32, c_void_p, c_wchar_p
from pathlib import Path
from typing import Protocol
from uuid import UUID


_MAX_PRIVATE_OBJECT_BYTES = 64 * 1024 * 1024
_MAX_DPAPI_ENVELOPE_OVERHEAD = 64 * 1024


class DataProtector(Protocol):
    def protect(self, data: bytes) -> bytes: ...

    def unprotect(self, data: bytes) -> bytes: ...


class WindowsDpapiProtector:
    """Protect data for the current Windows user; no plaintext fallback exists."""

    class _Blob(Structure):
        _fields_ = [("cbData", c_uint32), ("pbData", POINTER(ctypes.c_ubyte))]

    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows DPAPI is required for private account persistence")
        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._crypt32.CryptProtectData.argtypes = [
            POINTER(self._Blob), c_wchar_p, POINTER(self._Blob), c_void_p, c_void_p,
            c_uint32, POINTER(self._Blob),
        ]
        self._crypt32.CryptProtectData.restype = ctypes.c_int
        self._crypt32.CryptUnprotectData.argtypes = [
            POINTER(self._Blob), POINTER(c_void_p), POINTER(self._Blob), c_void_p,
            c_void_p, c_uint32, POINTER(self._Blob),
        ]
        self._crypt32.CryptUnprotectData.restype = ctypes.c_int
        self._kernel32.LocalFree.argtypes = [c_void_p]
        self._kernel32.LocalFree.restype = c_void_p

    @classmethod
    def _input_blob(cls, data: bytes) -> tuple[WindowsDpapiProtector._Blob, object]:
        storage = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        blob = cls._Blob(len(data), ctypes.cast(storage, POINTER(ctypes.c_ubyte)))
        return blob, storage

    def _transform(self, data: bytes, *, decrypt: bool) -> bytes:
        source, _keepalive = self._input_blob(data)
        output = self._Blob()
        if decrypt:
            ok = self._crypt32.CryptUnprotectData(
                byref(source), None, None, None, None, self._CRYPTPROTECT_UI_FORBIDDEN,
                byref(output),
            )
        else:
            ok = self._crypt32.CryptProtectData(
                byref(source), "StarHelp private local data", None, None, None,
                self._CRYPTPROTECT_UI_FORBIDDEN, byref(output),
            )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)

    def protect(self, data: bytes) -> bytes:
        return self._transform(data, decrypt=False)

    def unprotect(self, data: bytes) -> bytes:
        return self._transform(data, decrypt=True)


class EncryptedPrivateStore:
    """Atomic encrypted object files; callers never write private JSON to disk."""

    def __init__(self, root: Path, protector: DataProtector) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._protector = protector

    @classmethod
    def for_current_user(cls) -> EncryptedPrivateStore:
        if os.name != "nt":
            raise OSError("private account storage is available only on Windows")
        base = Path(os.environ["LOCALAPPDATA"]) / "StarHelp" / "private"
        return cls(base, WindowsDpapiProtector())

    @staticmethod
    def _safe_key(key: str) -> str:
        if not key or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in key):
            raise ValueError("invalid private-store key")
        if key in {".", ".."}:
            raise ValueError("invalid private-store key")
        return key

    def save(self, key: str, value: dict[str, object]) -> Path:
        safe_key = self._safe_key(key)
        plaintext = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(plaintext) > _MAX_PRIVATE_OBJECT_BYTES:
            raise ValueError("private object exceeds the configured size limit")
        encrypted = b"SHDPAPI1" + self._protector.protect(plaintext)
        if len(encrypted) > _MAX_PRIVATE_OBJECT_BYTES + _MAX_DPAPI_ENVELOPE_OVERHEAD:
            raise ValueError("encrypted private object exceeds the configured size limit")
        destination = self.root / f"{safe_key}.bin"
        descriptor, name = tempfile.mkstemp(prefix=f".{safe_key}.", suffix=".tmp", dir=self.root)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        return destination

    def load(self, key: str) -> dict[str, object]:
        path = self.root / f"{self._safe_key(key)}.bin"
        max_envelope = _MAX_PRIVATE_OBJECT_BYTES + _MAX_DPAPI_ENVELOPE_OVERHEAD
        with path.open("rb") as stream:
            payload = stream.read(max_envelope + 1)
        if len(payload) > max_envelope:
            raise ValueError("encrypted private object exceeds the configured size limit")
        if not payload.startswith(b"SHDPAPI1"):
            raise ValueError("private object has an unknown encryption envelope")
        plaintext = self._protector.unprotect(payload[8:])
        if len(plaintext) > _MAX_PRIVATE_OBJECT_BYTES:
            raise ValueError("private object exceeds the configured size limit")
        value = json.loads(plaintext.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("private object root must be a JSON object")
        return value

    def delete_profile(self, profile_id: UUID) -> tuple[Path, ...]:
        prefix = f"profile-{profile_id.hex}-"
        removed: list[Path] = []
        for path in self.root.glob(f"{prefix}*.bin"):
            path.unlink(missing_ok=True)
            removed.append(path)
        return tuple(removed)

    def list_profile_keys(self, profile_id: UUID, kind: str) -> tuple[str, ...]:
        if not kind or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789-" for char in kind):
            raise ValueError("invalid private object kind")
        prefix = f"profile-{profile_id.hex}-{kind}-"
        return tuple(sorted(
            path.stem for path in self.root.glob(f"{prefix}*.bin") if path.is_file()
        ))

    def delete_key(self, key: str) -> None:
        (self.root / f"{self._safe_key(key)}.bin").unlink(missing_ok=True)

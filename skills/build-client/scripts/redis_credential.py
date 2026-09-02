from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
import re
import sys
from ctypes import wintypes


PROVIDER = "windows-credential-manager"
USERNAME = "redis-password-only"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
ERROR_NO_SUCH_LOGON_SESSION = 1312
MAX_BLOB_BYTES = 2560
REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")


class CredentialError(ValueError):
    pass


def windows_error(action: str, error: int) -> CredentialError:
    if error == ERROR_NO_SUCH_LOGON_SESSION:
        return CredentialError(
            f"Credential Manager {action} has no usable Windows logon session; "
            "run this command as the same interactive Windows desktop user"
        )
    return CredentialError(f"Credential Manager {action} failed with Windows error {error}")


class CREDENTIALW(ctypes.Structure):
    _fields_ = (
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    )


PCREDENTIALW = ctypes.POINTER(CREDENTIALW)


def _windows_api() -> object:
    if os.name != "nt":
        raise CredentialError("Windows Credential Manager is available only on Windows")
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    advapi32.CredWriteW.restype = wintypes.BOOL
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(PCREDENTIALW),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi32.CredDeleteW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None
    return advapi32


def validate_reference(reference: str) -> str:
    if not isinstance(reference, str) or not REFERENCE_PATTERN.fullmatch(reference):
        raise CredentialError("credential reference contains unsupported characters")
    return reference


def _read_pointer(reference: str) -> tuple[object, PCREDENTIALW] | None:
    reference = validate_reference(reference)
    advapi32 = _windows_api()
    pointer = PCREDENTIALW()
    if advapi32.CredReadW(reference, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        return advapi32, pointer
    error = ctypes.get_last_error()
    if error == ERROR_NOT_FOUND:
        return None
    raise windows_error("read", error)


def credential_exists(reference: str) -> bool:
    result = _read_pointer(reference)
    if result is None:
        return False
    advapi32, pointer = result
    advapi32.CredFree(pointer)
    return True


def read_secret(reference: str) -> str:
    """Resolve the protected Redis password in memory without printing it."""
    reference = validate_reference(reference)
    result = _read_pointer(reference)
    if result is None:
        raise CredentialError(
            f"credential reference '{reference}' is not configured; run setup interactively"
        )
    advapi32, pointer = result
    temporary: ctypes.Array[ctypes.c_ubyte] | None = None
    try:
        credential = pointer.contents
        size = int(credential.CredentialBlobSize)
        if size <= 0 or not credential.CredentialBlob:
            raise CredentialError(f"credential reference '{reference}' contains no value")
        temporary = (ctypes.c_ubyte * size)()
        ctypes.memmove(temporary, credential.CredentialBlob, size)
        value = bytes(temporary).decode("utf-16-le")
        if not value:
            raise CredentialError(f"credential reference '{reference}' contains no value")
        return value
    except UnicodeDecodeError as exc:
        raise CredentialError(
            f"credential reference '{reference}' has an unsupported encoding"
        ) from exc
    finally:
        if temporary is not None:
            ctypes.memset(ctypes.addressof(temporary), 0, ctypes.sizeof(temporary))
        advapi32.CredFree(pointer)


def write_secret(reference: str, secret: str) -> None:
    reference = validate_reference(reference)
    if not secret:
        raise CredentialError("Redis password must not be empty")
    if "\x00" in secret:
        raise CredentialError("Redis password must not contain a NUL character")
    encoded = secret.encode("utf-16-le")
    if len(encoded) > MAX_BLOB_BYTES:
        raise CredentialError("Redis password exceeds the Credential Manager size limit")

    advapi32 = _windows_api()
    blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    target = ctypes.create_unicode_buffer(reference)
    username = ctypes.create_unicode_buffer(USERNAME)
    comment = ctypes.create_unicode_buffer("build-client Redis test authentication")
    credential = CREDENTIALW()
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = ctypes.cast(target, wintypes.LPWSTR)
    credential.Comment = ctypes.cast(comment, wintypes.LPWSTR)
    credential.CredentialBlobSize = len(encoded)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = ctypes.cast(username, wintypes.LPWSTR)
    try:
        if not advapi32.CredWriteW(ctypes.byref(credential), 0):
            error = ctypes.get_last_error()
            raise windows_error("write", error)
    finally:
        ctypes.memset(ctypes.addressof(blob), 0, ctypes.sizeof(blob))


def delete_secret(reference: str) -> bool:
    reference = validate_reference(reference)
    advapi32 = _windows_api()
    if advapi32.CredDeleteW(reference, CRED_TYPE_GENERIC, 0):
        return True
    error = ctypes.get_last_error()
    if error == ERROR_NOT_FOUND:
        return False
    raise windows_error("delete", error)


def status_payload(reference: str) -> dict[str, object]:
    return {
        "reference": reference,
        "provider": PROVIDER,
        "configured": credential_exists(reference),
        "secretExposed": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manage the protected build-client Redis credential reference."
    )
    parser.add_argument(
        "--reference",
        required=True,
        type=validate_reference,
        help="exact Credential Manager reference declared by the selected Profile",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="report whether the reference exists")
    setup = subparsers.add_parser("setup", help="store the password using no-echo input")
    setup.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing value after prompting twice",
    )
    delete = subparsers.add_parser("delete", help="delete the protected credential")
    delete.add_argument(
        "--confirm-reference",
        required=True,
        help="exact reference required for deletion",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        reference = args.reference
        if args.command == "status":
            print(json.dumps(status_payload(reference), ensure_ascii=False, indent=2))
            return 0
        if args.command == "setup":
            if credential_exists(reference) and not args.replace:
                payload = status_payload(reference)
                payload["reusedExisting"] = True
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0
            secret = getpass.getpass("Redis password: ")
            confirmation = getpass.getpass("Confirm Redis password: ")
            if secret != confirmation:
                raise CredentialError("Redis password confirmation does not match")
            write_secret(reference, secret)
            print(
                json.dumps(
                    {
                        "reference": reference,
                        "provider": PROVIDER,
                        "configured": True,
                        "replaced": bool(args.replace),
                        "secretExposed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.confirm_reference != reference:
            raise CredentialError("delete confirmation must exactly match --reference")
        deleted = delete_secret(reference)
        print(
            json.dumps(
                {
                    "reference": reference,
                    "provider": PROVIDER,
                    "deleted": deleted,
                    "secretExposed": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except CredentialError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

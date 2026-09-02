#!/usr/bin/env python3
"""Validate the lab Profile and run gated builds on the dedicated SSH host."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import importlib.util
import json
import os
import re
import shlex
import socket
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import paramiko
except ImportError:
    paramiko = None


SKILL_DIR = Path(__file__).resolve().parent.parent
FORBIDDEN_SECRET_KEYS = {
    "password",
    "passphrase",
    "private_key",
    "private_key_body",
    "secret",
    "token",
}


def load_profile_manager() -> Any:
    path = Path(__file__).resolve().parent / "profile_manager.py"
    spec = importlib.util.spec_from_file_location("build_client_profiles", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"ERROR: cannot load Profile manager: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PM = load_profile_manager()


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    timed_out: bool
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def fail(message: str) -> "None":
    raise SystemExit(f"ERROR: {message}")


def require_paramiko() -> Any:
    if paramiko is None:
        fail(
            "paramiko is required; ask before installing it with "
            "'python -m pip install paramiko'"
        )
    return paramiko


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reject_embedded_secrets(value: Any, location: str = "profile") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in FORBIDDEN_SECRET_KEYS:
                fail(f"embedded secret field is forbidden at {location}.{key}")
            reject_embedded_secrets(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_embedded_secrets(child, f"{location}[{index}]")
    elif isinstance(value, str) and "BEGIN PRIVATE KEY" in value:
        fail(f"embedded private-key material is forbidden at {location}")


def require_mapping(profile: dict[str, Any], name: str) -> dict[str, Any]:
    value = profile.get(name)
    if not isinstance(value, dict):
        fail(f"Profile field '{name}' must be an object")
    return value


def require_positive_int(mapping: dict[str, Any], name: str) -> int:
    value = mapping.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        fail(f"Profile field '{name}' must be a positive integer")
    return value


def resolve_profile_reference(
    profile: dict[str, Any], reference: str, field: str
) -> Path:
    if not isinstance(reference, str) or not reference.strip():
        fail(f"Profile field '{field}' must be a nonempty path reference")
    try:
        environment_path = Path(profile["_environment_path"])
        return PM.resolve_protected_path(
            environment_path.parent,
            reference,
            binding_id=profile["_binding_id"],
            fingerprint=profile["_fingerprint"],
        )
    except (KeyError, PM.ProfileError) as exc:
        fail(f"Profile field '{field}' is not a valid protected Profile reference: {exc}")


def load_profile(path: Path) -> dict[str, Any]:
    try:
        environment = PM.require_valid_environment(path)
        profile = PM.to_ssh_profile(environment, path)
    except PM.ProfileError as exc:
        fail(str(exc))
    reject_embedded_secrets(profile)

    for field in (
        "profile_name",
        "kind",
        "host",
        "port",
        "user",
        "platform",
        "queue_resource",
        "vm_identity",
    ):
        if field not in profile:
            fail(f"Profile is missing required field '{field}'")
    for field in (
        "profile_name",
        "host",
        "user",
        "platform",
        "queue_resource",
        "vm_identity",
    ):
        if not isinstance(profile[field], str) or not profile[field].strip():
            fail(f"Profile field '{field}' must be a nonempty string")
    if profile["kind"] != "ssh":
        fail(
            "this build-client adapter supports only kind='ssh'; "
            "Windows and VMware Profiles require RemoteX"
        )
    require_positive_int(profile, "port")

    credential = require_mapping(profile, "credential")
    if credential.get("source") != "identity-file":
        fail("SSH Profile credential.source must be 'identity-file'")
    resolve_profile_reference(profile, credential.get("identity_file"), "credential.identity_file")

    host_key = require_mapping(profile, "host_key")
    if host_key.get("policy") != "managed" or host_key.get("strict_checking") is not True:
        fail("SSH Profile requires managed host key and strict_checking=true")
    expected = host_key.get("expected_sha256")
    if not isinstance(expected, str) or not expected.startswith("SHA256:"):
        fail("host_key.expected_sha256 must be an OpenSSH SHA-256 fingerprint")
    resolve_profile_reference(profile, host_key.get("known_hosts_file"), "host_key.known_hosts_file")

    identity = require_mapping(profile, "identity")
    if identity.get("type") != "ssh-host-key-and-machine-id":
        fail("SSH Profile identity.type must be 'ssh-host-key-and-machine-id'")
    expected_machine_id = identity.get("expected_machine_id_sha256", "")
    if expected_machine_id and not re.fullmatch(r"[0-9a-f]{64}", expected_machine_id):
        fail("identity.expected_machine_id_sha256 must be empty or 64 lowercase hex characters")

    capabilities = require_mapping(profile, "capabilities")
    for capability in ("read", "execute", "copy", "reboot", "power", "snapshot"):
        if not isinstance(capabilities.get(capability), bool):
            fail(f"capabilities.{capability} must be boolean")
    if (
        not capabilities["read"]
        or not capabilities["execute"]
        or not capabilities["copy"]
    ):
        fail("build Profile requires read=true, execute=true, and copy=true")
    if capabilities["reboot"] or capabilities["power"] or capabilities["snapshot"]:
        fail("SSH build Profile must not declare reboot, power, or snapshot capability")

    timeouts = require_mapping(profile, "timeouts")
    for field in (
        "connect_seconds",
        "preflight_seconds",
        "command_seconds",
        "queue_wait_seconds",
    ):
        require_positive_int(timeouts, field)
    receipt = require_mapping(profile, "receipt")
    require_positive_int(receipt, "max_age_seconds")
    return profile


def profile_paths(profile: dict[str, Any]) -> tuple[Path, Path]:
    private_key = resolve_profile_reference(
        profile, profile["credential"]["identity_file"], "credential.identity_file"
    )
    known_hosts = resolve_profile_reference(
        profile, profile["host_key"]["known_hosts_file"], "host_key.known_hosts_file"
    )
    return private_key, known_hosts


def profile_sha256(profile: dict[str, Any]) -> str:
    stored = profile.get("_environment_sha256")
    if isinstance(stored, str) and stored:
        return stored
    return canonical_sha256({key: value for key, value in profile.items() if not key.startswith("_")})


def profile_status(profile: dict[str, Any], profile_path: Path) -> dict[str, Any]:
    private_key, known_hosts = profile_paths(profile)
    checks = {
        "configuration": True,
        "credentialReference": private_key.is_file(),
        "managedHostKey": known_hosts.is_file(),
        "identityContract": bool(profile["identity"].get("expected_machine_id_sha256")),
        "capabilityContract": True,
    }
    ready = all(checks.values())
    return {
        "ok": ready,
        "overallStatus": "READY" if ready else "SETUP_REQUIRED",
        "selectedProfileReady": ready,
        "profile": profile["profile_name"],
        "profileSha256": profile_sha256(profile),
        "profileFile": str(profile_path),
        "queueResource": profile["queue_resource"],
        "vmIdentity": profile["vm_identity"],
        "checks": checks,
    }


def fingerprint(key: Any) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded}"


def verify_expected_host_key(profile: dict[str, Any], key: Any) -> str:
    actual = fingerprint(key)
    expected = profile["host_key"]["expected_sha256"]
    if actual != expected:
        fail(f"server host key changed: expected {expected}, got {actual}")
    return actual


def probe_server_key(profile: dict[str, Any]) -> Any:
    pm = require_paramiko()
    timeout = profile["timeouts"]["connect_seconds"]
    try:
        sock = socket.create_connection(
            (profile["host"], profile["port"]), timeout=timeout
        )
    except OSError as exc:
        fail(f"SSH host-key probe failed: {exc}")
    transport = pm.Transport(sock)
    try:
        transport.start_client(timeout=timeout)
        key = transport.get_remote_server_key()
        verify_expected_host_key(profile, key)
        return key
    except (OSError, pm.SSHException) as exc:
        fail(f"SSH host-key probe failed: {exc}")
    finally:
        transport.close()


def load_private_key(path: Path) -> Any:
    pm = require_paramiko()
    if not path.is_file():
        fail(
            "SSH setup is required; run "
            f"python {shlex.quote(str(Path(__file__).resolve()))} setup "
            "in an interactive terminal"
        )
    loaders = (pm.RSAKey, pm.Ed25519Key, pm.ECDSAKey)
    errors: list[str] = []
    for loader in loaders:
        try:
            return loader.from_private_key_file(str(path))
        except (OSError, pm.SSHException) as exc:
            errors.append(str(exc))
    fail(f"cannot load project SSH key: {'; '.join(errors)}")


def connect_with_key(profile: dict[str, Any]) -> Any:
    pm = require_paramiko()
    private_key, known_hosts = profile_paths(profile)
    if not known_hosts.is_file():
        fail("SSH setup is required; managed known_hosts file is missing")
    key = load_private_key(private_key)
    client = pm.SSHClient()
    try:
        client.load_host_keys(str(known_hosts))
        client.set_missing_host_key_policy(pm.RejectPolicy())
        timeout = profile["timeouts"]["connect_seconds"]
        client.connect(
            profile["host"],
            port=profile["port"],
            username=profile["user"],
            pkey=key,
            look_for_keys=False,
            allow_agent=False,
            timeout=timeout,
            auth_timeout=timeout,
            banner_timeout=timeout,
        )
        remote_key = client.get_transport().get_remote_server_key()
        verify_expected_host_key(profile, remote_key)
        return client
    except (OSError, pm.SSHException) as exc:
        client.close()
        fail(f"SSH connection failed: {exc}")


def run_remote(
    client: Any,
    command: str,
    *,
    timeout_seconds: int,
    stdin_text: str | None = None,
    emit: bool = False,
) -> CommandResult:
    stdin, stdout, _stderr = client.exec_command(command)
    channel = stdout.channel
    if stdin_text is not None:
        stdin.write(stdin_text)
        stdin.flush()
    channel.shutdown_write()

    out = bytearray()
    err = bytearray()
    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    exit_code = 124
    while True:
        emitted = False
        while channel.recv_ready():
            chunk = channel.recv(65536)
            out.extend(chunk)
            if emit:
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
            emitted = True
        while channel.recv_stderr_ready():
            chunk = channel.recv_stderr(65536)
            err.extend(chunk)
            if emit:
                sys.stderr.buffer.write(chunk)
                sys.stderr.buffer.flush()
            emitted = True
        if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
            exit_code = channel.recv_exit_status()
            break
        if time.monotonic() >= deadline:
            timed_out = True
            channel.close()
            break
        if not emitted:
            time.sleep(0.05)
    return CommandResult(
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=out.decode("utf-8", errors="replace"),
        stderr=err.decode("utf-8", errors="replace"),
    )


def setup(profile: dict[str, Any]) -> int:
    pm = require_paramiko()
    private_key, known_hosts = profile_paths(profile)
    private_key.parent.mkdir(parents=True, exist_ok=True)

    # Verify the managed host key before asking for or presenting credentials.
    remote_key = probe_server_key(profile)
    if private_key.exists():
        key = load_private_key(private_key)
    else:
        key = pm.RSAKey.generate(bits=3072)
        key.write_private_key_file(str(private_key))
        try:
            private_key.chmod(0o600)
        except OSError:
            pass

    public_key = private_key.with_suffix(private_key.suffix + ".pub")
    public_line = f"{key.get_name()} {key.get_base64()} build-client@codex"
    public_key.write_text(public_line + "\n", encoding="ascii")

    password = getpass.getpass(
        f"Password for {profile['user']}@{profile['host']}: "
    )
    client = pm.SSHClient()
    host_keys = pm.HostKeys()
    host_label = (
        profile["host"]
        if profile["port"] == 22
        else f"[{profile['host']}]:{profile['port']}"
    )
    host_keys.add(host_label, remote_key.get_name(), remote_key)
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    host_keys.save(str(known_hosts))
    client.load_host_keys(str(known_hosts))
    client.set_missing_host_key_policy(pm.RejectPolicy())
    try:
        timeout = profile["timeouts"]["connect_seconds"]
        client.connect(
            profile["host"],
            port=profile["port"],
            username=profile["user"],
            password=password,
            look_for_keys=False,
            allow_agent=False,
            timeout=timeout,
            auth_timeout=timeout,
            banner_timeout=timeout,
        )
        verify_expected_host_key(
            profile, client.get_transport().get_remote_server_key()
        )
        quoted_key = shlex.quote(public_line)
        command = (
            "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; "
            f"grep -qxF -- {quoted_key} ~/.ssh/authorized_keys || "
            f"printf '%s\\n' {quoted_key} >> ~/.ssh/authorized_keys; "
            "chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys"
        )
        result = run_remote(
            client,
            command,
            timeout_seconds=profile["timeouts"]["preflight_seconds"],
        )
        if not result.ok:
            fail(
                "remote key installation failed "
                f"(exitCode={result.exit_code}, timedOut={str(result.timed_out).lower()})"
            )
    except (OSError, pm.AuthenticationException, pm.SSHException) as exc:
        fail(f"SSH setup failed: {exc}")
    finally:
        password = ""
        client.close()

    print("SSH setup completed")
    return 0


PREFLIGHT_COMMAND = r"""
set -eu
printf 'hostname='; hostname
printf 'machine_id='
if [ -r /etc/machine-id ]; then cat /etc/machine-id
elif [ -r /var/lib/dbus/machine-id ]; then cat /var/lib/dbus/machine-id
else exit 31
fi
printf 'os='; uname -s
printf 'kernel='; uname -r
printf 'arch='; uname -m
printf 'uptime_seconds='; awk '{printf "%d\n", $1}' /proc/uptime
printf 'memory_available_mb='; awk '/^MemAvailable:/ {printf "%d\n", $2/1024; found=1} END {if (!found) exit 32}' /proc/meminfo
printf 'root_use_percent='; df -P / | awk 'NR==2 {gsub(/%/, "", $5); print $5}'
""".strip()


def preflight(client: Any, profile: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = profile["timeouts"]["preflight_seconds"]
    bounded_command = (
        f"timeout --signal=TERM --kill-after=5s {timeout_seconds}s "
        f"sh -c {shlex.quote(PREFLIGHT_COMMAND)}"
    )
    result = run_remote(
        client,
        bounded_command,
        timeout_seconds=timeout_seconds + 10,
    )
    if result.exit_code in (124, 137) and not result.timed_out:
        result = CommandResult(
            result.exit_code, True, result.stdout, result.stderr
        )
    if not result.ok:
        detail = result.stderr.strip() or "read-only inventory failed"
        fail(
            f"preflight failed: exitCode={result.exit_code}, "
            f"timedOut={str(result.timed_out).lower()}, stderr={detail}"
        )
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value.strip()
    required = {
        "hostname",
        "machine_id",
        "os",
        "kernel",
        "arch",
        "uptime_seconds",
        "memory_available_mb",
        "root_use_percent",
    }
    missing = sorted(required - values.keys())
    if missing:
        fail(f"preflight output is incomplete: missing {', '.join(missing)}")
    host_key = fingerprint(client.get_transport().get_remote_server_key())
    verify_expected_host_key(profile, client.get_transport().get_remote_server_key())
    machine_id_sha256 = hashlib.sha256(values["machine_id"].encode("utf-8")).hexdigest()
    expected_machine_id = profile["identity"].get("expected_machine_id_sha256", "")
    if expected_machine_id and machine_id_sha256 != expected_machine_id:
        fail(
            "machine identity changed: expected "
            f"{expected_machine_id}, got {machine_id_sha256}"
        )
    return {
        "ok": True,
        "exitCode": result.exit_code,
        "timedOut": result.timed_out,
        "identity": {
            "hostKeySha256": host_key,
            "machineIdSha256": machine_id_sha256,
            "hostnameSha256": hashlib.sha256(
                values["hostname"].encode("utf-8")
            ).hexdigest(),
        },
        "inventory": parse_inventory(values),
    }


def parse_inventory(values: dict[str, str]) -> dict[str, Any]:
    try:
        uptime_seconds = int(values["uptime_seconds"])
        memory_available_mb = int(values["memory_available_mb"])
        root_use_percent = int(values["root_use_percent"])
    except ValueError as exc:
        fail(f"preflight returned a nonnumeric resource value: {exc}")
    if uptime_seconds < 0 or memory_available_mb < 0:
        fail("preflight returned a negative uptime or memory value")
    if not 0 <= root_use_percent <= 100:
        fail("preflight returned root filesystem usage outside 0..100")
    return {
        "os": values["os"],
        "kernel": values["kernel"],
        "architecture": values["arch"],
        "uptimeSeconds": uptime_seconds,
        "memoryAvailableMb": memory_available_mb,
        "rootUsePercent": root_use_percent,
    }


def local_queue_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        base = Path.home() / "AppData" / "Local"
    return base / "Codex" / "build-client" / "queues"


def local_queue_status(profile: dict[str, Any]) -> dict[str, Any]:
    queue_hash = hashlib.sha256(profile["queue_resource"].encode("utf-8")).hexdigest()
    claim_dir = local_queue_root() / f"{queue_hash}.claim"
    owner_file = claim_dir / "owner.json"
    owner: dict[str, Any] | None = None
    if owner_file.is_file():
        try:
            value = json.loads(owner_file.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                owner = value
        except (OSError, json.JSONDecodeError):
            owner = {"unreadable": True}
    return {
        "resource": profile["queue_resource"],
        "claimKeySha256": queue_hash,
        "claimPath": str(claim_dir),
        "claimed": claim_dir.is_dir(),
        "owner": owner,
    }


def claim_local_queue(
    profile: dict[str, Any], run_id: str, wait_seconds: int | None = None
) -> dict[str, Any]:
    root = local_queue_root()
    root.mkdir(parents=True, exist_ok=True)
    status = local_queue_status(profile)
    claim_dir = Path(status["claimPath"])
    owner_file = claim_dir / "owner.json"
    timeout = wait_seconds or profile["timeouts"]["queue_wait_seconds"]
    deadline = time.monotonic() + timeout
    print(
        f"==> HOST_QUEUE_WAIT resource={profile['queue_resource']} "
        f"timeout={timeout}s requester={run_id}"
    )
    while True:
        try:
            claim_dir.mkdir()
            owner = {
                "runId": run_id,
                "pid": os.getpid(),
                "queueResource": profile["queue_resource"],
                "claimedAt": datetime.now(timezone.utc).isoformat(),
            }
            owner_file.write_text(
                json.dumps(owner, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(
                f"==> HOST_QUEUE_CLAIMED resource={profile['queue_resource']} "
                f"requester={run_id}"
            )
            return {**status, "claimed": True, "owner": owner}
        except FileExistsError:
            if time.monotonic() >= deadline:
                current = local_queue_status(profile)
                fail(
                    f"host queue claim timed out for {profile['queue_resource']}; "
                    f"owner={current['owner']}; do not steal or delete the claim"
                )
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        except OSError as exc:
            try:
                if owner_file.exists():
                    owner_file.unlink()
                claim_dir.rmdir()
            except OSError:
                pass
            fail(f"host queue claim failed: {exc}")


def release_local_queue(profile: dict[str, Any], run_id: str) -> dict[str, Any]:
    status = local_queue_status(profile)
    claim_dir = Path(status["claimPath"])
    owner_file = claim_dir / "owner.json"
    if not claim_dir.is_dir() or not owner_file.is_file():
        return {"released": False, "error": "claim or owner file is missing"}
    try:
        owner = json.loads(owner_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"released": False, "error": f"cannot read queue owner: {exc}"}
    if owner.get("runId") != run_id:
        return {
            "released": False,
            "error": "queue owner does not match requester; claim was not changed",
            "owner": owner,
        }
    try:
        owner_file.unlink()
        claim_dir.rmdir()
    except OSError as exc:
        return {"released": False, "error": str(exc)}
    print(
        f"==> HOST_QUEUE_RELEASED resource={profile['queue_resource']} "
        f"requester={run_id}"
    )
    return {"released": True}


def check(profile: dict[str, Any], profile_path: Path) -> int:
    status = profile_status(profile, profile_path)
    if not status["selectedProfileReady"]:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2
    client = connect_with_key(profile)
    try:
        inventory = preflight(client, profile)
    finally:
        client.close()
    output = {
        **status,
        "ok": True,
        "overallStatus": "READY",
        "selectedProfileReady": True,
        "connection": inventory,
    }
    print("connected")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def claim_queue(client: Any, profile: dict[str, Any], run_id: str) -> dict[str, Any]:
    queue_hash = hashlib.sha256(
        profile["queue_resource"].encode("utf-8")
    ).hexdigest()
    command = (
        "set -eu; umask 077; base=\"$HOME/.cache/build-client/queues\"; "
        "mkdir -p -- \"$base\"; "
        f"claim=\"$base/{queue_hash}.claim\"; "
        "if mkdir -- \"$claim\" 2>/dev/null; then "
        f"printf '%s\\n' {shlex.quote(run_id)} >\"$claim/owner\"; "
        "printf 'claimed\\n'; exit 0; fi; "
        "printf 'busy\\n' >&2; exit 75"
    )
    wait_seconds = profile["timeouts"]["queue_wait_seconds"]
    deadline = time.monotonic() + wait_seconds
    print(
        f"==> QUEUE_WAIT resource={profile['queue_resource']} "
        f"timeout={wait_seconds}s requester={run_id}"
    )
    while True:
        result = run_remote(
            client,
            command,
            timeout_seconds=profile["timeouts"]["preflight_seconds"],
        )
        if result.ok:
            print(
                f"==> QUEUE_CLAIMED resource={profile['queue_resource']} "
                f"requester={run_id}"
            )
            return {
                "resource": profile["queue_resource"],
                "owner": run_id,
                "claimKeySha256": queue_hash,
            }
        if result.exit_code != 75 or result.timed_out:
            fail(
                "queue claim failed: "
                f"exitCode={result.exit_code}, timedOut={str(result.timed_out).lower()}"
            )
        if time.monotonic() >= deadline:
            fail(
                f"queue claim timed out for {profile['queue_resource']}; "
                "do not steal or release another requester's claim"
            )
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))


def release_queue(client: Any, profile: dict[str, Any], run_id: str) -> dict[str, Any]:
    queue_hash = hashlib.sha256(
        profile["queue_resource"].encode("utf-8")
    ).hexdigest()
    command = (
        "set -eu; "
        f"claim=\"$HOME/.cache/build-client/queues/{queue_hash}.claim\"; "
        "owner=\"$claim/owner\"; "
        "[ -f \"$owner\" ] || exit 76; "
        f"[ \"$(cat \"$owner\")\" = {shlex.quote(run_id)} ] || exit 77; "
        "rm -f -- \"$owner\"; rmdir -- \"$claim\"; printf 'released\\n'"
    )
    result = run_remote(
        client,
        command,
        timeout_seconds=profile["timeouts"]["preflight_seconds"],
    )
    released = result.ok
    if released:
        print(
            f"==> QUEUE_RELEASED resource={profile['queue_resource']} "
            f"requester={run_id}"
        )
    return {
        "released": released,
        "exitCode": result.exit_code,
        "timedOut": result.timed_out,
    }


def make_receipt(
    profile: dict[str, Any],
    run_id: str,
    preflight_result: dict[str, Any],
    *,
    action_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipt = {
        "status": "PASS",
        "runId": run_id,
        "requester": run_id,
        "profile": profile["profile_name"],
        "profileSha256": profile_sha256(profile),
        "queueResource": profile["queue_resource"],
        "queueOwner": run_id,
        "identity": preflight_result["identity"],
        "capabilities": profile["capabilities"],
        "preflight": {
            "ok": preflight_result["ok"],
            "exitCode": preflight_result["exitCode"],
            "timedOut": preflight_result["timedOut"],
            "inventory": preflight_result["inventory"],
        },
        "issuedAt": datetime.now(timezone.utc).isoformat(),
        "maxAgeSeconds": profile["receipt"]["max_age_seconds"],
    }
    if action_binding is not None:
        receipt["actionBinding"] = action_binding
    receipt["receiptSha256"] = canonical_sha256(receipt)
    return receipt


def parse_artifact_readbacks(stdout: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"^==> ARTIFACT_READBACK path=(\S+) size=(\d+) "
        r"sha256=([0-9a-f]{64}) mtime=(\d+)$"
    )
    artifacts: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        match = pattern.match(line.strip())
        if match:
            artifacts.append(
                {
                    "path": match.group(1),
                    "size": int(match.group(2)),
                    "sha256": match.group(3),
                    "mtimeEpoch": int(match.group(4)),
                }
            )
    return artifacts


def build(
    profile: dict[str, Any],
    recipe: dict[str, Any],
    recipe_path: Path,
    scope: str,
    *,
    host_queue_context: dict[str, Any] | None = None,
) -> int:
    scope_contract = recipe.get("scopes", {}).get(scope)
    if not isinstance(scope_contract, dict):
        fail(f"scope '{scope}' is not declared by the selected build recipe")
    if scope_contract.get("execution") != "remote-non-gui":
        fail("the SSH build adapter accepts only remote-non-gui scopes")
    try:
        provider_path = PM.require_provider(recipe, recipe_path)
    except PM.ProfileError as exc:
        fail(f"invalid build provider reference: {exc}")
    script = provider_path.read_text(encoding="utf-8")
    recipe_sha256 = PM.canonical_sha256(recipe)
    provider_sha256 = hashlib.sha256(script.encode("utf-8")).hexdigest()
    run_id = (
        host_queue_context["runId"]
        if host_queue_context is not None
        else str(uuid.uuid4())
    )
    owns_host_queue = host_queue_context is None
    private_key, known_hosts = profile_paths(profile)
    if not private_key.is_file() or not known_hosts.is_file():
        fail("selectedProfileReady=false; run profile-check and complete setup")
    status = profile_status(profile, Path(profile["_environment_path"]))
    if not status["selectedProfileReady"]:
        fail("selectedProfileReady=false; complete VMware/SSH initialization first")
    client: Any | None = None
    action: CommandResult | None = None
    readback: dict[str, Any] | None = None
    readback_error: str | None = None
    receipt: dict[str, Any] | None = None
    before: dict[str, Any] | None = None
    queue_claim: dict[str, Any] | None = None
    queue_release: dict[str, Any] | None = None
    host_queue_claim: dict[str, Any] | None = None
    host_queue_release: dict[str, Any] | None = None
    pending_error: BaseException | None = None
    try:
        host_queue_claim = (
            claim_local_queue(profile, run_id)
            if owns_host_queue
            else host_queue_context["claim"]
        )
        client = connect_with_key(profile)
        queue_claim = claim_queue(client, profile, run_id)
        issued_monotonic = time.monotonic()
        before = preflight(client, profile)
        receipt = make_receipt(
            profile,
            run_id,
            before,
            action_binding={
                "scope": scope,
                "recipeId": recipe["recipeId"],
                "recipeSha256": recipe_sha256,
                "providerSha256": provider_sha256,
                "expectedArtifactCount": scope_contract["expectedArtifactCount"],
            },
        )
        age = time.monotonic() - issued_monotonic
        if age > profile["receipt"]["max_age_seconds"]:
            fail("preflight receipt became stale before admission")
        print("==> ADMIT fresh exact receipt")
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        command_seconds = profile["timeouts"]["command_seconds"]
        command = (
            f"timeout --signal=TERM --kill-after=30s {command_seconds}s "
            f"bash -s -- {shlex.quote(scope)}"
        )
        action = run_remote(
            client,
            command,
            timeout_seconds=command_seconds + 45,
            stdin_text=script,
            emit=True,
        )
        if action.exit_code in (124, 137) and not action.timed_out:
            action = CommandResult(
                action.exit_code, True, action.stdout, action.stderr
            )
        try:
            readback = preflight(client, profile)
        except SystemExit as exc:
            readback_error = str(exc)
    except BaseException as exc:
        pending_error = exc
    finally:
        if queue_claim is not None and client is not None:
            try:
                queue_release = release_queue(client, profile, run_id)
            except BaseException as exc:
                queue_release = {
                    "released": False,
                    "exitCode": None,
                    "timedOut": None,
                    "error": str(exc),
                }
        if client is not None:
            client.close()
        if host_queue_claim is not None and owns_host_queue:
            host_queue_release = release_local_queue(profile, run_id)
        elif host_queue_claim is not None:
            host_queue_release = {
                "released": True,
                "deferredToVmLifecycle": True,
                "owner": run_id,
            }

    if pending_error is not None:
        if queue_release is not None and not queue_release["released"]:
            print(
                "ERROR: queue release also failed; manual owner-safe recovery is required",
                file=sys.stderr,
            )
        if host_queue_release is not None and not host_queue_release["released"]:
            print(
                "ERROR: host queue release failed; manual owner-safe recovery is required",
                file=sys.stderr,
            )
        raise pending_error
    if action is None:
        fail("remote action did not start")
    if (
        before is None
        or receipt is None
        or queue_claim is None
        or host_queue_claim is None
    ):
        fail("admission evidence is incomplete")
    identity_exact = (
        readback is not None and before["identity"] == readback["identity"]
    )
    artifacts = parse_artifact_readbacks(action.stdout)
    expected_artifact_count = scope_contract["expectedArtifactCount"]
    artifact_evidence_ok = len(artifacts) >= expected_artifact_count
    audit = {
        "runId": run_id,
        "profile": profile["profile_name"],
        "profileSha256": profile_sha256(profile),
        "recipe": recipe["recipeId"],
        "recipeSha256": recipe_sha256,
        "providerSha256": provider_sha256,
        "queueResource": profile["queue_resource"],
        "queueClaim": queue_claim,
        "queueRelease": queue_release,
        "hostQueueClaim": host_queue_claim,
        "hostQueueRelease": host_queue_release,
        "receiptSha256": receipt["receiptSha256"],
        "action": {
            "scope": scope,
            "ok": action.ok,
            "exitCode": action.exit_code,
            "timedOut": action.timed_out,
            "artifactReadback": artifacts,
            "expectedArtifactCount": expected_artifact_count,
            "artifactEvidenceOk": artifact_evidence_ok,
        },
        "readback": {
            "ok": readback is not None,
            "identityExact": identity_exact,
            "result": readback,
            "error": readback_error,
        },
        "terminalState": (
            "PASS"
            if action.ok
            and identity_exact
            and artifact_evidence_ok
            and queue_release is not None
            and queue_release["released"]
            and host_queue_release is not None
            and host_queue_release["released"]
            else "FAIL"
        ),
    }
    print("==> AUDIT")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if not action.ok:
        return action.exit_code or 1
    if not identity_exact:
        fail("post-action identity readback is missing or does not match the receipt")
    if not artifact_evidence_ok:
        fail("required artifact hash/metadata readback is missing")
    if queue_release is None or not queue_release["released"]:
        fail("queue release failed; do not attempt to release another requester owner")
    if host_queue_release is None or not host_queue_release["released"]:
        fail("host queue release failed; do not delete another requester's claim")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, help="explicit environment Profile or directory")
    parser.add_argument("--recipe", type=Path, help="explicit build recipe")
    parser.add_argument("--binding-id", help="saved Profile binding ID")
    parser.add_argument("--project-root", type=Path, help="project registry root")
    parser.add_argument("--registry-root", type=Path, help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("profile-check", help="validate the Profile without network access")
    subparsers.add_parser("setup", help="install the project-specific SSH key")
    subparsers.add_parser("check", help="run the five read-only first-contact gates")
    build_parser = subparsers.add_parser("build", help="run the six-gate remote action")
    build_parser.add_argument("scope", help="exact non-GUI scope declared by the selected recipe")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        selection = PM.resolve_selection(
            profile=args.profile,
            recipe=args.recipe,
            binding_id=args.binding_id,
            project_root=args.project_root,
            registry_root=args.registry_root,
        )
    except PM.ProfileError as exc:
        fail(str(exc))
    profile_path = selection.environment_path
    profile = load_profile(profile_path)
    if args.command == "profile-check":
        status = profile_status(profile, profile_path)
        provider_path = PM.require_provider(selection.recipe, selection.recipe_path)
        status["recipe"] = selection.recipe["recipeId"]
        status["recipeSha256"] = PM.canonical_sha256(selection.recipe)
        status["providerSha256"] = hashlib.sha256(provider_path.read_bytes()).hexdigest()
        status["scopes"] = selection.recipe["scopes"]
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status["selectedProfileReady"] else 2
    if args.command == "setup":
        return setup(profile)
    if args.command == "check":
        return check(profile, profile_path)
    return build(profile, selection.recipe, selection.recipe_path, args.scope)


if __name__ == "__main__":
    raise SystemExit(main())

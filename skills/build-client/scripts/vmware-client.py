#!/usr/bin/env python3
"""Operate the Linux build VM through a paired VMware/SSH Profile contract."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent.parent


def load_remote_client() -> Any:
    path = Path(__file__).resolve().parent / "remote-client.py"
    spec = importlib.util.spec_from_file_location("build_client_remote", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"ERROR: cannot load SSH adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RC = load_remote_client()
PM = RC.PM


def fail(message: str) -> "None":
    raise SystemExit(f"ERROR: {message}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"Profile not found: {path}")
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot parse Profile {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"Profile root must be an object: {path}")
    RC.reject_embedded_secrets(value)
    return value


def require_text(mapping: dict[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        fail(f"Profile field '{field}' must be a nonempty string")
    return value


def require_positive_int(mapping: dict[str, Any], field: str) -> int:
    value = mapping.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        fail(f"Profile field '{field}' must be a positive integer")
    return value


def normalize_uuid(value: str) -> str:
    normalized = re.sub(r"[^0-9a-f]", "", value.lower())
    if len(normalized) != 32:
        fail(f"invalid VMware UUID: {value}")
    return normalized


def normalize_mac(value: str) -> str:
    normalized = re.sub(r"[^0-9a-f]", "", value.lower())
    if len(normalized) != 12:
        fail(f"invalid VMware MAC address: {value}")
    return ":".join(normalized[index : index + 2] for index in range(0, 12, 2))


def normalized_path(value: str | Path) -> str:
    return str(Path(value).resolve()).replace("/", "\\").casefold()


def parse_vmx(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        fail(f"cannot read VMX file {path}: {exc}")
    values: dict[str, str] = {}
    wanted = {
        "displayName": "displayName",
        "guestOS": "guestOS",
        "uuid.bios": "uuid.bios",
        "ethernet0.address": "ethernet0.address",
        "ethernet0.generatedAddress": "ethernet0.generatedAddress",
    }
    for line in text.splitlines():
        match = re.match(r'^\s*([^=]+?)\s*=\s*"(.*)"\s*$', line)
        if match:
            key = match.group(1).strip()
            if key in wanted:
                values[wanted[key]] = match.group(2)
    mac = values.get("ethernet0.address") or values.get("ethernet0.generatedAddress")
    for field in ("displayName", "guestOS", "uuid.bios"):
        if field not in values:
            fail(f"VMX identity field is missing: {field}")
    if not mac:
        fail("VMX identity field is missing: ethernet0 address")
    return {
        "displayName": values["displayName"],
        "guestOS": values["guestOS"],
        "uuid": normalize_uuid(values["uuid.bios"]),
        "mac": normalize_mac(mac),
    }


def load_vmware_profile(path: Path) -> dict[str, Any]:
    try:
        environment = PM.require_valid_environment(path)
        profile = PM.to_vmware_profile(environment, path)
    except PM.ProfileError as exc:
        fail(str(exc))
    for field in (
        "profile_name",
        "kind",
        "management_host",
        "platform",
        "queue_resource",
        "vm_identity",
        "vmrun_path",
        "workstation_gui_path",
    ):
        require_text(profile, field)
    if profile["kind"] != "vmware-workstation":
        fail("VMware Profile kind must be 'vmware-workstation'")
    if profile["management_host"] != "localhost" or profile["platform"] != "windows":
        fail("VMware Workstation Profile must target the local Windows host")
    credential = RC.require_mapping(profile, "credential")
    if credential.get("source") != "current-windows-user":
        fail("local VMware Workstation must use credential.source='current-windows-user'")
    vm = RC.require_mapping(profile, "vm")
    for field in (
        "display_name",
        "vmx_path",
        "guest_os",
        "expected_uuid",
        "expected_mac",
        "expected_ipv4",
    ):
        require_text(vm, field)
    normalize_uuid(vm["expected_uuid"])
    normalize_mac(vm["expected_mac"])
    capabilities = RC.require_mapping(profile, "capabilities")
    expected_capabilities = {
        "status": True,
        "start": True,
        "gui_console": True,
        "soft_stop": True,
        "soft_restart": True,
        "hard_stop": False,
        "snapshot": False,
    }
    if capabilities != expected_capabilities:
        fail(
            "VMware capability matrix must allow status/start/gui_console/soft_stop/soft_restart only"
        )
    timeouts = RC.require_mapping(profile, "timeouts")
    for field in (
        "command_seconds",
        "power_on_seconds",
        "power_off_seconds",
        "ssh_ready_seconds",
        "queue_wait_seconds",
    ):
        require_positive_int(timeouts, field)
    receipt = RC.require_mapping(profile, "receipt")
    require_positive_int(receipt, "max_age_seconds")
    return profile


def vmx_identity(profile: dict[str, Any]) -> dict[str, Any]:
    vmrun_path = Path(profile["vmrun_path"])
    workstation_gui_path = Path(profile["workstation_gui_path"])
    vmx_path = Path(profile["vm"]["vmx_path"])
    if not vmrun_path.is_file():
        fail(f"vmrun executable not found: {vmrun_path}")
    if not workstation_gui_path.is_file():
        fail(f"VMware Workstation GUI executable not found: {workstation_gui_path}")
    if not vmx_path.is_file():
        fail(f"VMX file not found: {vmx_path}")
    actual = parse_vmx(vmx_path)
    expected = profile["vm"]
    checks = {
        "displayName": actual["displayName"] == expected["display_name"],
        "guestOs": actual["guestOS"] == expected["guest_os"],
        "uuid": actual["uuid"] == normalize_uuid(expected["expected_uuid"]),
        "mac": actual["mac"] == normalize_mac(expected["expected_mac"]),
    }
    if not all(checks.values()):
        fail(f"VMX composite identity mismatch: {checks}")
    return {
        "vmIdentity": profile["vm_identity"],
        "displayName": actual["displayName"],
        "guestOs": actual["guestOS"],
        "uuidSha256": RC.canonical_sha256(actual["uuid"]),
        "mac": actual["mac"],
        "vmxPath": str(vmx_path.resolve()),
        "checks": checks,
    }


def paired_status(
    vmware: dict[str, Any],
    vmware_path: Path,
    ssh: dict[str, Any],
    ssh_path: Path,
) -> dict[str, Any]:
    vmx = vmx_identity(vmware)
    ssh_private_key, ssh_known_hosts = RC.profile_paths(ssh)
    checks = {
        "configuration": True,
        "sameQueueResource": vmware["queue_resource"] == ssh["queue_resource"],
        "sameVmIdentity": vmware["vm_identity"] == ssh["vm_identity"],
        "expectedIpMatchesSsh": vmware["vm"]["expected_ipv4"] == ssh["host"],
        "credentialReference": ssh_private_key.is_file(),
        "managedHostKey": ssh_known_hosts.is_file(),
        "machineIdentityPinned": bool(
            ssh["identity"].get("expected_machine_id_sha256")
        ),
        "vmxIdentity": all(vmx["checks"].values()),
        "capabilityContract": True,
    }
    initialization_ready = all(
        value for key, value in checks.items() if key != "machineIdentityPinned"
    )
    ready = all(checks.values())
    return {
        "ok": ready,
        "overallStatus": "READY" if ready else (
            "INITIALIZATION_REQUIRED" if initialization_ready else "SETUP_REQUIRED"
        ),
        "selectedProfileReady": ready,
        "initializationReady": initialization_ready,
        "profiles": {
            "vmware": vmware["profile_name"],
            "ssh": ssh["profile_name"],
        },
        "profileFiles": {
            "vmware": str(vmware_path),
            "ssh": str(ssh_path),
        },
        "profileSha256": {
            "vmware": RC.profile_sha256(vmware),
            "ssh": RC.profile_sha256(ssh),
        },
        "queueResource": vmware["queue_resource"],
        "vmIdentity": vmware["vm_identity"],
        "checks": checks,
        "vmxIdentity": vmx,
    }


def run_vmrun(profile: dict[str, Any], *arguments: str) -> subprocess.CompletedProcess[str]:
    command = [profile["vmrun_path"], "-T", "ws", *arguments]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=profile["timeouts"]["command_seconds"],
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail(f"vmrun invocation failed: {exc}")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        fail(f"vmrun failed: exitCode={result.returncode}, detail={detail}")
    return result


def power_status(profile: dict[str, Any]) -> dict[str, Any]:
    result = run_vmrun(profile, "list")
    expected = normalized_path(profile["vm"]["vmx_path"])
    running_paths: list[str] = []
    for line in result.stdout.splitlines():
        candidate = line.strip()
        if candidate.lower().startswith("total running vms:") or not candidate:
            continue
        running_paths.append(str(Path(candidate).resolve()))
    matches = [path for path in running_paths if normalized_path(path) == expected]
    if len(matches) > 1:
        fail("vmrun listed the target VM more than once")
    return {
        "running": len(matches) == 1,
        "state": "running" if matches else "stopped",
        "targetVmx": str(Path(profile["vm"]["vmx_path"]).resolve()),
        "runningVmCount": len(running_paths),
    }


def ssh_tcp_reachable(ssh: dict[str, Any], timeout_seconds: float = 1.0) -> bool:
    try:
        connection = socket.create_connection(
            (ssh["host"], ssh["port"]), timeout=timeout_seconds
        )
    except OSError:
        return False
    connection.close()
    return True


def require_power_context_consistency(
    power: dict[str, Any], ssh: dict[str, Any]
) -> dict[str, Any]:
    ssh_reachable = ssh_tcp_reachable(ssh)
    if not power["running"] and ssh_reachable:
        fail(
            "vmrun reports the target stopped while its configured SSH endpoint is reachable; "
            "run vmrun in the same Windows logon context as VMware Workstation and do not "
            "perform a power action from this ambiguous context"
        )
    return {"vmrunState": power["state"], "sshTcpReachable": ssh_reachable}


def wait_for_power(profile: dict[str, Any], running: bool) -> dict[str, Any]:
    field = "power_on_seconds" if running else "power_off_seconds"
    deadline = time.monotonic() + profile["timeouts"][field]
    while True:
        status = power_status(profile)
        if status["running"] is running:
            return status
        if time.monotonic() >= deadline:
            fail(f"VM power readback timed out waiting for {'running' if running else 'stopped'}")
        time.sleep(2)


def start_vm(profile: dict[str, Any]) -> dict[str, Any]:
    before = power_status(profile)
    if not before["running"]:
        run_vmrun(profile, "start", profile["vm"]["vmx_path"], "nogui")
    return wait_for_power(profile, True)


def stop_vm_soft(profile: dict[str, Any]) -> dict[str, Any]:
    before = power_status(profile)
    if before["running"]:
        run_vmrun(profile, "stop", profile["vm"]["vmx_path"], "soft")
    return wait_for_power(profile, False)


def wait_for_ssh(ssh: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error = "SSH not attempted"
    while True:
        client = None
        try:
            client = RC.connect_with_key(ssh)
            return RC.preflight(client, ssh)
        except SystemExit as exc:
            last_error = str(exc)
        finally:
            if client is not None:
                client.close()
        if time.monotonic() >= deadline:
            fail(f"SSH readiness timed out: {last_error}")
        time.sleep(2)


def pin_machine_identity(
    ssh_path: Path, ssh: dict[str, Any], machine_id_sha256: str
) -> dict[str, Any]:
    current = ssh["identity"].get("expected_machine_id_sha256", "")
    if current and current != machine_id_sha256:
        fail(f"refusing to replace pinned machine identity {current}")
    if current == machine_id_sha256:
        return ssh
    try:
        environment = PM.pin_machine_identity(ssh_path, machine_id_sha256)
        return PM.to_ssh_profile(environment, ssh_path)
    except PM.ProfileError as exc:
        fail(str(exc))


def power_action(
    action: str,
    vmware: dict[str, Any],
    vmware_path: Path,
    ssh: dict[str, Any],
    ssh_path: Path,
) -> int:
    status = paired_status(vmware, vmware_path, ssh, ssh_path)
    if not status["selectedProfileReady"]:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2
    run_id = str(uuid.uuid4())
    claim = RC.claim_local_queue(vmware, run_id)
    release: dict[str, Any] | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    pending: BaseException | None = None
    try:
        vmx_identity(vmware)
        before = power_status(vmware)
        require_power_context_consistency(before, ssh)
        if action == "start":
            after = start_vm(vmware)
            wait_for_ssh(ssh, vmware["timeouts"]["ssh_ready_seconds"])
        elif action == "stop":
            after = stop_vm_soft(vmware)
        elif action == "restart":
            if not before["running"]:
                fail("soft restart requires the VM to be running")
            stop_vm_soft(vmware)
            start_vm(vmware)
            wait_for_ssh(ssh, vmware["timeouts"]["ssh_ready_seconds"])
            after = power_status(vmware)
        else:
            fail(f"unsupported power action: {action}")
        vmx_identity(vmware)
    except BaseException as exc:
        pending = exc
    finally:
        release = RC.release_local_queue(vmware, run_id)
    audit = {
        "runId": run_id,
        "action": action,
        "queueResource": vmware["queue_resource"],
        "queueClaim": claim,
        "queueRelease": release,
        "before": before,
        "after": after,
        "hardPowerFallbackUsed": False,
        "terminalState": "PASS" if pending is None and release.get("released") else "FAIL",
    }
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if pending is not None:
        raise pending
    if not release.get("released"):
        fail("host queue release failed; do not delete another requester's claim")
    return 0


def initialize(
    vmware: dict[str, Any],
    vmware_path: Path,
    ssh: dict[str, Any],
    ssh_path: Path,
    pin: bool,
) -> int:
    status = paired_status(vmware, vmware_path, ssh, ssh_path)
    if not status["initializationReady"]:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2
    if not status["checks"]["machineIdentityPinned"] and not pin:
        fail("machine identity is not pinned; rerun vm-init with --pin-machine-id")
    run_id = str(uuid.uuid4())
    claim = RC.claim_local_queue(vmware, run_id)
    initial_power: dict[str, Any] | None = None
    final_power: dict[str, Any] | None = None
    ssh_readback: dict[str, Any] | None = None
    started_for_initialization = False
    restored = False
    pending: BaseException | None = None
    cleanup_error: BaseException | None = None
    release: dict[str, Any] | None = None
    observed_machine_id = ""
    try:
        vmx_identity(vmware)
        initial_power = power_status(vmware)
        require_power_context_consistency(initial_power, ssh)
        if not initial_power["running"]:
            start_vm(vmware)
            started_for_initialization = True
        ssh_readback = wait_for_ssh(ssh, vmware["timeouts"]["ssh_ready_seconds"])
        observed_machine_id = ssh_readback["identity"]["machineIdSha256"]
        expected = ssh["identity"].get("expected_machine_id_sha256", "")
        if expected and expected != observed_machine_id:
            fail(f"machine identity changed: expected {expected}, got {observed_machine_id}")
        vmx_identity(vmware)
    except BaseException as exc:
        pending = exc
    finally:
        if started_for_initialization:
            try:
                stop_vm_soft(vmware)
                restored = True
            except BaseException as exc:
                cleanup_error = exc
        try:
            final_power = power_status(vmware)
        except BaseException as exc:
            cleanup_error = cleanup_error or exc
        release = RC.release_local_queue(vmware, run_id)

    if (
        pending is None
        and cleanup_error is None
        and observed_machine_id
        and pin
        and release
        and release.get("released")
    ):
        ssh = pin_machine_identity(ssh_path, ssh, observed_machine_id)
    expected_final_running = bool(initial_power and initial_power["running"])
    state_restored = bool(
        final_power and final_power["running"] == expected_final_running
    )
    successful = (
        pending is None
        and cleanup_error is None
        and ssh_readback is not None
        and state_restored
        and bool(release and release.get("released"))
    )
    receipt = {
        "status": "PASS" if successful else "FAIL",
        "runId": run_id,
        "issuedAt": datetime.now(timezone.utc).isoformat(),
        "profiles": {
            "vmware": vmware["profile_name"],
            "ssh": ssh["profile_name"],
        },
        "profileSha256": {
            "vmware": RC.profile_sha256(vmware),
            "ssh": RC.profile_sha256(ssh),
        },
        "queueResource": vmware["queue_resource"],
        "vmIdentity": vmware["vm_identity"],
        "vmxIdentity": vmx_identity(vmware),
        "sshIdentity": ssh_readback["identity"] if ssh_readback else None,
        "machineIdentityPinned": bool(
            ssh["identity"].get("expected_machine_id_sha256")
        ),
        "initialPower": initial_power,
        "finalPower": final_power,
        "startedForInitialization": started_for_initialization,
        "restoredOriginalPowerState": state_restored,
        "softStopReadback": restored,
        "hardPowerFallbackUsed": False,
        "queueClaim": claim,
        "queueRelease": release,
        "error": str(pending) if pending else None,
        "cleanupError": str(cleanup_error) if cleanup_error else None,
    }
    receipt["receiptSha256"] = RC.canonical_sha256(receipt)
    print("==> VM_INITIALIZATION_RECEIPT")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    if pending is not None:
        raise pending
    if cleanup_error is not None:
        raise cleanup_error
    if not successful:
        fail("VM initialization did not reach a verified terminal state")
    return 0


def build_lifecycle(
    scope: str,
    vmware: dict[str, Any],
    vmware_path: Path,
    ssh: dict[str, Any],
    ssh_path: Path,
    recipe: dict[str, Any],
    recipe_path: Path,
) -> int:
    status = paired_status(vmware, vmware_path, ssh, ssh_path)
    if not status["selectedProfileReady"]:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 2
    run_id = str(uuid.uuid4())
    claim = RC.claim_local_queue(vmware, run_id)
    initial_power: dict[str, Any] | None = None
    final_power: dict[str, Any] | None = None
    started_for_build = False
    build_exit_code: int | None = None
    pending: BaseException | None = None
    cleanup_error: BaseException | None = None
    release: dict[str, Any] | None = None
    try:
        vmx_identity(vmware)
        initial_power = power_status(vmware)
        require_power_context_consistency(initial_power, ssh)
        if not initial_power["running"]:
            start_vm(vmware)
            started_for_build = True
        wait_for_ssh(ssh, vmware["timeouts"]["ssh_ready_seconds"])
        build_exit_code = RC.build(
            ssh,
            recipe,
            recipe_path,
            scope,
            host_queue_context={"runId": run_id, "claim": claim},
        )
    except BaseException as exc:
        pending = exc
    finally:
        if started_for_build:
            try:
                stop_vm_soft(vmware)
            except BaseException as exc:
                cleanup_error = exc
        try:
            final_power = power_status(vmware)
        except BaseException as exc:
            cleanup_error = cleanup_error or exc
        release = RC.release_local_queue(vmware, run_id)

    expected_final_running = bool(initial_power and initial_power["running"])
    state_restored = bool(
        final_power and final_power["running"] == expected_final_running
    )
    successful = (
        pending is None
        and cleanup_error is None
        and build_exit_code == 0
        and state_restored
        and bool(release and release.get("released"))
    )
    audit = {
        "runId": run_id,
        "action": "vm-build",
        "scope": scope,
        "buildExitCode": build_exit_code,
        "initialPower": initial_power,
        "finalPower": final_power,
        "startedForBuild": started_for_build,
        "restoredOriginalPowerState": state_restored,
        "hardPowerFallbackUsed": False,
        "queueClaim": claim,
        "queueRelease": release,
        "error": str(pending) if pending else None,
        "cleanupError": str(cleanup_error) if cleanup_error else None,
        "terminalState": "PASS" if successful else "FAIL",
    }
    audit["receiptSha256"] = RC.canonical_sha256(audit)
    print("==> VM_BUILD_LIFECYCLE_AUDIT")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if pending is not None:
        raise pending
    if cleanup_error is not None:
        raise cleanup_error
    if not successful:
        return build_exit_code or 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, help="explicit environment Profile or directory")
    parser.add_argument("--recipe", type=Path, help="explicit build recipe")
    parser.add_argument("--binding-id", help="saved Profile binding ID")
    parser.add_argument("--project-root", type=Path, help="project registry root")
    parser.add_argument("--registry-root", type=Path, help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("profile-check", help="validate the paired Profiles offline")
    subparsers.add_parser("vm-status", help="read VMware power state")
    init_parser = subparsers.add_parser(
        "vm-init", help="validate composite identity and restore original power state"
    )
    init_parser.add_argument("--pin-machine-id", action="store_true")
    subparsers.add_parser("vm-start", help="start the VM and wait for pinned SSH identity")
    subparsers.add_parser("vm-stop", help="soft-stop the VM; never use a hard fallback")
    subparsers.add_parser("vm-restart", help="soft-stop, start, and verify SSH identity")
    build_parser = subparsers.add_parser(
        "vm-build", help="hold the host queue across power, SSH build, and restoration"
    )
    build_parser.add_argument("scope", help="exact non-GUI scope declared by the selected recipe")
    subparsers.add_parser("queue-status", help="read the host lifecycle queue owner")
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
    vmware_path = selection.environment_path
    ssh_path = selection.environment_path
    vmware = load_vmware_profile(vmware_path)
    ssh = RC.load_profile(ssh_path)
    status = paired_status(vmware, vmware_path, ssh, ssh_path)
    provider_path = PM.require_provider(selection.recipe, selection.recipe_path)
    status["recipe"] = selection.recipe["recipeId"]
    status["recipeSha256"] = PM.canonical_sha256(selection.recipe)
    status["providerSha256"] = hashlib.sha256(provider_path.read_bytes()).hexdigest()
    status["scopes"] = selection.recipe["scopes"]
    if args.command == "profile-check":
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status["selectedProfileReady"] else 2
    if args.command == "queue-status":
        print(json.dumps(RC.local_queue_status(vmware), ensure_ascii=False, indent=2))
        return 0
    if args.command == "vm-status":
        power = power_status(vmware)
        output = {
            **status,
            "power": power,
            "executionContext": require_power_context_consistency(power, ssh),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0 if status["initializationReady"] else 2
    if args.command == "vm-init":
        return initialize(vmware, vmware_path, ssh, ssh_path, args.pin_machine_id)
    if args.command == "vm-build":
        return build_lifecycle(
            args.scope,
            vmware,
            vmware_path,
            ssh,
            ssh_path,
            selection.recipe,
            selection.recipe_path,
        )
    action = args.command.removeprefix("vm-")
    return power_action(action, vmware, vmware_path, ssh, ssh_path)


if __name__ == "__main__":
    raise SystemExit(main())

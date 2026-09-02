#!/usr/bin/env python3
"""Discover, validate, scaffold, and persist non-secret build-client Profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent.parent
ENVIRONMENT_FILE = "environment.json"
RECIPE_FILE = "build-recipe.json"
PRIVATE_REGISTRY_PARTS = ("profiles", "build-client")
PROTECTED_PREFIXES = ("protected:", "provider:", "session:")
FORBIDDEN_SECRET_KEYS = {
    "password",
    "passwd",
    "passphrase",
    "token",
    "secret",
    "privatekey",
    "private_key",
    "private_key_body",
    "apikey",
    "api_key",
}
BINDING_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
SCOPE_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
MACHINE_ID_PATTERN = re.compile(r"[0-9a-f]{64}")


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Selection:
    mode: str
    environment_path: Path
    recipe_path: Path
    environment: dict[str, Any]
    recipe: dict[str, Any]


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _text_list(value: Any, *, non_empty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (not non_empty or bool(value))
        and all(_text(item) for item in value)
    )


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _protected_ref(value: Any) -> bool:
    return _text(value) and value.startswith(PROTECTED_PREFIXES)


def _find_forbidden_keys(value: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            normalized = str(key).lower().replace("-", "_")
            if normalized in FORBIDDEN_SECRET_KEYS:
                found.append(child_path)
            found.extend(_find_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_keys(child, f"{path}[{index}]"))
    elif isinstance(value, str) and "BEGIN PRIVATE KEY" in value:
        found.append(path or "root")
    return found


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileError(f"file not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProfileError(f"JSON root must be an object: {path}")
    return value


def _validate_common_profile(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for path in _find_forbidden_keys(data):
        errors.append(f"secret-bearing field is not allowed: {path}")
    if data.get("containsSecrets") is not False:
        errors.append("containsSecrets must be false")
    if not isinstance(data.get("shareable"), bool):
        errors.append("shareable must be boolean")
    return errors


def validate_environment(data: dict[str, Any]) -> list[str]:
    errors = _validate_common_profile(data)
    if data.get("schemaVersion") != 2:
        errors.append("schemaVersion must be 2")
    for field in (
        "bindingId",
        "displayName",
        "scope",
        "fingerprint",
        "toolchainProfile",
    ):
        if not _text(data.get(field)):
            errors.append(f"{field} must be non-empty")
    binding_id = data.get("bindingId")
    if _text(binding_id) and not BINDING_PATTERN.fullmatch(binding_id):
        errors.append("bindingId must use lowercase letters, digits, dot, underscore, or hyphen")
    if not _text_list(data.get("capabilities"), non_empty=True):
        errors.append("capabilities must be a non-empty string array")

    nodes = data.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append("nodes must be a non-empty array")
        nodes = []
    node_ids: set[str] = set()
    providers: dict[str, tuple[int, dict[str, Any], dict[str, Any]]] = {}
    for index, node in enumerate(nodes):
        prefix = f"nodes[{index}]"
        if not isinstance(node, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("nodeId", "platform", "fingerprint"):
            if not _text(node.get(field)):
                errors.append(f"{prefix}.{field} must be non-empty")
        node_id = node.get("nodeId")
        if _text(node_id):
            if node_id in node_ids:
                errors.append(f"duplicate nodeId {node_id}")
            node_ids.add(node_id)
        if not _text_list(node.get("roles"), non_empty=True):
            errors.append(f"{prefix}.roles must be a non-empty string array")
        if not _text_list(node.get("capabilities"), non_empty=True):
            errors.append(f"{prefix}.capabilities must be a non-empty string array")
        if not _protected_ref(node.get("accessRef")):
            errors.append(f"{prefix}.accessRef must be a protected/provider/session reference")
        privilege_ref = node.get("privilegeRef")
        if privilege_ref is not None and not _protected_ref(privilege_ref):
            errors.append(f"{prefix}.privilegeRef must be null or a protected reference")
        credential_refs = node.get("credentialRefs")
        if not isinstance(credential_refs, dict):
            errors.append(f"{prefix}.credentialRefs must be an object")
        else:
            for name, reference in credential_refs.items():
                if not _text(name) or not _protected_ref(reference):
                    errors.append(f"{prefix}.credentialRefs entries must be protected references")
        provider = node.get("provider")
        if not isinstance(provider, dict):
            errors.append(f"{prefix}.provider must be an object")
            continue
        kind = provider.get("kind")
        if kind not in ("vmware-workstation", "ssh"):
            errors.append(f"{prefix}.provider.kind must be vmware-workstation or ssh")
            continue
        if kind in providers:
            errors.append(f"exactly one {kind} node is allowed")
        providers[kind] = (index, node, provider)

    if set(providers) != {"vmware-workstation", "ssh"}:
        errors.append("a paired Profile requires exactly one vmware-workstation node and one ssh node")
        return errors

    vm_index, vm_node, vm = providers["vmware-workstation"]
    ssh_index, ssh_node, ssh = providers["ssh"]
    vm_prefix = f"nodes[{vm_index}].provider"
    ssh_prefix = f"nodes[{ssh_index}].provider"

    for field in (
        "managementHost",
        "queueResource",
        "vmIdentity",
        "vmrunPath",
        "workstationGuiPath",
    ):
        if not _text(vm.get(field)):
            errors.append(f"{vm_prefix}.{field} must be non-empty")
    if vm.get("managementHost") != "localhost":
        errors.append(f"{vm_prefix}.managementHost must be localhost")
    vm_data = vm.get("vm")
    if not isinstance(vm_data, dict):
        errors.append(f"{vm_prefix}.vm must be an object")
        vm_data = {}
    for field in (
        "displayName",
        "vmxPath",
        "guestOs",
        "expectedUuid",
        "expectedMac",
        "expectedIpv4",
    ):
        if not _text(vm_data.get(field)):
            errors.append(f"{vm_prefix}.vm.{field} must be non-empty")
    vm_caps = set(vm_node.get("capabilities") or [])
    required_vm_caps = {"status", "start", "gui-console", "soft-stop", "soft-restart"}
    if not required_vm_caps.issubset(vm_caps):
        errors.append(f"nodes[{vm_index}].capabilities must include {sorted(required_vm_caps)}")
    if vm_caps.intersection({"hard-stop", "snapshot"}):
        errors.append(f"nodes[{vm_index}].capabilities must not include hard-stop or snapshot")

    for field in ("host", "user", "queueResource", "vmIdentity"):
        if not _text(ssh.get(field)):
            errors.append(f"{ssh_prefix}.{field} must be non-empty")
    if not _positive_int(ssh.get("port")):
        errors.append(f"{ssh_prefix}.port must be a positive integer")
    host_key = ssh.get("hostKey")
    if not isinstance(host_key, dict):
        errors.append(f"{ssh_prefix}.hostKey must be an object")
        host_key = {}
    if host_key.get("policy") != "managed" or host_key.get("strictChecking") is not True:
        errors.append(f"{ssh_prefix}.hostKey requires policy=managed and strictChecking=true")
    expected_host_key = host_key.get("expectedSha256")
    if not _text(expected_host_key) or not expected_host_key.startswith("SHA256:"):
        errors.append(f"{ssh_prefix}.hostKey.expectedSha256 must be an OpenSSH SHA-256 fingerprint")
    identity = ssh.get("identity")
    if not isinstance(identity, dict):
        errors.append(f"{ssh_prefix}.identity must be an object")
        identity = {}
    if identity.get("type") != "ssh-host-key-and-machine-id":
        errors.append(f"{ssh_prefix}.identity.type must be ssh-host-key-and-machine-id")
    machine_id = identity.get("expectedMachineIdSha256", "")
    if machine_id and (not isinstance(machine_id, str) or not MACHINE_ID_PATTERN.fullmatch(machine_id)):
        errors.append(f"{ssh_prefix}.identity.expectedMachineIdSha256 must be empty or 64 lowercase hex")
    ssh_caps = set(ssh_node.get("capabilities") or [])
    if not {"read", "execute", "copy"}.issubset(ssh_caps):
        errors.append(f"nodes[{ssh_index}].capabilities must include read, execute, and copy")
    if ssh_caps.intersection({"reboot", "power", "snapshot"}):
        errors.append(f"nodes[{ssh_index}].capabilities must not include reboot, power, or snapshot")
    for key in ("ssh", "knownHosts"):
        reference = (ssh_node.get("credentialRefs") or {}).get(key)
        if not _text(reference) or not reference.startswith("protected:profile/"):
            errors.append(f"nodes[{ssh_index}].credentialRefs.{key} must use protected:profile/")

    for prefix, provider, fields in (
        (
            vm_prefix,
            vm,
            ("commandSeconds", "powerOnSeconds", "powerOffSeconds", "sshReadySeconds", "queueWaitSeconds"),
        ),
        (
            ssh_prefix,
            ssh,
            ("connectSeconds", "preflightSeconds", "commandSeconds", "queueWaitSeconds"),
        ),
    ):
        timeouts = provider.get("timeouts")
        if not isinstance(timeouts, dict):
            errors.append(f"{prefix}.timeouts must be an object")
        else:
            for field in fields:
                if not _positive_int(timeouts.get(field)):
                    errors.append(f"{prefix}.timeouts.{field} must be a positive integer")
        receipt = provider.get("receipt")
        if not isinstance(receipt, dict) or not _positive_int(receipt.get("maxAgeSeconds")):
            errors.append(f"{prefix}.receipt.maxAgeSeconds must be a positive integer")

    if vm.get("queueResource") != ssh.get("queueResource"):
        errors.append("paired providers must share queueResource")
    if vm.get("vmIdentity") != ssh.get("vmIdentity"):
        errors.append("paired providers must share vmIdentity")
    if vm_data.get("expectedIpv4") != ssh.get("host"):
        errors.append("VM expectedIpv4 must equal the SSH host")

    evidence = data.get("evidencePolicy")
    if not isinstance(evidence, dict):
        errors.append("evidencePolicy must be an object")
    else:
        for field in ("location", "encoding", "decisionFormat", "locale"):
            if not _text(evidence.get(field)):
                errors.append(f"evidencePolicy.{field} must be non-empty")
        if evidence.get("encoding") != "UTF-8":
            errors.append("evidencePolicy.encoding must be UTF-8")
        if evidence.get("decisionFormat") != "JSON":
            errors.append("evidencePolicy.decisionFormat must be JSON")
    return errors


def validate_recipe(data: dict[str, Any]) -> list[str]:
    errors = _validate_common_profile(data)
    if data.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    for field in ("recipeId", "displayName"):
        if not _text(data.get(field)):
            errors.append(f"{field} must be non-empty")
    runner = data.get("runner")
    if not isinstance(runner, dict):
        errors.append("runner must be an object")
        runner = {}
    if runner.get("type") != "bash-stdin":
        errors.append("runner.type must be bash-stdin")
    script_ref = runner.get("scriptRef")
    if not _text(script_ref) or not script_ref.startswith("provider:profile/"):
        errors.append("runner.scriptRef must use provider:profile/")
    expected_provider = runner.get("expectedSha256")
    if not isinstance(expected_provider, str) or not MACHINE_ID_PATTERN.fullmatch(expected_provider):
        errors.append("runner.expectedSha256 must be 64 lowercase hexadecimal characters")
    scopes = data.get("scopes")
    if not isinstance(scopes, dict) or not scopes:
        errors.append("scopes must be a non-empty object")
        scopes = {}
    for scope, contract in scopes.items():
        prefix = f"scopes.{scope}"
        if not isinstance(scope, str) or not SCOPE_PATTERN.fullmatch(scope):
            errors.append(f"{prefix} has an invalid scope name")
        if not isinstance(contract, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if not _text(contract.get("description")):
            errors.append(f"{prefix}.description must be non-empty")
        count = contract.get("expectedArtifactCount")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append(f"{prefix}.expectedArtifactCount must be a non-negative integer")
        if contract.get("execution") != "remote-non-gui":
            errors.append(f"{prefix}.execution must be remote-non-gui")
    return errors


def require_valid_environment(path: Path) -> dict[str, Any]:
    data = load_json(path)
    errors = validate_environment(data)
    if errors:
        raise ProfileError(f"invalid environment Profile {path}: {'; '.join(errors)}")
    return data


def require_valid_recipe(path: Path) -> dict[str, Any]:
    data = load_json(path)
    errors = validate_recipe(data)
    if errors:
        raise ProfileError(f"invalid build recipe {path}: {'; '.join(errors)}")
    return data


def require_provider(recipe: dict[str, Any], recipe_path: Path) -> Path:
    provider = resolve_provider_path(recipe_path.resolve().parent, recipe["runner"]["scriptRef"])
    if not provider.is_file():
        raise ProfileError(f"build provider not found: {provider}")
    if provider.stat().st_size > 1024 * 1024:
        raise ProfileError("build provider exceeds the 1 MiB safety limit")
    payload = provider.read_bytes()
    if b"\x00" in payload or b"BEGIN PRIVATE KEY" in payload or b"BEGIN OPENSSH PRIVATE KEY" in payload:
        raise ProfileError("build provider contains forbidden binary or private-key material")
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProfileError("build provider must be UTF-8 text") from exc
    actual = hashlib.sha256(payload).hexdigest()
    expected = recipe["runner"]["expectedSha256"]
    if actual != expected:
        raise ProfileError(
            f"build provider hash drift: expected {expected}, got {actual}"
        )
    return provider


def codex_root() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def private_registry_root(override: Path | None = None) -> Path:
    return override.resolve() if override else codex_root().joinpath(*PRIVATE_REGISTRY_PARTS)


def project_registry_root(project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    return project_root.resolve() / ".codex" / "profiles" / "build-client"


def _candidate_environment_files(root: Path | None) -> list[Path]:
    if root is None or not root.is_dir():
        return []
    return sorted(path.resolve() for path in root.glob(f"*/{ENVIRONMENT_FILE}") if path.is_file())


def discover_profiles(
    *, project_root: Path | None = None, registry_root: Path | None = None
) -> list[dict[str, Any]]:
    candidates: list[tuple[str, Path]] = []
    candidates.extend(("PRIVATE", path) for path in _candidate_environment_files(private_registry_root(registry_root)))
    candidates.extend(("PROJECT", path) for path in _candidate_environment_files(project_registry_root(project_root)))
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for mode, environment_path in candidates:
        key = str(environment_path).casefold()
        if key in seen:
            continue
        seen.add(key)
        recipe_path = environment_path.parent / RECIPE_FILE
        try:
            environment = require_valid_environment(environment_path)
            recipe = require_valid_recipe(recipe_path)
            provider_path = require_provider(recipe, recipe_path)
            results.append(
                {
                    "mode": mode,
                    "bindingId": environment["bindingId"],
                    "displayName": environment["displayName"],
                    "fingerprint": environment["fingerprint"],
                    "environmentPath": str(environment_path),
                    "recipePath": str(recipe_path),
                    "environmentSha256": canonical_sha256(environment),
                    "recipeSha256": canonical_sha256(recipe),
                    "providerSha256": hashlib.sha256(provider_path.read_bytes()).hexdigest(),
                    "scopes": sorted(recipe["scopes"]),
                    "valid": True,
                }
            )
        except ProfileError as exc:
            results.append(
                {
                    "mode": mode,
                    "environmentPath": str(environment_path),
                    "recipePath": str(recipe_path),
                    "valid": False,
                    "error": str(exc),
                }
            )
    return results


def resolve_selection(
    *,
    profile: Path | None = None,
    recipe: Path | None = None,
    binding_id: str | None = None,
    project_root: Path | None = None,
    registry_root: Path | None = None,
) -> Selection:
    if profile is not None and binding_id is not None:
        raise ProfileError("choose either --profile or --binding-id, not both")
    if recipe is not None and profile is None:
        raise ProfileError("--recipe requires an explicit --profile")
    if profile is not None:
        environment_path = profile.resolve()
        if environment_path.is_dir():
            environment_path = environment_path / ENVIRONMENT_FILE
        recipe_path = recipe.resolve() if recipe else environment_path.parent / RECIPE_FILE
        environment = require_valid_environment(environment_path)
        build_recipe = require_valid_recipe(recipe_path)
        require_provider(build_recipe, recipe_path)
        return Selection("SESSION", environment_path, recipe_path, environment, build_recipe)

    discovered = discover_profiles(project_root=project_root, registry_root=registry_root)
    valid = [item for item in discovered if item.get("valid")]
    if binding_id:
        valid = [item for item in valid if item.get("bindingId") == binding_id]
    if not valid:
        invalid_count = sum(1 for item in discovered if not item.get("valid"))
        detail = f"; invalidProfiles={invalid_count}" if invalid_count else ""
        raise ProfileError(
            "UNCONFIGURED: no matching build-client Profile; initialize a candidate, "
            f"then ask the user to choose PRIVATE, PROJECT, or SESSION persistence{detail}"
        )
    if len(valid) > 1:
        labels = [f"{item['bindingId']} ({item['mode']})" for item in valid]
        raise ProfileError(
            "CHOICE_REQUIRED: multiple Profiles match; ask the user to select one: "
            + ", ".join(labels)
        )
    item = valid[0]
    environment_path = Path(item["environmentPath"])
    recipe_path = Path(item["recipePath"])
    build_recipe = require_valid_recipe(recipe_path)
    require_provider(build_recipe, recipe_path)
    return Selection(
        item["mode"],
        environment_path,
        recipe_path,
        require_valid_environment(environment_path),
        build_recipe,
    )


def _relative_profile_ref(reference: str, prefix: str) -> Path:
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ProfileError(f"reference must start with {prefix}")
    relative = Path(reference[len(prefix) :])
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise ProfileError("Profile reference must be a safe relative path")
    return relative


def protected_state_root(binding_id: str, fingerprint: str) -> Path:
    if not BINDING_PATTERN.fullmatch(binding_id):
        raise ProfileError("invalid binding ID for protected state")
    state_key = hashlib.sha256(f"{binding_id}\0{fingerprint}".encode("utf-8")).hexdigest()[:16]
    return codex_root() / "state" / "build-client" / f"{binding_id}-{state_key}" / "protected"


def resolve_protected_path(
    profile_dir: Path,
    reference: str,
    *,
    binding_id: str | None = None,
    fingerprint: str | None = None,
) -> Path:
    relative = _relative_profile_ref(reference, "protected:profile/")
    if binding_id is not None and fingerprint is not None:
        base = protected_state_root(binding_id, fingerprint).resolve()
    else:
        base = (profile_dir / ".protected").resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ProfileError("protected reference escapes the Profile directory") from exc
    return candidate


def resolve_provider_path(profile_dir: Path, reference: str) -> Path:
    relative = _relative_profile_ref(reference, "provider:profile/")
    base = (profile_dir / "providers").resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ProfileError("provider reference escapes the Profile directory") from exc
    return candidate


def provider_nodes(environment: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    vm_node = next(node for node in environment["nodes"] if node["provider"]["kind"] == "vmware-workstation")
    ssh_node = next(node for node in environment["nodes"] if node["provider"]["kind"] == "ssh")
    return vm_node, ssh_node


def to_vmware_profile(environment: dict[str, Any], environment_path: Path) -> dict[str, Any]:
    vm_node, _ = provider_nodes(environment)
    provider = vm_node["provider"]
    timeouts = provider["timeouts"]
    vm = provider["vm"]
    return {
        "profile_name": environment["bindingId"],
        "kind": "vmware-workstation",
        "management_host": provider["managementHost"],
        "platform": vm_node["platform"],
        "queue_resource": provider["queueResource"],
        "vm_identity": provider["vmIdentity"],
        "vmrun_path": provider["vmrunPath"],
        "workstation_gui_path": provider["workstationGuiPath"],
        "credential": {"source": "current-windows-user"},
        "vm": {
            "display_name": vm["displayName"],
            "vmx_path": vm["vmxPath"],
            "guest_os": vm["guestOs"],
            "expected_uuid": vm["expectedUuid"],
            "expected_mac": vm["expectedMac"],
            "expected_ipv4": vm["expectedIpv4"],
        },
        "capabilities": {
            "status": "status" in vm_node["capabilities"],
            "start": "start" in vm_node["capabilities"],
            "gui_console": "gui-console" in vm_node["capabilities"],
            "soft_stop": "soft-stop" in vm_node["capabilities"],
            "soft_restart": "soft-restart" in vm_node["capabilities"],
            "hard_stop": "hard-stop" in vm_node["capabilities"],
            "snapshot": "snapshot" in vm_node["capabilities"],
        },
        "timeouts": {
            "command_seconds": timeouts["commandSeconds"],
            "power_on_seconds": timeouts["powerOnSeconds"],
            "power_off_seconds": timeouts["powerOffSeconds"],
            "ssh_ready_seconds": timeouts["sshReadySeconds"],
            "queue_wait_seconds": timeouts["queueWaitSeconds"],
        },
        "receipt": {"max_age_seconds": provider["receipt"]["maxAgeSeconds"]},
        "_environment_path": str(environment_path.resolve()),
        "_environment_sha256": canonical_sha256(environment),
        "_binding_id": environment["bindingId"],
        "_fingerprint": environment["fingerprint"],
    }


def to_ssh_profile(environment: dict[str, Any], environment_path: Path) -> dict[str, Any]:
    _, ssh_node = provider_nodes(environment)
    provider = ssh_node["provider"]
    timeouts = provider["timeouts"]
    refs = ssh_node["credentialRefs"]
    return {
        "profile_name": environment["bindingId"],
        "kind": "ssh",
        "host": provider["host"],
        "port": provider["port"],
        "user": provider["user"],
        "platform": ssh_node["platform"],
        "queue_resource": provider["queueResource"],
        "vm_identity": provider["vmIdentity"],
        "credential": {
            "source": "identity-file",
            "identity_file": refs["ssh"],
        },
        "host_key": {
            "policy": provider["hostKey"]["policy"],
            "strict_checking": provider["hostKey"]["strictChecking"],
            "expected_sha256": provider["hostKey"]["expectedSha256"],
            "known_hosts_file": refs["knownHosts"],
        },
        "identity": {
            "type": provider["identity"]["type"],
            "expected_machine_id_sha256": provider["identity"].get("expectedMachineIdSha256", ""),
        },
        "capabilities": {
            name: name in ssh_node["capabilities"]
            for name in ("read", "execute", "copy", "reboot", "power", "snapshot")
        },
        "timeouts": {
            "connect_seconds": timeouts["connectSeconds"],
            "preflight_seconds": timeouts["preflightSeconds"],
            "command_seconds": timeouts["commandSeconds"],
            "queue_wait_seconds": timeouts["queueWaitSeconds"],
        },
        "receipt": {"max_age_seconds": provider["receipt"]["maxAgeSeconds"]},
        "_environment_path": str(environment_path.resolve()),
        "_environment_sha256": canonical_sha256(environment),
        "_binding_id": environment["bindingId"],
        "_fingerprint": environment["fingerprint"],
    }


def pin_machine_identity(environment_path: Path, machine_id_sha256: str) -> dict[str, Any]:
    if not MACHINE_ID_PATTERN.fullmatch(machine_id_sha256):
        raise ProfileError("machine identity must be 64 lowercase hexadecimal characters")
    environment = require_valid_environment(environment_path)
    _, ssh_node = provider_nodes(environment)
    identity = ssh_node["provider"]["identity"]
    current = identity.get("expectedMachineIdSha256", "")
    if current and current != machine_id_sha256:
        raise ProfileError("refusing to replace a pinned machine identity; create or explicitly replace the Profile")
    identity["expectedMachineIdSha256"] = machine_id_sha256
    _atomic_json_write(environment_path, environment)
    return environment


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def scaffold(output: Path) -> dict[str, Any]:
    destination = output.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ProfileError(f"scaffold destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    providers = destination / "providers"
    providers.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SKILL_DIR / "assets" / "environment-profile.template.json", destination / ENVIRONMENT_FILE)
    shutil.copy2(SKILL_DIR / "assets" / "build-recipe.template.json", destination / RECIPE_FILE)
    shutil.copy2(SKILL_DIR / "assets" / "providers" / "remote-build.sh", providers / "remote-build.sh")
    return {"status": "UNCONFIGURED", "directory": str(destination), "next": "edit fictional placeholders, validate, then choose PRIVATE, PROJECT, or SESSION"}


def save_selection(
    *,
    environment_path: Path,
    recipe_path: Path,
    mode: str,
    project_root: Path | None = None,
    registry_root: Path | None = None,
    replace: bool = False,
    accept_fingerprint_change: bool = False,
) -> dict[str, Any]:
    environment_path = environment_path.resolve()
    recipe_path = recipe_path.resolve()
    environment = require_valid_environment(environment_path)
    recipe = require_valid_recipe(recipe_path)
    source_provider = require_provider(recipe, recipe_path)
    normalized_mode = mode.upper()
    if normalized_mode == "SESSION":
        return {
            "status": "CONFIGURED",
            "mode": "SESSION",
            "persisted": False,
            "environmentPath": str(environment_path),
            "recipePath": str(recipe_path),
        }
    if normalized_mode == "PRIVATE":
        root = private_registry_root(registry_root)
    elif normalized_mode == "PROJECT":
        root = project_registry_root(project_root)
        if root is None:
            raise ProfileError("PROJECT persistence requires --project-root")
        if environment.get("shareable") is not True or recipe.get("shareable") is not True:
            raise ProfileError("PROJECT persistence requires explicitly sanitized shareable Profiles")
    else:
        raise ProfileError("mode must be PRIVATE, PROJECT, or SESSION")

    destination = root / environment["bindingId"]
    destination_environment = destination / ENVIRONMENT_FILE
    destination_recipe = destination / RECIPE_FILE
    if destination.exists() and not replace:
        raise ProfileError(f"Profile already exists: {destination}; explicit replacement authorization is required")
    if destination_environment.is_file():
        current = require_valid_environment(destination_environment)
        if current.get("fingerprint") != environment.get("fingerprint") and not accept_fingerprint_change:
            raise ProfileError("environment fingerprint changed; do not treat drift as a new environment without explicit acceptance")

    destination_provider = resolve_provider_path(destination, recipe["runner"]["scriptRef"])
    destination_provider.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json_write(destination_environment, environment)
    _atomic_json_write(destination_recipe, recipe)
    shutil.copy2(source_provider, destination_provider)
    try:
        destination.chmod(0o700)
        destination_provider.chmod(0o700)
    except OSError:
        pass
    return {
        "status": "CONFIGURED",
        "mode": normalized_mode,
        "persisted": True,
        "bindingId": environment["bindingId"],
        "environmentPath": str(destination_environment),
        "recipePath": str(destination_recipe),
        "fingerprint": environment["fingerprint"],
    }


def selection_payload(selection: Selection) -> dict[str, Any]:
    provider_path = require_provider(selection.recipe, selection.recipe_path)
    return {
        "status": "CONFIGURED",
        "selectedProfileReady": False,
        "reason": "read-only provider and target preflight is still required",
        "mode": selection.mode,
        "bindingId": selection.environment["bindingId"],
        "displayName": selection.environment["displayName"],
        "fingerprint": selection.environment["fingerprint"],
        "environmentPath": str(selection.environment_path),
        "recipePath": str(selection.recipe_path),
        "environmentSha256": canonical_sha256(selection.environment),
        "recipeSha256": canonical_sha256(selection.recipe),
        "providerSha256": hashlib.sha256(provider_path.read_bytes()).hexdigest(),
        "scopes": selection.recipe["scopes"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--environment", type=Path, required=True)
    validate.add_argument("--recipe", type=Path, required=True)
    listing = subparsers.add_parser("list")
    listing.add_argument("--project-root", type=Path)
    listing.add_argument("--registry-root", type=Path)
    resolve = subparsers.add_parser("resolve")
    resolve.add_argument("--profile", type=Path)
    resolve.add_argument("--recipe", type=Path)
    resolve.add_argument("--binding-id")
    resolve.add_argument("--project-root", type=Path)
    resolve.add_argument("--registry-root", type=Path)
    initialize = subparsers.add_parser("init")
    initialize.add_argument("output", type=Path)
    save = subparsers.add_parser("save")
    save.add_argument("--environment", type=Path, required=True)
    save.add_argument("--recipe", type=Path, required=True)
    save.add_argument("--mode", choices=("PRIVATE", "PROJECT", "SESSION"), required=True)
    save.add_argument("--project-root", type=Path)
    save.add_argument("--registry-root", type=Path)
    save.add_argument("--replace", action="store_true")
    save.add_argument("--accept-fingerprint-change", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "validate":
            environment = load_json(args.environment)
            recipe = load_json(args.recipe)
            errors = validate_environment(environment) + validate_recipe(recipe)
            if not errors:
                try:
                    require_provider(recipe, args.recipe)
                except ProfileError as exc:
                    errors.append(str(exc))
            print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
            return 0 if not errors else 2
        if args.command == "list":
            profiles = discover_profiles(project_root=args.project_root, registry_root=args.registry_root)
            print(json.dumps({"profiles": profiles}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "resolve":
            selection = resolve_selection(
                profile=args.profile,
                recipe=args.recipe,
                binding_id=args.binding_id,
                project_root=args.project_root,
                registry_root=args.registry_root,
            )
            print(json.dumps(selection_payload(selection), ensure_ascii=False, indent=2))
            return 0
        if args.command == "init":
            print(json.dumps(scaffold(args.output), ensure_ascii=False, indent=2))
            return 0
        payload = save_selection(
            environment_path=args.environment,
            recipe_path=args.recipe,
            mode=args.mode,
            project_root=args.project_root,
            registry_root=args.registry_root,
            replace=args.replace,
            accept_fingerprint_change=args.accept_fingerprint_change,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except ProfileError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3 if str(exc).startswith("UNCONFIGURED") else 4 if str(exc).startswith("CHOICE_REQUIRED") else 2


if __name__ == "__main__":
    raise SystemExit(main())

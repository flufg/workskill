from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parent / "vmware-client.py"
SPEC = importlib.util.spec_from_file_location("vmware_client_test_target", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VM = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VM
SPEC.loader.exec_module(VM)


class VmwareClientTests(unittest.TestCase):
    def make_environment(self, root: Path) -> Path:
        environment = VM.PM.load_json(
            SCRIPT.parent.parent / "assets" / "environment-profile.template.json"
        )
        vm = environment["nodes"][0]["provider"]
        vmrun = root / "vmrun.exe"
        gui = root / "vmware.exe"
        vmx = root / "Example.vmx"
        vmrun.write_bytes(b"fixture")
        gui.write_bytes(b"fixture")
        vmx.write_text(
            "\n".join(
                (
                    'displayName = "Example_CentOS_Build"',
                    'guestOS = "centos7-64"',
                    'uuid.bios = "56 4d 00 00 00 00 00 00-00 00 00 00 00 00 00 01"',
                    'ethernet0.generatedAddress = "00:50:56:00:00:01"',
                )
            ),
            encoding="utf-8",
        )
        vm["vmrunPath"] = str(vmrun)
        vm["workstationGuiPath"] = str(gui)
        vm["vm"]["vmxPath"] = str(vmx)
        path = root / "environment.json"
        path.write_text(json.dumps(environment, indent=2) + "\n", encoding="utf-8")
        return path

    def test_normalizes_uuid_and_mac(self) -> None:
        self.assertEqual(
            VM.normalize_uuid("56 4d 00 00-00 00 00 00 00 00 00 00 00 00 00 01"),
            "564d0000000000000000000000000001",
        )
        self.assertEqual(VM.normalize_mac("00:50:56:00:00:01"), "00:50:56:00:00:01")

    def test_parses_static_vmx_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_environment(Path(temporary))
            profile = VM.load_vmware_profile(path)
            identity = VM.vmx_identity(profile)
        self.assertEqual(identity["displayName"], "Example_CentOS_Build")
        self.assertEqual(identity["mac"], "00:50:56:00:00:01")

    def test_rejects_hard_power_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_environment(Path(temporary))
            data = json.loads(path.read_text(encoding="utf-8"))
            data["nodes"][0]["capabilities"].append("hard-stop")
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SystemExit):
                VM.load_vmware_profile(path)

    def test_ssh_profile_requires_copy_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self.make_environment(Path(temporary))
            data = json.loads(path.read_text(encoding="utf-8"))
            data["nodes"][1]["capabilities"].remove("copy")
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(SystemExit):
                VM.RC.load_profile(path)

    def test_vmrun_uses_argument_vector_without_shell(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile = VM.load_vmware_profile(self.make_environment(Path(temporary)))
            completed = mock.Mock(returncode=0, stdout="Total running VMs: 0\n", stderr="")
            with mock.patch.object(VM.subprocess, "run", return_value=completed) as runner:
                VM.run_vmrun(profile, "list")
            args, kwargs = runner.call_args
            self.assertEqual(args[0][1:4], ["-T", "ws", "list"])
            self.assertNotIn("shell", kwargs)

    def test_local_queue_release_is_owner_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = VM.load_vmware_profile(self.make_environment(root))
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(root / "local")}, clear=False):
                claim = VM.RC.claim_local_queue(profile, "owner-a", wait_seconds=1)
                wrong = VM.RC.release_local_queue(profile, "owner-b")
                self.assertFalse(wrong["released"])
                self.assertTrue(Path(claim["claimPath"]).is_dir())
                right = VM.RC.release_local_queue(profile, "owner-a")
                self.assertTrue(right["released"])

    def test_rejects_ambiguous_vmrun_execution_context(self) -> None:
        ssh = {"host": "192.0.2.10", "port": 22}
        power = {"running": False, "state": "stopped"}
        with mock.patch.object(VM, "ssh_tcp_reachable", return_value=True):
            with self.assertRaises(SystemExit):
                VM.require_power_context_consistency(power, ssh)

    def test_build_scope_is_data_driven(self) -> None:
        args = VM.parse_args(["vm-build", "component-a"])
        self.assertEqual("component-a", args.scope)
        remote = VM.RC.parse_args(["build", "component-a"])
        self.assertEqual("component-a", remote.scope)

    def test_public_provider_never_launches_gui(self) -> None:
        provider = (
            SCRIPT.parent.parent / "assets" / "providers" / "remote-build.sh"
        ).read_text(encoding="utf-8")
        self.assertNotIn("nohup", provider)
        self.assertNotIn("DISPLAY=", provider)
        self.assertNotIn("vmware", provider.lower())
        self.assertIn('[[ "$WORKSPACE_ROOT" == "/srv/example-client/workspace" ]]', provider)
        self.assertIn('cp -R -- "$SOURCE_ROOT/." "$WORKSPACE_ROOT/"', provider)
        self.assertIn('WORKSPACE_READY source=example-source', provider)
        self.assertIn('WORKSPACE_CLEANUP_READBACK path=%s absent=true', provider)
        self.assertIn('[[ ! -e "$WORKSPACE_ROOT" && ! -L "$WORKSPACE_ROOT" ]]', provider)
        self.assertNotIn('rm -rf -- "$SOURCE_ROOT"', provider)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parent / "redis_credential.py"
SPEC = importlib.util.spec_from_file_location("redis_credential_test_target", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
RC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RC
SPEC.loader.exec_module(RC)
REFERENCE = "example-build-client-redis"


class RedisCredentialTests(unittest.TestCase):
    def test_status_reports_reference_without_secret(self) -> None:
        with mock.patch.object(RC, "credential_exists", return_value=True):
            payload = RC.status_payload(REFERENCE)
        self.assertEqual(payload["reference"], REFERENCE)
        self.assertTrue(payload["configured"])
        self.assertFalse(payload["secretExposed"])

    def test_setup_reuses_existing_credential_without_prompting(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(RC, "credential_exists", return_value=True),
            mock.patch.object(RC.getpass, "getpass") as prompt,
            mock.patch.object(RC, "write_secret") as writer,
            contextlib.redirect_stdout(output),
        ):
            result = RC.main(["--reference", REFERENCE, "setup"])
        self.assertEqual(result, 0)
        prompt.assert_not_called()
        writer.assert_not_called()
        self.assertTrue(json.loads(output.getvalue())["reusedExisting"])

    def test_setup_replace_prompts_twice_and_writes_once(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(RC, "credential_exists", return_value=True),
            mock.patch.object(RC.getpass, "getpass", side_effect=["replacement", "replacement"]),
            mock.patch.object(RC, "write_secret") as writer,
            contextlib.redirect_stdout(output),
        ):
            result = RC.main(["--reference", REFERENCE, "setup", "--replace"])
        self.assertEqual(result, 0)
        writer.assert_called_once_with(REFERENCE, "replacement")
        self.assertNotIn("replacement", output.getvalue())

    def test_confirmation_mismatch_never_writes(self) -> None:
        error = io.StringIO()
        with (
            mock.patch.object(RC, "credential_exists", return_value=False),
            mock.patch.object(RC.getpass, "getpass", side_effect=["one", "two"]),
            mock.patch.object(RC, "write_secret") as writer,
            contextlib.redirect_stderr(error),
        ):
            result = RC.main(["--reference", REFERENCE, "setup"])
        self.assertEqual(result, 2)
        writer.assert_not_called()
        self.assertNotIn("one", error.getvalue())
        self.assertNotIn("two", error.getvalue())

    def test_delete_requires_exact_reference(self) -> None:
        error = io.StringIO()
        with (
            mock.patch.object(RC, "delete_secret") as delete,
            contextlib.redirect_stderr(error),
        ):
            result = RC.main(
                ["--reference", REFERENCE, "delete", "--confirm-reference", "different"]
            )
        self.assertEqual(2, result)
        delete.assert_not_called()

    def test_no_cli_command_can_print_the_secret(self) -> None:
        for command in ("get", "show", "print", "export"):
            with self.subTest(command=command):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        RC.parse_args(["--reference", REFERENCE, command])

    def test_rejects_empty_or_nul_secret_before_provider_call(self) -> None:
        for value in ("", "bad\x00value"):
            with self.subTest(value=value):
                with self.assertRaises(RC.CredentialError):
                    RC.write_secret(REFERENCE, value)


if __name__ == "__main__":
    unittest.main()

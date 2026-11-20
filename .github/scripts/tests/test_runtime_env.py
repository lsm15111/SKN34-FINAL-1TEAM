"""실제 AWS 호출 없이 배포 환경 파일의 비밀값 처리와 보존을 검사한다."""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

SOURCE = Path(__file__).resolve().parents[3] / "deploy/aws/runtime_env.py"
SPEC = importlib.util.spec_from_file_location("runtime_env", SOURCE)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
DB_ID = "arn:aws:secretsmanager:ap-northeast-2:000000000000:secret:fake-db-123456"
AI_ID = "mitjip-staging/ai-runtime"
CANARY = "fake-only-$key'quote\\path"
MISSING = (
    "An error occurred (ResourceNotFoundException) when calling "
    "the GetSecretValue operation: fake missing"
)


def response(data):
    return subprocess.CompletedProcess(
        args=["aws"],
        returncode=0,
        stdout=json.dumps({"SecretString": json.dumps(data)}),
        stderr="",
    )


class RuntimeEnvTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / ".env.runtime"
        self.args = argparse.Namespace(
            region="ap-northeast-2",
            stack="mitjip-staging",
            db_secret_id=DB_ID,
            db_host="db.example.test",
            bucket="fake-bucket",
            host="staging.example.test",
            output=str(self.path),
        )
        self.db = {"username": "fake:admin", "password": "fake@p$'\\:/#"}
        self.calls = []

    def fake_aws(self, *, ai=None, ai_error=None, db_error=None):
        def call(command, **kwargs):
            self.calls.append(command)
            self.assertTrue(kwargs["capture_output"])
            self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
            self.assertNotIn(CANARY, " ".join(command))
            secret_id = command[command.index("--secret-id") + 1]
            if secret_id == DB_ID:
                if db_error is not None:
                    return subprocess.CompletedProcess(command, 254, "", db_error)
                return response(self.db)
            self.assertEqual(secret_id, AI_ID)
            if ai_error is not None:
                return subprocess.CompletedProcess(command, 254, "", ai_error)
            return response(ai or {})

        return patch.object(runtime.subprocess, "run", side_effect=call)

    def render(self, *, ai=None, ai_error=None, db_error=None):
        with self.fake_aws(ai=ai, ai_error=ai_error, db_error=db_error):
            runtime.render(self.args)
        return self.path.read_text(encoding="utf-8")

    def test_missing_optional_ai_secret_defaults_to_free(self):
        text = self.render(ai_error=MISSING)
        self.assertIn("LLM_LIVE='false'\n", text)
        self.assertNotIn("OPENAI_API_KEY=", text)
        self.assertEqual(len(self.calls), 2)

    def test_model_flags_quotes_dollars_and_backslashes_are_not_interpolated(self):
        ai = {
            "LLM_LIVE": "true",
            "OPENAI_API_KEY": CANARY,
            "OPENAI_AGENT_MODEL": "fake-model",
            "OPENAI_LIGHT_ROLES": "trade,guide",
            "OPENAI_REASONING_EFFORT": "high",
            "JEV_ENABLED": "false",
        }
        text = self.render(ai=ai)
        self.assertIn("LLM_LIVE='true'\n", text)
        self.assertIn("OPENAI_API_KEY='fake-only-$key\\'quote\\path'\n", text)
        self.assertIn("OPENAI_AGENT_MODEL='fake-model'\n", text)
        self.assertIn("OPENAI_LIGHT_ROLES='trade,guide'\n", text)
        self.assertNotIn("\nexport ", text)

    def test_compose_escaping_preserves_trailing_slashes_and_embedded_apostrophes(self):
        for value in (r"fake\'combo", "fake-trailing\\", "fake'\\"):
            with self.subTest(value="special-escape"):
                rendered = self.render(ai={"LLM_LIVE": "true", "OPENAI_API_KEY": value})
                self.assertIn(
                    "OPENAI_API_KEY=" + runtime._compose_value(value), rendered
                )
                self.assertTrue(runtime._compose_value(value).startswith('"'))
        double_slash = "fake\\\\'combo"
        self.assertTrue(runtime._compose_value(double_slash).startswith("'"))

    def test_secret_json_whitespace_is_allowed_but_values_cannot_contain_line_breaks(
        self,
    ):
        def pretty(command, **kwargs):
            secret_id = command[command.index("--secret-id") + 1]
            data = self.db if secret_id == DB_ID else {"LLM_LIVE": "false"}
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"SecretString": json.dumps(data, indent=2)}),
                "",
            )

        with patch.object(runtime.subprocess, "run", side_effect=pretty):
            runtime.render(self.args)
        self.assertIn("LLM_LIVE='false'", self.path.read_text(encoding="utf-8"))

    def test_db_url_credentials_are_percent_encoded(self):
        text = self.render(ai_error=MISSING)
        uri = (
            f"postgresql+asyncpg://{quote(self.db['username'], safe='')}:"
            f"{quote(self.db['password'], safe='')}@db.example.test:5432/mitjip"
        )
        self.assertIn(f"DATABASE_URL='{uri}'", text)
        self.assertNotIn(self.db["password"], text)

    def test_atomic_permissions_and_repeated_render_keep_ai_values(self):
        ai = {
            "LLM_LIVE": "true",
            "OPENAI_API_KEY": CANARY,
            "OPENAI_LIGHT_MODEL": "fake-mini",
        }
        first = self.render(ai=ai)
        self.calls.clear()
        second = self.render(ai=ai)
        self.assertEqual(first, second)
        self.assertEqual(len(self.calls), 2)
        if os.name == "posix":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_invalid_ai_json_and_access_denied_leave_old_file_untouched(self):
        self.path.write_text("previous release\n", encoding="utf-8")
        invalid = [
            {"LLM_LIVE": True},
            {"LLM_LIVE": "yes"},
            {"LLM_LIVE": "true"},
            {"LLM_LIVE": "false", "UNKNOWN_SETTING": CANARY},
            ["wrong JSON type"],
        ]
        for candidate in invalid:
            with self.subTest(candidate=type(candidate).__name__):
                with (
                    self.fake_aws(ai=candidate),
                    self.assertRaises(runtime.RuntimeConfigError),
                ):
                    runtime.render(self.args)
                self.assertEqual(
                    self.path.read_text(encoding="utf-8"), "previous release\n"
                )
        for error in [
            "An error occurred (AccessDeniedException) when calling the GetSecretValue operation: "
            + CANARY,
            "An error occurred (AccessDeniedException) when calling the GetSecretValue operation: "
            "(ResourceNotFoundException) " + CANARY,
            "An error occurred (AccessDeniedException) when calling the GetSecretValue operation:\n"
            + MISSING,
        ]:
            with self.subTest(error="access-denied"):
                with (
                    self.fake_aws(ai_error=error),
                    self.assertRaises(runtime.RuntimeConfigError),
                ):
                    runtime.render(self.args)
                self.assertEqual(
                    self.path.read_text(encoding="utf-8"), "previous release\n"
                )

    def test_bad_db_secret_and_ai_secret_cannot_be_skipped(self):
        self.path.write_text("previous release\n", encoding="utf-8")
        with (
            self.fake_aws(db_error=MISSING),
            self.assertRaises(runtime.RuntimeConfigError),
        ):
            runtime.render(self.args)
        with (
            self.fake_aws(ai_error="unrecognizable failure"),
            self.assertRaises(runtime.RuntimeConfigError),
        ):
            runtime.render(self.args)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "previous release\n")

    def test_newline_carriage_return_and_nul_injection_are_blocked(self):
        self.path.write_text("previous release\n", encoding="utf-8")
        for bad in ("\nLLM_LIVE=true", "\rLLM_LIVE=true", "\x00", "line\nbreak"):
            with self.subTest(bad=repr(bad)):
                with (
                    self.fake_aws(ai={"OPENAI_API_KEY": "fake" + bad}),
                    self.assertRaises(runtime.RuntimeConfigError),
                ):
                    runtime.render(self.args)
                self.assertEqual(
                    self.path.read_text(encoding="utf-8"), "previous release\n"
                )
        for bad in ("\n", "\r", "\x00"):
            with self.subTest(value_type="db", bad=repr(bad)):
                self.db["password"] = "fake" + bad + "value"
                with (
                    self.fake_aws(ai_error=MISSING),
                    self.assertRaises(runtime.RuntimeConfigError),
                ):
                    runtime.render(self.args)
                self.assertEqual(
                    self.path.read_text(encoding="utf-8"), "previous release\n"
                )

    def test_malformed_json_and_cli_errors_never_print_canaries(self):
        bad_output = json.dumps({"SecretString": "{not JSON " + CANARY})

        def cli_error(command, **kwargs):
            if command[command.index("--secret-id") + 1] == DB_ID:
                return response(self.db)
            return subprocess.CompletedProcess(
                command, 254, "", "AccessDeniedException " + CANARY
            )

        argv = [
            "--region",
            self.args.region,
            "--stack",
            self.args.stack,
            "--db-secret-id",
            self.args.db_secret_id,
            "--db-host",
            self.args.db_host,
            "--bucket",
            self.args.bucket,
            "--host",
            self.args.host,
            "--output",
            self.args.output,
        ]
        for fake in (
            cli_error,
            lambda command, **kwargs: (
                response(self.db)
                if command[command.index("--secret-id") + 1] == DB_ID
                else subprocess.CompletedProcess(command, 0, bad_output, "")
            ),
        ):
            with self.subTest(fake=fake):
                stderr, stdout = io.StringIO(), io.StringIO()
                with (
                    patch.object(runtime.subprocess, "run", side_effect=fake),
                    contextlib.redirect_stderr(stderr),
                    contextlib.redirect_stdout(stdout),
                ):
                    self.assertEqual(runtime.main(argv), 1)
                self.assertNotIn(CANARY, stderr.getvalue() + stdout.getvalue())
                self.assertFalse(self.path.exists())

    def test_temp_file_failure_does_not_overwrite_current_runtime(self):
        self.path.write_text("previous release\n", encoding="utf-8")
        with (
            patch.object(
                runtime.os, "replace", side_effect=OSError("fake failure " + CANARY)
            ),
            self.fake_aws(ai_error=MISSING),
            self.assertRaises(runtime.RuntimeConfigError) as caught,
        ):
            runtime.render(self.args)
        self.assertNotIn(CANARY, str(caught.exception))
        self.assertEqual(self.path.read_text(encoding="utf-8"), "previous release\n")
        self.assertEqual(list(self.path.parent.glob(".env.runtime.*")), [])


if __name__ == "__main__":
    unittest.main()

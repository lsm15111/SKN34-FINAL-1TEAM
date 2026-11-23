"""테스트 분배·집계와 실제 pytest의 실패 전파를 검증한다."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from ci_backend import run_context, select_shard, validate_report, verify

NODES = [f"tests/security/test_api.py::test_case[한글 공백 {i}]" for i in range(9)]


def make_report(shard, shards=4, collected=None):
    collected = NODES if collected is None else collected
    selected = select_shard(collected, shard, shards)
    return {
        "version": 1,
        "context": run_context(),
        "shard": shard,
        "shards": shards,
        "collected": list(collected),
        "selected": selected,
        "exit_code": 0,
        "outcomes": {
            node: [[phase, "passed"] for phase in ("setup", "call", "teardown")]
            for node in selected
        },
    }


class PartitionTests(unittest.TestCase):
    def test_partition_is_complete_disjoint_balanced_and_order_independent(self):
        for count in (1, 2, 4, 8, 9):
            with self.subTest(count=count):
                parts = [select_shard(NODES, i, count) for i in range(1, count + 1)]
                flattened = [node for part in parts for node in part]
                self.assertEqual(sorted(flattened), sorted(NODES))
                self.assertEqual(len(flattened), len(set(flattened)))
                self.assertLessEqual(max(map(len, parts)) - min(map(len, parts)), 1)
                self.assertEqual(parts[0], select_shard(list(reversed(NODES)), 1, count))

    def test_invalid_empty_duplicate_and_malformed_input_fails(self):
        cases = [
            (NODES, 0, 4),
            (NODES, 5, 4),
            (NODES, 1, 0),
            (NODES, True, 4),
            ([], 1, 4),
            (NODES, 10, 10),
            (["a", "a"], 1, 1),
            ([None], 1, 1),
        ]
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError):
                select_shard(*args)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.reports = [make_report(i) for i in range(1, 5)]

    def check(self, reports):
        for path in self.path.glob("*.json"):
            path.unlink()
        for i, report in enumerate(reports):
            (self.path / f"result-{i}.json").write_text(json.dumps(report), encoding="utf-8")
        return verify(self.path, 4)

    def test_complete_reports_pass(self):
        self.assertEqual(self.check(self.reports), len(NODES))

    def test_missing_extra_and_duplicate_shard_fail(self):
        cases = [
            self.reports[:-1],
            self.reports + [self.reports[0]],
            self.reports[:-1] + [self.reports[0]],
        ]
        for reports in cases:
            with self.subTest(count=len(reports)), self.assertRaises(ValueError):
                self.check(reports)

    def test_inconsistent_collection_fails_even_if_each_report_is_valid(self):
        reports = deepcopy(self.reports)
        reports[-1] = make_report(4, collected=NODES + ["tests/test_extra.py::test_new"])
        with self.assertRaisesRegex(ValueError, "전체 테스트 목록"):
            self.check(reports)

    def test_failed_skipped_incomplete_duplicate_and_unassigned_execution_fail(self):
        node = self.reports[0]["selected"][0]
        mutations = [
            lambda r: r.update(exit_code=1),
            lambda r: r.update(exit_code=False),
            lambda r: r["collected"].append(r["collected"][0]),
            lambda r: r["selected"].pop(),
            lambda r: r["selected"].append(r["selected"][0]),
            lambda r: r["outcomes"].pop(node),
            lambda r: r["outcomes"].update({"unassigned": []}),
            lambda r: r["outcomes"][node].pop(),
            lambda r: r["outcomes"][node].append(["call", "passed"]),
            lambda r: r["outcomes"][node].__setitem__(1, ["call", "skipped"]),
            lambda r: r["outcomes"][node].__setitem__(1, ["call", "failed"]),
            lambda r: r["outcomes"][node].__setitem__(1, ["call", "xfail"]),
            lambda r: r.update(shard=5),
            lambda r: r.update(shards=3),
            lambda r: r.update(context={"GITHUB_SHA": "other", "GITHUB_RUN_ID": "other"}),
        ]
        for i, mutate in enumerate(mutations):
            reports = deepcopy(self.reports)
            mutate(reports[0])
            with self.subTest(case=i), self.assertRaises(ValueError):
                self.check(reports)

    def test_malformed_report_and_missing_directory_fail(self):
        for report in (None, [], {}, {"version": 1}, {**self.reports[0], "outcomes": []}):
            with self.subTest(report=report), self.assertRaises(ValueError):
                validate_report(report, 4, run_context())
        with self.assertRaises(ValueError):
            verify(self.path / "missing", 4)
        with self.assertRaises(ValueError):
            verify(self.path, 0)
        self.check(self.reports)
        (self.path / "result-0.json").write_text("{", encoding="utf-8")
        with self.assertRaises(ValueError):
            verify(self.path, 4)

    def test_same_run_retry_allowed_but_other_sha_or_run_rejected(self):
        with patch.dict(
            os.environ, {"GITHUB_SHA": "abc", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1"}
        ):
            reports = [make_report(i) for i in range(1, 5)]
            with patch.dict(os.environ, {"GITHUB_RUN_ATTEMPT": "2"}):
                self.assertEqual(self.check(reports), len(NODES))
            for name in ("GITHUB_SHA", "GITHUB_RUN_ID"):
                with patch.dict(os.environ, {name: "other"}), self.assertRaises(ValueError):
                    self.check(reports)


def integration_suite():
    # repository-checks는 표준 라이브러리만 쓴다. 실제 pytest 검사는 backend 작업에서 실행한다.
    class PytestIntegrationTests(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory()
            self.addCleanup(self.temp.cleanup)
            self.path = Path(self.temp.name)
            (self.path / "tests" / "security").mkdir(parents=True)
            (self.path / "pytest.ini").write_text(
                "[pytest]\ntestpaths = tests\naddopts = -k impossible\n"
                "disable_test_id_escaping_and_forfeit_all_rights_to_community_support = True\n",
                encoding="utf-8",
            )

        def execute(self, source, shard=1, shards=1, extra_env=None):
            (self.path / "tests" / "security" / "test_sample.py").write_text(
                source, encoding="utf-8"
            )
            report = self.path / "reports" / f"shard-{shard}.json"
            env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": ""}
            env.update(extra_env or {})
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "ci_backend.py"),
                    "run",
                    "--shard",
                    str(shard),
                    "--shards",
                    str(shards),
                    "--report",
                    str(report),
                ],
                cwd=self.path,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            return result, report

        def test_real_parameterized_collection_is_exhaustive(self):
            source = (
                "import pytest\n@pytest.mark.parametrize('value', ['한글 공백', 'a::b[]', 'c'])\n"
                "def test_value(value):\n    assert value\n\n"
                "def test_other():\n    assert True\n"
            )
            for shard in (1, 2):
                result, _ = self.execute(source, shard, 2)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(verify(self.path / "reports", 2), 4)

        def test_random_values_require_stable_parameter_ids(self):
            for stable in (False, True):
                with self.subTest(stable=stable):
                    ids = ", ids=lambda value: value.replace(X, '{id}')" if stable else ""
                    source = (
                        "import uuid\nimport pytest\nX = str(uuid.uuid4())\n"
                        "@pytest.mark.parametrize('path', "
                        "[f'/threads/{X}', f'/projects/{X}', '/stream', '/reports']"
                        + ids
                        + ")\ndef test_path(path):\n    assert path.startswith('/')\n"
                    )
                    reports = []
                    for shard in (1, 2):
                        result, report = self.execute(
                            source, shard, 2, extra_env={"PYTHONHASHSEED": str(shard)}
                        )
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        reports.append(json.loads(report.read_text(encoding="utf-8")))
                    if stable:
                        self.assertEqual(reports[0]["collected"], reports[1]["collected"])
                        self.assertEqual(verify(self.path / "reports", 2), 4)
                    else:
                        self.assertNotEqual(reports[0]["collected"], reports[1]["collected"])
                        with self.assertRaisesRegex(ValueError, "전체 테스트 목록"):
                            verify(self.path / "reports", 2)

        def test_collection_error_replaces_previous_success(self):
            result, report = self.execute("def test_ok():\n    pass\n")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result, report = self.execute("def test_broken(:\n")
            self.assertNotEqual(result.returncode, 0)
            self.assertNotEqual(json.loads(report.read_text())["exit_code"], 0)
            with self.assertRaises(ValueError):
                verify(self.path / "reports", 1)

        def test_test_setup_teardown_skip_and_xfail_cannot_pass(self):
            sources = [
                "def test_fail():\n    assert False\n",
                (
                    "import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    raise RuntimeError()\n"
                    "def test_ok():\n    pass\n"
                ),
                (
                    "import pytest\n@pytest.fixture(autouse=True)\ndef setup():\n    yield\n"
                    "    raise RuntimeError()\ndef test_ok():\n    pass\n"
                ),
                "import pytest\n@pytest.mark.skip(reason='검증')\ndef test_skip():\n    pass\n",
                "import pytest\n@pytest.mark.xfail\ndef test_xfail():\n    assert False\n",
                "import pytest\n@pytest.mark.xfail\ndef test_xpass():\n    pass\n",
                "import pytest\ndef test_stop():\n    pytest.exit('stop', returncode=0)\n",
            ]
            for source in sources:
                with self.subTest(source=source):
                    result, _ = self.execute(source)
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    with self.assertRaises(ValueError):
                        verify(self.path / "reports", 1)

        def test_invalid_empty_and_external_filter_cannot_pass(self):
            source = "def test_ok():\n    pass\n"
            for shard, shards in ((0, 4), (5, 4), (1, 0), (2, 2)):
                with self.subTest(shard=shard, shards=shards):
                    result, _ = self.execute(source, shard, shards)
                    self.assertNotEqual(result.returncode, 0)
            result, report = self.execute(source, extra_env={"PYTEST_ADDOPTS": "-k nope"})
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(report.exists())
            for decorator in ("", "@pytest.hookimpl(trylast=True)\n"):
                (self.path / "tests" / "conftest.py").write_text(
                    "import pytest\n" + decorator + "def pytest_collection_modifyitems(items):\n"
                    "    items.clear()\n",
                    encoding="utf-8",
                )
                result, _ = self.execute(source)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    return unittest.defaultTestLoader.loadTestsFromTestCase(PytestIntegrationTests)


if __name__ == "__main__":
    if sys.argv[1:] == ["--integration"]:
        result = unittest.TextTestRunner(verbosity=2).run(integration_suite())
        raise SystemExit(not result.wasSuccessful())
    unittest.main()

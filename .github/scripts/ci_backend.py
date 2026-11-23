"""백엔드 테스트를 나누고 전체 실행 결과의 누락·중복을 차단한다."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def run_context() -> dict[str, str]:
    # 실패한 작업만 재실행하면 같은 실행의 이전 성공 결과도 함께 검증한다.
    return {name: os.environ.get(name, "") for name in ("GITHUB_SHA", "GITHUB_RUN_ID")}


def node_ids(value: object, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise ValueError(f"{label}: 비어 있거나 잘못된 테스트 목록")
    if len(value) != len(set(value)):
        raise ValueError(f"{label}: 중복 테스트")
    return sorted(value)


def select_shard(collected: list[str], shard: int, shards: int) -> list[str]:
    if type(shards) is not int or type(shard) is not int or not 1 <= shard <= shards:
        raise ValueError("분배 번호는 1 이상이고 전체 작업 수 이하여야 합니다")
    selected = node_ids(collected, "전체 수집")[shard - 1 :: shards]
    if not selected:
        raise ValueError("테스트가 없는 작업은 통과할 수 없습니다")
    return selected


def validate_report(report: object, shards: int, context: dict[str, str]) -> list[str]:
    if (
        not isinstance(report, dict)
        or type(report.get("version")) is not int
        or report["version"] != 1
    ):
        raise ValueError("잘못된 결과 형식")
    if type(report.get("exit_code")) is not int or report["exit_code"] != 0:
        raise ValueError("pytest가 성공하지 않았습니다")
    if type(report.get("shards")) is not int or report["shards"] != shards:
        raise ValueError("전체 작업 수가 다릅니다")
    if report.get("context") != context:
        raise ValueError("다른 커밋 또는 CI 실행의 결과입니다")
    collected = node_ids(report.get("collected"), "전체 수집")
    selected = node_ids(report.get("selected"), "배정")
    if selected != select_shard(collected, report.get("shard"), shards):
        raise ValueError("배정된 테스트 목록이 다릅니다")
    outcomes = report.get("outcomes")
    if not isinstance(outcomes, dict) or set(outcomes) != set(selected):
        raise ValueError("실제로 실행한 테스트가 배정과 다릅니다")
    expected = [[phase, "passed"] for phase in ("setup", "call", "teardown")]
    if any(phases != expected for phases in outcomes.values()):
        raise ValueError("실패·건너뜀·중복·미완료 테스트가 있습니다")
    return collected


class ShardPlugin:
    def __init__(self, shard: int, shards: int):
        self.shard = shard
        self.shards = shards
        self.collected: list[str] = []
        self.selected: list[str] = []
        self.outcomes: dict[str, list[list[str]]] = {}

    def pytest_itemcollected(self, item):
        self.collected.append(item.nodeid)

    def pytest_collection_modifyitems(self, items):
        # 필터가 일부 테스트를 제거했더라도 전체 수집 목록과 비교해 실패한다.
        if node_ids([item.nodeid for item in items], "수집 결과") != node_ids(
            self.collected, "전체 수집"
        ):
            raise ValueError("분배 전에 테스트가 제거됐습니다")
        self.selected = select_shard(self.collected, self.shard, self.shards)
        selected = set(self.selected)
        items[:] = [item for item in items if item.nodeid in selected]

    def pytest_collection_finish(self, session):
        if sorted(item.nodeid for item in session.items) != self.selected:
            raise ValueError("분배 뒤 테스트 목록이 바뀌었습니다")

    def pytest_runtest_logreport(self, report):
        # xfail과 xpass도 전체 테스트가 실제 통과한 것으로 세지 않는다.
        outcome = "xfail" if hasattr(report, "wasxfail") else report.outcome
        self.outcomes.setdefault(report.nodeid, []).append([report.when, outcome])


def run(shard: int, shards: int, report_path: Path) -> int:
    report_path.unlink(missing_ok=True)
    if type(shards) is not int or type(shard) is not int or not 1 <= shard <= shards:
        raise ValueError("잘못된 분배 번호 또는 작업 수")
    if os.environ.get("PYTEST_ADDOPTS"):
        raise ValueError("CI 분배 실행에는 PYTEST_ADDOPTS를 사용할 수 없습니다")
    import pytest

    plugin = ShardPlugin(shard, shards)
    # testpaths는 프로젝트 설정을 따르고 외부의 추가 선택 옵션은 받지 않는다.
    exit_code = int(pytest.main(["-q", "--durations=20", "-o", "addopts="], plugins=[plugin]))
    report = {
        "version": 1,
        "context": run_context(),
        "shard": shard,
        "shards": shards,
        "collected": sorted(plugin.collected),
        "selected": plugin.selected,
        "outcomes": plugin.outcomes,
        "exit_code": exit_code,
    }
    if exit_code == 0:
        try:
            validate_report(report, shards, run_context())
        except ValueError as exc:
            print(f"백엔드 분배 검사 실패: {exc}", file=sys.stderr)
            report["exit_code"] = exit_code = 1
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"백엔드 작업 {shard}/{shards}: 전체 {len(plugin.collected)}개, 배정 {len(plugin.selected)}개"
    )
    return exit_code


def verify(reports_path: Path, shards: int) -> int:
    if type(shards) is not int or shards < 1:
        raise ValueError("잘못된 전체 작업 수")
    paths = sorted(reports_path.glob("*.json"))
    if len(paths) != shards:
        raise ValueError(f"결과 파일이 {shards}개여야 합니다: 현재 {len(paths)}개")
    collection: list[str] | None = None
    seen_shards: set[int] = set()
    executed: set[str] = set()
    for path in paths:
        report = json.loads(path.read_text(encoding="utf-8"))
        collected = validate_report(report, shards, run_context())
        if collection is not None and collected != collection:
            raise ValueError("작업마다 수집한 전체 테스트 목록이 다릅니다")
        collection = collected
        if report["shard"] in seen_shards:
            raise ValueError("같은 작업의 결과가 중복됐습니다")
        seen_shards.add(report["shard"])
        selected = set(report["selected"])
        if executed & selected:
            raise ValueError("여러 작업에서 같은 테스트를 실행했습니다")
        executed.update(selected)
    if seen_shards != set(range(1, shards + 1)) or executed != set(collection or []):
        raise ValueError("전체 테스트에서 실행하지 않은 항목이 있습니다")
    print(f"백엔드 {shards}개 작업 검증 완료: {len(executed)}개 테스트 통과, 누락·중복 없음")
    return len(executed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--shard", type=int, required=True)
    run_parser.add_argument("--shards", type=int, required=True)
    run_parser.add_argument("--report", type=Path, required=True)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--shards", type=int, required=True)
    verify_parser.add_argument("--reports", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "run":
            return run(args.shard, args.shards, args.report)
        verify(args.reports, args.shards)
        return 0
    except (ValueError, OSError) as exc:
        print(f"백엔드 분배 검사 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

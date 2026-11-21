"""Claude 엄격 도구 한도: 한 요청에 엄격 도구 20개 · 엄격 스키마 선택 칸 합 24개까지(넘으면 400).
2026-11-21 고객 도구가 24개가 되어 비서 본 호출이 모두 400('Too many strict tools')이었어요."""

import pytest

from app.agent import llm
from app.assistant import tools

OPTIONAL_MAX = 24


def _optional(schema: dict) -> int:
    n = 0
    if schema.get("type") == "object" and "properties" in schema:
        req = set(schema.get("required", []))
        n += sum(1 for k in schema["properties"] if k not in req)
        n += sum(_optional(v) for v in schema["properties"].values() if isinstance(v, dict))
    if isinstance(schema.get("items"), dict):
        n += _optional(schema["items"])
    return n


@pytest.mark.parametrize("surface", ["customer", "vendor"])
def test_strict_tools_within_claude_limits(surface):
    out = llm.to_claude_tools(tools.defs(surface))
    strict = [t for t in out if t.get("strict")]
    assert len(strict) <= tools.STRICT_MAX, [t["name"] for t in strict]
    assert sum(_optional(t["input_schema"]) for t in strict) <= OPTIONAL_MAX
    # 제안 도구(승인 카드)는 모두 엄격, 읽기 도구는 엄격이 아니에요
    kinds = {t.name: t.kind for t in tools.REGISTRY.values() if t.surface == surface}
    assert {t["name"] for t in strict} == {n for n, k in kinds.items() if k == "propose"}
    assert all("strict" not in t or t["strict"] is True for t in out)

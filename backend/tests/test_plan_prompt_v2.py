"""공정 의견 프롬프트 v2: 공정마다 다른 줄 + 공통 규칙. 지금 스펙은 v1을 쓰고, 유료 평가로 비교한 뒤 바꾼다."""

import pytest

from app.agent.trade import TradeAgent, prompt_text
from app.consult.trades import REGISTRY


@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_v2_prompt_has_trade_lines_and_shared_rules(key):
    name = REGISTRY[key].agent.name
    v1, v2 = prompt_text(f"{name}_v1.md"), prompt_text(f"{name}_v2.md")
    assert "{{" not in v2 and "지킬 것:" in v2
    # 공정마다 다른 줄(역할 · 요약 · 실측 후 줄)은 v1에서 그대로 옮긴다
    for line in v1.splitlines():
        if line.startswith(("너는 믿집의", "- summary:")):
            assert line in v2
    # v2에서 고친 공통 규칙: 빈집 짐 이야기 금지 · 어려운 말 풀이 · 개수를 채우지 않기
    assert "빈집이면 짐 이야기를 아예 하지 마" in v2 and "쉬운 풀이" in v2
    assert "셋에서 다섯 개" in v2 and "둘에서 세 개" in v2
    agent = TradeAgent.load(name, REGISTRY[key].label, f"{name}_v2.md")
    assert agent.plan_prompt_version == f"{name}-v2"
    assert agent.sources == REGISTRY[key].agent.sources

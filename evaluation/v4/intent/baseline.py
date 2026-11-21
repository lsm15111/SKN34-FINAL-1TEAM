"""지금 무료 모드 길(v3 입구 관문 → step_card)을 v4 라벨 · 카드로 옮기기(LLM 0회 · DB 없음).

- 길은 gate.gate(글, has_project=True)예요. free_turn과 같아요(고객 공사가 있는 화면).
- 길 → 카드는 step_card 그대로: guide · multi → today, quote_explanation → 받은 견적서가 있으면 견적서 비교, 없으면
  표준견적서, schedule → schedule, trade · out_of_scope · ask_back → 카드 없음(답 카드만).
- quote_explanation은 상태에 따라 두 카드 중 하나라서, 정답이 둘 중 하나면 맞은 것으로 쳐요(기준선에 유리하게).
  라벨로 셀 때도 같아요. ask_back은 라벨 없음(None)이에요.
"""

from app.agent.v3 import gate as gate_mod

ROUTE_CARDS: dict[str, set] = {
    "guide": {"today"}, "multi": {"today"}, "quote_explanation": {"standard_quote", "quote_compare"},
    "schedule": {"schedule"}, "trade": {None}, "out_of_scope": {None}, "ask_back": {None},
}  # fmt: skip
ROUTE_LABEL: dict[str, str | None] = {
    "guide": "guide", "multi": "guide", "trade": "knowledge", "schedule": "schedule",
    "out_of_scope": "out_of_scope", "ask_back": None,
}  # fmt: skip
QUOTES = ("standard_quote", "quote_compare")


def route_of(text: str) -> tuple[str, float]:
    g = gate_mod.gate(text, has_project=True)
    return g.route, float(g.confidence)


def label_of(route: str, gold: str) -> str | None:
    if route == "quote_explanation":
        return gold if gold in QUOTES else "standard_quote"
    return ROUTE_LABEL[route]


def run(rows: list[dict]) -> dict:
    out: dict = {"pred": [], "cards": [], "conf": [], "route": []}
    for r in rows:
        route, conf = route_of(r["text"])
        out["route"].append(route)
        out["pred"].append(label_of(route, r["label"]))
        out["cards"].append(ROUTE_CARDS[route])
        out["conf"].append(conf)
    return out

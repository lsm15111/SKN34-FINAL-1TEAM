"""라우터 출력(RouterOut) 코드 채점. 라우터가 뽑은 값을 상담 코드(apply_route · normalize)로 카드에 넣어 보고,
바뀐 칸을 기대와 견준다. 그래서 같은 뜻을 다르게 낸 출력(예: multi 칸 set · add)은 같게 친다.

바뀐 칸(effect): 칸 이름 → 바뀐 뒤 값
- trades: 공정을 더하거나 빼면 바뀐 뒤 공정 목록 ('+'로 이음)
- 공통 칸: area_m2 · area_basis · occupied · balcony_ext · built_year
- 공정 칸: "공정.칸". 여러 개 고른 값은 '+'로 잇고, '모르겠어요'로 기본값을 넣은 칸(to_check)은 "unknown"
- 조건이 꺼져 지워진 칸은 None (예: 방문을 빼면 방문 개수)

공정 더하기 · 빼기(trades_add · trades_remove)는 라우터 v5부터 있다. 스키마에 칸이 없으면(기준 커밋) 원문 dict에서
읽고, v5 apply_trades와 같은 규칙(등록된 공정만 더하고 하나는 남긴다)으로 칸보다 먼저 넣는다.
"""

from decimal import Decimal

from app.agent.consult import reply_ok
from app.agent.schemas import RouterOut
from app.agent.trade import NUMBER_CLAIM
from app.consult import service
from app.consult.schemas import ConsultCard
from app.consult.trades import ORDER, REGISTRY
from evaluation.scorers.rules import bad_endings, sentences

HAS_TRADES = "trades_add" in RouterOut.model_fields  # 라우터 v5부터
CHECKS = {
    "effect_exact": "바뀐 칸이 기대와 똑같음",
    "no_invented": "말하지 않은 칸 · 공정을 바꾸지 않음",
    "no_missed": "말한 칸을 빠짐없이 맞게 바꿈",
    "trades_exact": "공정 더하기 · 빼기가 기대와 같음 (묻기만 하면 더하지 않음)",
    "raw_trades": "더하기는 카드에 없는 목록 공정, 빼기는 카드 공정만",
    "raw_in_card": "변경은 카드 공정(이번에 더한 공정 포함) 칸만",
    "raw_valid": "변경 값이 칸 선택지 · 범위 안",
    "questions_exact": "공정별 질문 나누기가 기대와 같음",
    "out_of_scope": "범위 밖 판단이 맞음",
    "reply_ok": "답 300자 이하 · 지어낸 금액 · 기간 · 면적 없음",
    "reply_style": "답이 '-해요'체",
    "reply_no_ask": "되묻지 않음 (물음표로 끝나지 않음)",
    "reply_empty_when_asked": "질문을 넘기면 답은 빈 글",
    "reply_guides": "업체 소개 · 견적 요청이면 '가견적 받기'를 안내함",
}


def trade_lists(out: RouterOut, raw: dict | None = None) -> tuple[list[str], list[str]]:
    """(더할 공정, 뺄 공정). 스키마에 칸이 없으면(기준 커밋) 원문에서 읽는다"""
    raw = raw or {}
    add, rem = getattr(out, "trades_add", None), getattr(out, "trades_remove", None)
    if add is None:
        add = raw.get("trades_add") or []
    if rem is None:
        rem = raw.get("trades_remove") or []
    return list(add), list(rem)


def _apply_trades(c: ConsultCard, add: list[str], remove: list[str]) -> ConsultCard:
    """라우터 v5 service.apply_trades와 같은 규칙 (기준 커밋에는 없어서 여기서 넣는다)"""
    picked = (set(c.trades) | {k for k in add if k in REGISTRY}) - set(remove)
    keep = [k for k in ORDER if k in picked]
    if not keep or keep == c.trades:
        return c
    return c.model_copy(update={"trades": keep})


def apply(card: ConsultCard, out: RouterOut, raw: dict | None = None) -> ConsultCard:
    """상담과 같게 라우터 값을 카드에 넣는다 (공정 먼저, 스펙에 맞지 않는 값은 버린다)."""
    if not HAS_TRADES:
        add, rem = trade_lists(out, raw)
        card = _apply_trades(card, add[:10], rem[:10])
    return service.normalize(service.apply_route(card, out))


def _basis(c: ConsultCard) -> str | None:
    return "unknown" if "area_basis" in c.to_check else c.area_basis


def _value(c: ConsultCard, trade: str, key: str):
    if f"{trade}.{key}" in c.to_check:
        return "unknown"
    v = c.values.get(trade, {}).get(key)
    return "+".join(v) if isinstance(v, list) else v


def effect(before: ConsultCard, after: ConsultCard) -> dict:
    out: dict = {}
    if before.trades != after.trades:
        out["trades"] = "+".join(after.trades)
    for k in ("area_m2", "occupied", "balcony_ext", "built_year"):
        a, b = getattr(before, k), getattr(after, k)
        if a != b:
            out[k] = str(b) if isinstance(b, Decimal) else b
    if _basis(before) != _basis(after):
        out["area_basis"] = _basis(after)
    for t in after.trades:
        keys = set(before.values.get(t, {})) | set(after.values.get(t, {}))
        for k in sorted(keys):
            if _value(before, t, k) != _value(after, t, k):
                out[f"{t}.{k}"] = _value(after, t, k)
    return out


def trade_ops(before: list[str], after: list[str]) -> set[str]:
    """공정 목록 차이 → {'+floor', '-mokgong'}"""
    b, a = set(before), set(after)
    return {f"+{k}" for k in a - b} | {f"-{k}" for k in b - a}


def raw_change_ok(allowed: set[str], ch: dict) -> tuple[bool, bool]:
    """(카드 공정 칸인지, 값이 칸에 맞는지). allowed: 공정을 더하고 뺀 뒤의 카드 공정"""
    trade, _, key = (ch.get("field") or "").partition(".")
    spec = REGISTRY.get(trade)
    f = spec.field(key) if spec else None
    if f is None or trade not in allowed:
        return False, False
    value, op = str(ch.get("value", "")).strip(), ch.get("op")
    try:
        if op == "set":
            raw: str | list[str] = value
            if f.kind == "multi" and value != "unknown":
                raw = [x.strip() for x in value.split(",") if x.strip()]
            f.read(raw)
        elif op in ("add", "remove") and f.kind == "multi":
            if value not in f.values:
                return True, False
        else:
            return True, False
    except ValueError:
        return True, False
    return True, True


def score(case: dict, raw: dict) -> dict:
    """{'checks': {검사 id: 통과}, 'counts': {tp · fp · fn · q_* · t_*}, 'effect': 바뀐 칸, 'detail'}"""
    card = ConsultCard.model_validate(case["input"]["card"])
    exp = case["expect"]
    out = RouterOut.model_validate(raw)
    after = apply(card, out, raw)
    got = effect(card, after)
    want = exp["effect"]
    checks: dict[str, bool] = {}
    detail: dict[str, str] = {}

    def put(cid: str, ok: bool, why: str = "") -> None:
        checks[cid] = ok
        if not ok and why:
            detail[cid] = why

    pg, pw = set(got.items()), set(want.items())
    invented = sorted(set(got) - set(want))
    missed = sorted(k for k in want if got.get(k, "∅") != want[k])
    put("effect_exact", got == want, f"얻음 {got} · 기대 {want}")
    put("no_invented", not invented, f"말하지 않은 칸 {invented}")
    put("no_missed", not missed, f"빠지거나 틀린 칸 {missed}")
    gt = trade_ops(card.trades, after.trades)
    wt = trade_ops(card.trades, want["trades"].split("+") if "trades" in want else card.trades)
    put("trades_exact", gt == wt, f"얻음 {sorted(gt)} · 기대 {sorted(wt)}")
    add, rem = trade_lists(out, raw)
    put(
        "raw_trades",
        all(k in REGISTRY and k not in card.trades for k in add)
        and all(k in card.trades for k in rem),
        f"더하기 {add} · 빼기 {rem}",
    )
    raw_ok = [raw_change_ok(set(after.trades), ch) for ch in raw.get("changes") or []]
    put("raw_in_card", all(a for a, _ in raw_ok), "카드에 없는 공정 · 칸을 바꾸려 함")
    put("raw_valid", all(b for _, b in raw_ok), "선택지 · 범위 밖 값")
    asked = {q["trade"] for q in raw.get("questions") or [] if q.get("trade") in REGISTRY}
    wq = set(exp["questions"])
    put("questions_exact", asked == wq, f"얻음 {sorted(asked)} · 기대 {sorted(wq)}")
    put("out_of_scope", bool(raw.get("out_of_scope")) == exp["out_of_scope"])
    reply = (raw.get("reply") or "").strip()
    put(
        "reply_ok",
        not reply or reply_ok(reply),
        f"{len(reply)}자" + (" · 숫자 주장" if NUMBER_CLAIM.search(reply) else ""),
    )
    put("reply_style", not bad_endings(sentences(reply)), reply[-30:])
    put("reply_no_ask", not reply.rstrip().endswith("?"), reply[-30:])
    put("reply_empty_when_asked", not (wq and reply), reply[:30])
    need = exp.get("reply_has") or []
    put("reply_guides", all(w in reply for w in need), f"'{' · '.join(need)}' 없음: {reply[:40]}")
    counts = {
        "tp": len(pg & pw),
        "fp": len(pg - pw),
        "fn": len(pw - pg),
        "q_tp": len(asked & wq),
        "q_fp": len(asked - wq),
        "q_fn": len(wq - asked),
        "t_tp": len(gt & wt),
        "t_fp": len(gt - wt),
        "t_fn": len(wt - gt),
    }
    return {"checks": checks, "counts": counts, "effect": got, "detail": detail}

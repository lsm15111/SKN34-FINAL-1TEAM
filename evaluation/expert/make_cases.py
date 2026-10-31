"""전문가 답 평가 사례 약 5,000개를 만든다. 등록된 공정마다 주제 10개(종류 비교 · 고르기 · 실측 · 비용 · 기간 ·
주의점 · 순서 · 살면서 공사 · 이 공정 밖의 일 · 업계 말)로 질문을 만들고 시드를 고정한다.

- 범주 = 공정.주제 (도배 · 목공이면 20개 × 249: dev 166 · held-out 83). 범주 안에서 거리(무엇을 묻는지)는
  고르게, 카드 상태(덜 참 · 다 참) · 카드에 그 공정이 있는지 · 집 이야기 앞말 · 잡음은 값마다 고르게 채운다
- 질문: 손으로 쓴 질문(phrases.BANK)과 스펙 · 지식에서 뽑은 말을 넣은 질문(GENERIC). 이 공정 밖의 일은 지식
  '쓰는 법'의 범위 밖 목록, 업계 말은 terms.py 용어 중 그 공정 지식에 나오는 것. 새 공정은 GENERIC만으로도 만든다
- 묶음마다 조각 3개 중 1개는 held-out 전용이라 두 나눔이 같은 질문 조각을 쓰지 않는다
- 입력은 상담과 같다: 카드 → consult.service.facts로 만든 집 정보(그 공정 칸 + 공통 칸) + 질문 한 문장
- 기대: 답에 있어야 할 핵심 말(groups)과 모범 답(무료 점검 · 가짜 LLM용)
- 근사 중복: 나눔 · 범주마다 질문 + 집 정보 글자 3-gram Jaccard 0.8 이상이면 다시 뽑는다

실행 (저장소 루트에서): cd backend && uv run python ../evaluation/expert/make_cases.py
→ evaluation/expert/cases_5k.jsonl (커밋 안 함) · sample_100.jsonl (커밋)
"""

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from evaluation.common import gen, house, trades
from evaluation.expert import phrases as P
from evaluation.expert.score import score
from evaluation.scorers.terms import TERMS
from evaluation.scorers.trade_plan import choice_words

TOTAL = 5000
TRIES = 30  # 근사 중복을 피해 다시 뽑는 횟수
FULL = HERE / "cases_5k.jsonl"
SAMPLE = HERE / "sample_100.jsonl"
NOISE = (
    "partial_space",
    "add_space",
    "spelling",
    "yeo",
    "tail",
)  # 라우터가 넘긴 한 문장: 가벼운 잡음만


class Retry(Exception):
    """이 설계로는 사례를 못 만든다 (다시 뽑는다)"""


@dataclass(frozen=True)
class Subject:
    key: str
    questions: tuple[str, ...]  # 질문 조각 (번호 % 3 == 2는 held-out)
    groups: tuple[str, ...]  # 답에 있어야 할 말 (정규식, 모두)
    ideal: str  # 모범 답


# ---------------------------------------------------------------- 말 만들기
def plain(label: str) -> str:
    """화면 말에서 괄호 설명을 뗀다"""
    return re.sub(r"\s*\(.*?\)", "", label).strip()


def marks(name: str, word: str) -> dict[str, str]:
    """{name} 자리와 받침에 맞춘 조사 자리 ({name}_은 · _이 · _을 · _과 · _랑 · _으로 · _이라고)"""
    ch = re.sub(r"\(.*\)$", "", word).strip()[-1]
    jong = (ord(ch) - 0xAC00) % 28 if "가" <= ch <= "힣" else 0
    has = bool(jong)
    return {
        name: word,
        f"{name}_은": "은" if has else "는",
        f"{name}_이": "이" if has else "가",
        f"{name}_을": "을" if has else "를",
        f"{name}_과": "과" if has else "와",
        f"{name}_랑": "이랑" if has else "랑",
        f"{name}_으로": "으로" if has and jong != 8 else "로",  # ㄹ 받침은 '로'
        f"{name}_이라고": "이라고" if has else "라고",
    }


def say(tpl: str, **words: str) -> str:
    kw: dict[str, str] = {}
    for k, v in words.items():
        kw |= marks(k, v)
    return tpl.format(**kw)


def alt(words: list[str]) -> str:
    return "|".join(re.escape(w) for w in words)


def scope_items(trade: str) -> list[str]:
    """지식 '쓰는 법'의 범위 밖 목록 (예: '단열 · 방수 · … · 결제는 판단하지 않고')"""
    for line in trades.knowledge(trade).splitlines():
        if "판단하지 않" in line:
            head = line.split("판단하지 않")[0].strip()
            m = re.search(r"\(([^()]*)\)\s*(?:은|는)$", head)
            text = m.group(1) if m else re.split(r"[.:]\s+", head)[-1]
            text = re.sub(r"\s*(?:은|는)$", "", text).lstrip("- ")
            return [x.strip() for x in text.split(" · ") if x.strip()]
    return []


def term_words(trade: str) -> list[str]:
    """그 공정 지식에 나오는 업계 말 (낱말 하나인 용어만)"""
    kn = trades.knowledge(trade)
    return [
        k
        for k, t in TERMS.items()
        if " " not in k and (not t.trades or trade in t.trades) and t.pattern.search(kn)
    ]


# ---------------------------------------------------------------- 거리 (무엇을 묻는지)
def _subject(key: str, qs: list[str], groups: list[str], ideal: str) -> Subject:
    return Subject(key, tuple(dict.fromkeys(qs)), tuple(groups), ideal)


def _generic(trade: str, topic: str) -> list[Subject]:
    sp, t = trades.spec(trade), trades.label(trade)
    tg = P.TOPIC_GROUPS.get(topic, [])
    gen_q = P.GENERIC[topic]
    out: list[Subject] = []
    if topic == "compare":
        for f in sp.fields:
            if f.kind != "choice" or len(f.choices) < 2:
                continue
            a, b = f.choices[0], f.choices[1]
            if plain(a.label).endswith("요") or plain(b.label).endswith("요"):
                continue
            words = choice_words(f, (sp.label,))
            qs = [say(x, a=plain(a.label), b=plain(b.label)) for x in gen_q]
            groups = [alt(words[a.value]), alt(words[b.value])]
            out.append(_subject(f.key, qs, groups, say(P.IDEAL["compare"], a=a.label, b=b.label)))
    elif topic == "choose":
        for f in sp.fields:
            if f.kind not in ("choice", "multi") or len(f.choices) < 2:
                continue
            words = choice_words(f, (sp.label,))
            first = words[f.choices[0].value][0]
            qs = [say(x, f=f.label) for x in gen_q]
            groups = [alt([w for ws in words.values() for w in ws])]
            out.append(_subject(f.key, qs, groups, say(P.IDEAL["choose"], f=f.label, a=first)))
    elif topic == "scope":
        for x in scope_items(trade):
            tpls = P.GENERIC["scope_admin"] if re.search(r"계약|결제", x) else gen_q
            qs = [say(q, x=x, t=t) for q in tpls]
            out.append(_subject(x, qs, tg, say(P.IDEAL["scope"], x=x, t=t)))
    elif topic == "term":
        for w in term_words(trade):
            term = TERMS[w]
            qs = [say(q, w=w) for q in gen_q]
            out.append(
                _subject(w, qs, [term.gloss.pattern], say(P.IDEAL["term"], w=w, e=term.easy))
            )
    else:
        qs = [say(q, t=t) for q in gen_q]
        out.append(_subject("general", qs, tg, say(P.IDEAL[topic], t=t)))
    return out


@cache
def subjects(trade: str, topic: str) -> dict[str, Subject]:
    """그 공정 · 주제의 거리 → Subject. 손으로 쓴 묶음이 있으면 먼저 쓰고, 모범 답이 채점을 못 지나는 거리는 뺀다"""
    t = trades.label(trade)
    hand = {k[2]: v for k, v in P.BANK.items() if k[:2] == (trade, topic)}
    tg = P.TOPIC_GROUPS.get(topic, [])
    out: list[Subject] = []
    if hand and topic in ("compare", "choose"):
        for key, b in hand.items():
            out.append(_subject(key, b["q"], b["groups"] + tg, b["ideal"]))
    elif "general" in hand:  # 손으로 쓴 질문 + 공정 이름을 넣은 질문
        b = hand["general"]
        qs = b["q"] + [say(q, t=t) for q in P.GENERIC[topic]]
        out.append(_subject("general", qs, b["groups"] + tg, say(P.IDEAL[topic], t=t)))
    else:
        out = _generic(trade, topic)
    known = trades.sources(trade)
    src = ["field"] if "field" in known else list(known)[:1]
    ok = {}
    for s in out:
        case = {"trade": trade, "expect": {"groups": list(s.groups)}}
        good = all(score(case, {"answer": s.ideal, "sources": src})["checks"].values())
        if good and len(s.questions) >= 3:
            ok[s.key] = s
    return ok


@cache
def bank(trade: str) -> gen.Fragments:
    """질문 조각 묶음: '공정.주제.거리' → 질문들, 'clause:종류' → 집 이야기 앞말"""
    table = {
        f"{trade}.{topic}.{k}": list(s.questions)
        for topic in P.TOPICS
        for k, s in subjects(trade, topic).items()
    }
    return gen.Fragments(table | {f"clause:{k}": v for k, v in P.CLAUSE.items()})


def categories() -> list[tuple[str, str]]:
    return [(t, topic) for t in trades.registered() for topic in P.TOPICS if subjects(t, topic)]


def ideal(trade: str, topic: str, key: str) -> dict:
    known = trades.sources(trade)
    src = ["field"] if "field" in known else list(known)[:1]
    return {"answer": subjects(trade, topic)[key].ideal, "sources": src}


# ---------------------------------------------------------------- 사례
def clauses(c) -> list[str]:
    """카드 값과 맞는 집 이야기 앞말 종류"""
    out = []
    if c.occupied is not None:
        out.append("occupied_yes" if c.occupied else "occupied_no")
    if c.balcony_ext:
        out.append("balcony")
    if c.built_year and c.built_year < 2000:
        out.append("old")
    return out


def build_case(r, trade: str, topic: str, row: dict) -> tuple[dict, list[str]]:
    used: list[str] = []
    split, frag = row["split"], bank(trade)
    others = [k for k in trades.registered() if k != trade]
    if row["in_card"] == "yes":
        picked = [trade, *r.sample(others, min(len(others), r.choice((0, 0, 1, 2))))]
    else:
        picked = r.sample(others, min(len(others), r.choice((1, 1, 2))))
    raw = house.random_card(r, picked, row["state"] == "full")
    if topic == "living" and raw["occupied"] is False:  # '살면서 해도 돼요?'와 빈집이 어긋나지 않게
        raw["occupied"] = r.choice((True, None))
    c = trades.card({"card": raw})
    q = frag.pick(r, f"{trade}.{topic}.{row['subject']}", split, used)
    if row["clause"] == "house":
        kinds = [k for k in clauses(c) if not (topic == "living" and k.startswith("occupied"))]
        if not kinds:
            raise Retry
        q = f"{frag.pick(r, 'clause:' + r.choice(kinds), split, used)} {q}"
    if row["noise"] == "noisy":
        q, _ = gen.noisy(q, r, k=1, ops=NOISE)
    card = c.model_dump(mode="json")
    return {"card": card, "context": trades.expert_text(c, trade), "question": q}, used


def build(total: int = TOTAL) -> tuple[list[dict], dict]:
    r = gen.rng("expert")
    cats = categories()
    per = max(3, total // len(cats) // 3 * 3)
    near = gen.NearDup(0.8, keep_numbers=True)
    in_card = ("yes", "no") if len(trades.registered()) > 1 else ("yes",)
    extra = {
        "state": ("partial", "full"),
        "in_card": in_card,
        "clause": ("none", "house"),
        "noise": ("none", "noisy"),
    }
    stats: Counter = Counter()
    seen: set[str] = set()
    cases: list[dict] = []
    for trade, topic in cats:
        cat = f"{trade}.{topic}"
        rows = gen.balanced_rows(r, per, {"subject": tuple(subjects(trade, topic))}, extra)
        gen.assign_splits(rows, group=lambda x: x["subject"])
        for row in rows:
            for attempt in range(300):
                try:
                    inp, tpl = build_case(r, trade, topic, row)
                except Retry:
                    stats["retry"] += 1
                    continue
                key = json.dumps(inp, sort_keys=True, ensure_ascii=False)
                if key in seen:
                    stats["dup"] += 1
                    continue
                if near.add(inp["question"] + "\n" + inp["context"], (row["split"], cat)):
                    break
                stats["near"] += 1
                if attempt >= TRIES:  # 집 정보가 짧아 겹치기 쉬운 범주: 말은 비슷해도 남긴다
                    stats[f"near_kept:{cat}"] += 1
                    break
            else:
                raise SystemExit(f"{cat}: 사례를 만들지 못했어요")
            seen.add(key)
            subj = subjects(trade, topic)[row["subject"]]
            strata = {k: v for k, v in row.items() if k != "split"}
            strata["trades"] = "+".join(inp["card"]["trades"])
            cases.append(
                {
                    "trade": trade,
                    "split": row["split"],
                    "category": cat,
                    "topic": topic,
                    "strata": strata,
                    "input": inp,
                    "expect": {
                        "groups": list(subj.groups),
                        "ideal": ideal(trade, topic, row["subject"]),
                    },
                    "tpl": tpl,
                }
            )
    return gen.number_cases(cases, "ex"), dict(stats)


def sample(cases: list[dict], n: int = 100) -> list[dict]:
    return gen.sample_2to1(cases, n, key=lambda c: c["category"])


def report(cases: list[dict], smp: list[dict], stats: dict) -> str:
    tpl = {s: {x for c in cases if c["split"] == s for x in c["tpl"]} for s in gen.SPLITS}
    qs = {s: {c["input"]["question"] for c in cases if c["split"] == s} for s in gen.SPLITS}
    kept = {k: v for k, v in sorted(stats.items()) if k.startswith("near_kept:")}
    nsub = Counter()
    for cat, s in {(c["category"], c["strata"]["subject"]) for c in cases}:
        nsub[cat] += 1
    parts = [
        gen.count_table(cases, "category", "범주"),
        *(gen.count_table(cases, f"strata.{k}") for k in ("in_card", "state", "clause", "noise")),
        "범주별 거리 수: " + ", ".join(f"{k} {v}" for k, v in sorted(nsub.items())),
        (
            f"질문 조각: dev {len(tpl['dev'])}개 · held-out {len(tpl['heldout'])}개, "
            f"두 나눔이 같이 쓴 조각 {len(tpl['dev'] & tpl['heldout'])}개"
        ),
        (
            f"서로 다른 질문: dev {len(qs['dev'])}개 · held-out {len(qs['heldout'])}개 · "
            f"두 나눔에 같이 나온 질문 {len(qs['dev'] & qs['heldout'])}개"
        ),
        (
            f"다시 뽑음: 설계가 안 맞음 {stats.get('retry', 0)}번 · 같은 입력 {stats.get('dup', 0)}번 · "
            f"근사 중복 {stats.get('near', 0)}번"
        ),
        f"근사 중복을 {TRIES}번 안에 못 피해 남긴 사례: "
        + (", ".join(f"{k.split(':')[1]} {v}" for k, v in kept.items()) or "없음"),
        "표본 100: "
        + ", ".join(f"{k} {v}" for k, v in sorted(Counter(c["split"] for c in smp).items())),
    ]
    return "\n\n".join(parts)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows 콘솔에서도 한글이 깨지지 않게
        stream.reconfigure(encoding="utf-8")
    cases, stats = build()
    smp = sample(cases)
    gen.write_jsonl(FULL, cases)
    gen.write_jsonl(SAMPLE, smp)
    assert gen.read_jsonl(FULL) == cases, "다시 읽은 사례가 달라요"
    print(
        f"저장: {FULL.relative_to(ROOT)} ({len(cases)}개) · {SAMPLE.relative_to(ROOT)} ({len(smp)}개)"
    )
    print()
    print(report(cases, smp, stats))


if __name__ == "__main__":
    main()

"""v4 비서 글 점검(피클 원칙 + 믿집 규칙, docs/v4/06-answer-audit.md). 표준 라이브러리만 써요(LLM · DB 없음).

- check(text, kind): 글 하나의 규칙 위반(Hit) 목록. kind는 글이 보이는 자리예요.
  - answer: 대화 답(LLM 턴 글 · 무료 모드 정해 둔 글 · 실패 글). 두세 문장(3문장까지).
  - line: 먼저 말 걸기 · 업체 브리핑 한 줄 · 카드 위 한 줄. 60자 한 줄.
  - note: 카드 · 승인 카드 안 설명 문장. 두 문장까지.
  - label: 단추 · 제목 · 칸 이름(문장이 아님). 끝말 · 길이는 보지 않아요.
  - user: 고객 · 업체 목소리(칩 · 제안 say). 끝말 · 길이는 보지 않아요.
- 기계로 보는 규칙: R2 길이 · R3 '요' 끝 · R4 영어 상태값 · 도구 이름 · 이름표 · 코드 키 · R6 한 일처럼 말함 · 말한 카드가
  없음(cards · actions를 주면) · 기억 약속 · R11 마크다운 · 한자 · 이모지 · 영어 낱말 · R13 연락처 · 동호수 · 이메일 ·
  R14 표준 대비 % · VAT. R1은 첫 문장이 맞장구뿐인지(R1?)만 어림해요. R1 · R5 · R7 · R8 · R9 · R10 · R12는 사람이
  표본을 읽어요(보고서 3절).
- 보고: python evaluation/v4/style_lint.py report <기록 폴더 · 파일 …> [--json 파일]
  기록 꼴을 알아서 읽어요: sim.jsonl(시뮬레이터) · redteam.jsonl(레드팀) · answers.jsonl(답 러너) · 흐름 기록 README-llm.md.
"""

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

RULES = {
    "R1": "결론 먼저",
    "R2": "짧게",
    "R3": "'-해요'체 · '요'로 끝",
    "R4": "영어 상태값 · 도구 이름 · 이름표 · 코드 키",
    "R5": "숫자는 도구 값만",
    "R6": "한 일처럼 말하지 않음 · 말한 행동은 함",
    "R7": "다음 할 일 하나",
    "R8": "되풀이 없음",
    "R9": "기억을 씀",
    "R10": "실패는 정직하게",
    "R11": "마크다운 · 한자 · 이모지 · 영어 낱말",
    "R12": "범위 밖",
    "R13": "개인정보 · 연락처",
    "R14": "표준 대비 % · VAT",
}
KINDS = ("answer", "line", "note", "label", "user")
MAX_SENTS = {"answer": 3, "note": 2}
LINE_MAX = 60

# 문장 끝: 마침표 · 물음표 · 느낌표 뒤 빈칸, 또는 줄 바꿈(runtime.SENT_END와 같은 꼴)
SENT_END = re.compile(r"(?<=[.!?。])[ \t]+|\n+")
BULLET = re.compile(r"^\s*(?:[-*•·]|\d{1,2}[.)])\s+")
TAIL_PAREN = re.compile(r"\s*[(\[（][^()\[\]（）]*[)\]）]\s*$")
TAIL_PUNCT = " \t.!?…~,"
TAIL_QUOTE = " \t.!?…~,\"'”’」』*"
# 끝말 검사에서 받아 주는 짧은 대답(맞장구는 R1?에서 따로 세요)
SHORT_OK = re.compile(r"^(?:네|넵|예|아니요|좋아요)[.!]?$")
# 이름표(v1 · m1 · r1 · s1 · w1 · d1 · p1 · n1)와 판 이름(v3 · v4)
REF = re.compile(r"(?<![A-Za-z0-9_.])[vmrswdpn][1-9]\d?(?![A-Za-z0-9_])")
SNAKE = re.compile(r"(?<![A-Za-z0-9_])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![A-Za-z0-9_])")
# 코드가 쓰는 영어 값(상태 · 공정 · 등급 · 기준 · 모드 · 카드 종류). 소문자 낱말 그대로일 때만
CODE_WORDS = frozenset((
    "proposed", "approved", "executed", "rejected", "expired", "failed", "requested", "offered",
    "picked", "booked", "visited", "quoted", "chosen", "closed", "declined", "cancelled",
    "pending", "scheduled", "confirmed", "waiting", "replaced", "stale", "conflict", "locked",
    "dobae", "mokgong", "economy", "basic", "supply", "exclusive", "partial", "full", "none",
    "other", "llm", "free", "feed", "notify", "guide", "customer", "vendor", "visit", "deal",
    "proposal", "nudge", "estimate", "quote", "schedule", "brief", "today", "answer", "knowledge",
    "running", "stopped", "done", "need", "dates", "delay",
))  # fmt: skip
MD = re.compile(r"\*\*|__\S|(?m:^#{1,6}\s)|`[^`\n]+`|\[[^\]\n]+\]\([^)\n]+\)|(?m:^\s*\|.*\|\s*$)")
HANJA = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
EMOJI = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27bf\u2b50\u2b55\ufe0f]")
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9']*")
LATIN_OK = frozenset({"AI", "PDF", "cm", "mm", "km", "kg", "m", "L"})
ACRONYM = re.compile(r"^[A-Z]{2,5}$")
PHONE = re.compile(r"(?<!\d)01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)")
DONGHO = re.compile(r"(?<!\d)\d{1,4}\s?동\s?\d{1,4}\s?호(?![가-힣])")
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,5}")
VS_STANDARD = re.compile(
    r"표준[^.\n]{0,20}(?:대비|보다)[^.\n]{0,15}\d+(?:\.\d+)?\s*%|표준\s*대비|(?i:(?<![a-z])vat(?![a-z_]))"
)
# 승인이 있어야 하는 일을 한 것처럼 끝맺는 말(assistant.runtime.CLAIM과 같은 꼴). 다른 사람이 주어면 사실 전달
CLAIM = re.compile(
    r"(?:확정|수락|승인|거절|결제|예약|저장|실행|처리|요청|신청|접수|전송)(?:을|를|으로|로)?\s*"
    r"(?:했어요|했습니다|했고|했으니|해\s*드렸|해\s*뒀|완료|바꿨)"
    r"|보냈어요|보냈습니다|보내\s*드렸|보내\s*뒀"
)
SUBJECT = re.compile(r"([가-힣A-Za-z0-9]+?)(?:이|가|께서)\s")
FIRST = frozenset({"제", "저", "저희", "AI", "비서", "믿집", "내"})
CARD_SAID = re.compile(
    r"카드(?:를|로|도)?\s*(?:새로\s*)?(?:만들었|만들어\s*(?:뒀|놨|드렸)|띄웠|띄워\s*(?:뒀|드렸)|보여\s*드렸|올렸|준비했)"
)
ACTION_SAID = re.compile(
    r"승인\s*카드(?:를|도)?\s*(?:새로\s*)?(?:만들었|만들어\s*(?:뒀|놨|드렸)|띄웠|준비했)"
)
MEMORY_SAID = re.compile(
    r"기억(?:해\s*(?:둘|뒀|놓을|놨|드릴)|할게|했어요|하고\s*있을게)(?!\s*(?:수\s*(?:없|는\s*없)|게\s*없))"
)
# 받침 있는 이름 뒤 '로'(마루와벽로 확정 → 마루와벽으로 확정). ㄹ 받침은 '로'가 맞아요
JOSA_RO = re.compile(r"[가-힣]*([가-힣])로(?=[\s.,!?]|$)")
RO_WORDS = frozenset({"경로", "통로", "진로", "항로", "선로", "회로", "산로"})
ACK = re.compile(
    r"^(?:네|넵|예|좋아요|알겠어요|알겠습니다|그럼요|물론이에요|물론이죠|맞아요|좋은\s*질문이에요|그렇군요|아하|"
    r"(?:알려|올려|말씀해)\s*주셔서\s*(?:감사해요|고마워요))[.!,]?$"
)
# 첫 문장이 도구를 부르기 전 말(확인해 볼게요) · 목록 머리(이래요)뿐인 꼴(R1 어림). 긴 문장은 답으로 봐요
LEAD_MAX = 32
LEAD = re.compile(
    r"(?:확인|비교|찾아|살펴|불러|정리|설명)\S{0,4}\s*(?:볼게요|할게요|드릴게요)[.!]?$"
    r"|(?:이래요|이렇게\s*나와\s*있어요|아래를\s*확인해\s*보세요|이런\s*걸\s*물어보세요|이것들을\s*챙기세요)[.!]?$"
)


@dataclass(frozen=True)
class Hit:
    rule: str
    why: str
    piece: str


def sentences(text: str) -> list[str]:
    """글 → 문장(줄 바꿈 · 마침표 뒤 빈칸으로 나눠요). 빈 줄은 빼고, 줄 앞 목록 표시(1. · -)는 첫 문장에 붙여 둬요."""
    out: list[str] = []
    for line in re.split(r"\n+", text or ""):
        line = line.strip()
        if not line:
            continue
        m = BULLET.match(line)
        head = m.group(0) if m else ""
        parts = [x.strip() for x in SENT_END.split(line[len(head) :]) if x and x.strip()]
        if parts:
            parts[0] = head + parts[0]
            out += parts
    return out


def ends_yo(sent: str) -> bool:
    """문장이 '요'로 끝나는지(끝 문장부호 · 따옴표 · 괄호 덧말 · 이모지는 떼고 봐요)."""
    s = EMOJI.sub("", sent).strip()
    if SHORT_OK.match(s):
        return True
    for _ in range(3):
        s = TAIL_PAREN.sub("", s.rstrip(TAIL_PUNCT)).rstrip(TAIL_QUOTE)
    return s.endswith(("요", "죠"))  # '-죠'는 '-지요'의 준말(해요체)


def bad_ro(text: str) -> list[str]:
    """받침(ㄹ 말고) 뒤에 '로'를 붙인 낱말. '으로' · '앞으로'처럼 맞는 꼴은 빼요."""
    out = []
    for m in JOSA_RO.finditer(text):
        ch = m.group(1)
        tail = (ord(ch) - 0xAC00) % 28
        if (
            ch != "으" and tail not in (0, 8) and m.group(0)[-2:] not in RO_WORDS
        ):  # 0 받침 없음 · 8 ㄹ
            out.append(m.group(0))
    return out


def claims_done(text: str) -> bool:
    if not CLAIM.search(text):
        return False
    subjects = [m.group(1) for m in SUBJECT.finditer(text)]
    return not subjects or all(s in FIRST for s in subjects)


def _r4(text: str) -> tuple[list[Hit], list[tuple[int, int]]]:
    hits: list[Hit] = []
    spans: list[tuple[int, int]] = []
    for m in SNAKE.finditer(text):
        hits.append(Hit("R4", "코드 키 · 도구 이름", m.group(0)))
        spans.append(m.span())
    for m in REF.finditer(text):
        hits.append(Hit("R4", "이름표 · 판 이름", m.group(0)))
        spans.append(m.span())
    for m in LATIN.finditer(text):
        if m.group(0) in CODE_WORDS and not any(a <= m.start() < b for a, b in spans):
            hits.append(Hit("R4", "영어 상태값", m.group(0)))
            spans.append(m.span())
    return hits, spans


def _r11(text: str, spans: list[tuple[int, int]]) -> list[Hit]:
    hits = [Hit("R11", "마크다운", m.group(0).strip()[:20]) for m in MD.finditer(text)]
    hits += [Hit("R11", "한자", m.group(0)) for m in HANJA.finditer(text)]
    hits += [Hit("R11", "이모지", m.group(0)) for m in EMOJI.finditer(text)]
    for m in LATIN.finditer(text):
        w = m.group(0)
        if w in LATIN_OK or any(a <= m.start() < b for a, b in spans):
            continue
        hits.append(Hit("R11", "영어 약어" if ACRONYM.match(w) else "영어 낱말", w))
    return hits


def check(
    text: str,
    kind: str = "answer",
    *,
    cards: list | None = None,
    actions: list | None = None,
) -> list[Hit]:
    """글 하나 → 규칙 위반 목록. cards · actions(이번 턴에 보낸 카드 · 승인 카드)를 주면 '말한 카드가 있는지'도 봐요."""
    if kind not in KINDS:
        raise ValueError(f"모르는 kind: {kind}")
    text = text or ""
    hits: list[Hit] = []
    sents = sentences(text)
    if kind == "line":
        if "\n" in text.strip():
            hits.append(Hit("R2", "한 줄이 아님", text[:40]))
        if len(text.strip()) > LINE_MAX:
            hits.append(Hit("R2", f"{LINE_MAX}자 넘음({len(text.strip())}자)", text[:40]))
    elif kind in MAX_SENTS and len(sents) > MAX_SENTS[kind]:
        hits.append(
            Hit("R2", f"문장 {len(sents)}개(>{MAX_SENTS[kind]})", sents[MAX_SENTS[kind]][:40])
        )
    if kind in ("answer", "line", "note"):
        for s in sents:
            if not ends_yo(s):
                why = "목록 줄이 '요'로 끝나지 않음" if BULLET.match(s) else "'요'로 끝나지 않음"
                hits.append(Hit("R3", why, s[-30:]))
        if sents and ACK.match(sents[0]):
            hits.append(Hit("R1?", "첫 문장이 맞장구뿐", sents[0]))
        elif sents and len(sents[0]) <= LEAD_MAX and LEAD.search(sents[0]):
            hits.append(Hit("R1?", "첫 문장이 도구 앞 말 · 목록 머리", sents[0]))
        for s in sents:
            if claims_done(s):
                hits.append(Hit("R6", "승인 없이 한 일처럼 말함", s[:40]))
        if MEMORY_SAID.search(text):
            hits.append(
                Hit("R6", "기억 약속(저장은 따로 걸러져요)", MEMORY_SAID.search(text).group(0))
            )
        if cards is not None and actions is not None:
            if ACTION_SAID.search(text) and not actions:
                hits.append(
                    Hit(
                        "R6",
                        "승인 카드를 만들었다는데 이번 턴 행동이 없음",
                        ACTION_SAID.search(text).group(0),
                    )
                )
            elif CARD_SAID.search(text) and not cards and not actions:
                hits.append(
                    Hit(
                        "R6",
                        "카드를 보였다는데 이번 턴 카드가 없음",
                        CARD_SAID.search(text).group(0),
                    )
                )
    hits += [Hit("R3", "조사 틀림(로 → 으로)", x) for x in bad_ro(text)]
    r4, spans = _r4(text)
    vs = list(VS_STANDARD.finditer(text))
    hits += r4
    hits += _r11(text, spans + [m.span() for m in vs])
    for rx, why in ((PHONE, "전화번호"), (DONGHO, "동호수"), (EMAIL, "이메일")):
        hits += [Hit("R13", why, m.group(0)) for m in rx.finditer(text)]
    hits += [Hit("R14", "표준 대비 · VAT", m.group(0)[:30]) for m in vs]
    return hits


def rules_of(hits: list[Hit], *, acronyms: bool = False) -> set[str]:
    """걸린 규칙 이름(영어 약어는 acronyms=True일 때만 R11로 세요)."""
    return {h.rule for h in hits if acronyms or h.why != "영어 약어"}


# ---- 기록 읽기 ----


@dataclass
class Text:
    """점검할 글 하나: 길(path) · 자리(kind) · 글 · 출처 · (턴이면) 카드 · 행동 · 앞뒤 묶음."""

    path: str
    kind: str
    text: str
    src: str
    cards: list | None = None
    actions: list | None = None
    group: str = ""  # 같은 대화(되풀이 검사)
    seq: int = 0
    meta: dict | None = None


CARDS_ONLY = "(카드를 보여 줬어요"
CARD_LINE = re.compile(r"^(?:\[카드\]|\[승인 카드\]|\[믿집 계산\]|· |링크: |출처: |단추: )")
SAY_LINE = re.compile(
    r"(?:에서 이 집 조건에 맞는 곳이에요|실측 견적서가 \d+곳 왔어요|공사 날짜를 올렸어요|^확정 공정표예요|"
    r"이 집 정보가 맞는지 확인해 주세요)\.?$"
)


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def from_sim(path: Path) -> list[Text]:
    out: list[Text] = []
    for r in _load_jsonl(path):
        who = "고객" if r.get("surface") == "customer" else "업체"
        grp = f"{r.get('scenario')}#{r.get('trial')}"
        for i, t in enumerate(x for x in r.get("turns", []) if x.get("kind") == "say"):
            text = t.get("text") or ""
            if text.startswith(CARDS_ONLY):
                text = ""
            out.append(
                Text(
                    f"LLM 턴 · {who}(시뮬레이터)",
                    "answer",
                    text,
                    f"{path.parent.name}:{grp}:{i + 1}",
                    cards=list(t.get("cards") or []),
                    actions=list(t.get("actions") or []),
                    group=grp,
                    seq=i,
                    meta={
                        "say": t.get("say"),
                        "mode": t.get("mode"),
                        "status": t.get("turn_status"),
                        "tools": t.get("tools"),
                    },
                )
            )
    return out


def from_redteam(path: Path) -> list[Text]:
    out: list[Text] = []
    for r in _load_jsonl(path):
        who = "고객" if r.get("surface") == "customer" else "업체"
        for i, t in enumerate(x for x in r.get("turns", []) if x.get("kind") == "say"):
            text = t.get("text") or ""
            if text.startswith(CARDS_ONLY):
                text = ""
            out.append(
                Text(
                    f"LLM 턴 · {who}(레드팀)",
                    "answer",
                    text,
                    f"{path.parent.name}:{r.get('id')}:{i + 1}",
                    cards=list(t.get("cards") or []),
                    actions=list(t.get("actions") or []),
                    group=str(r.get("id")),
                    seq=i,
                    meta={
                        "say": t.get("say"),
                        "category": r.get("category"),
                        "mode": t.get("mode"),
                    },
                )
            )
    return out


def turn_text(rendered: str) -> str:
    """답 러너 글(토큰 글 + 카드 · 승인 카드 줄) → 토큰 글만. 카드 줄이 처음 나오는 곳 앞까지에서 카드 위 한 줄을 떼요."""
    lines = rendered.splitlines()
    cut = next((i for i, x in enumerate(lines) if CARD_LINE.match(x)), len(lines))
    head = lines[:cut]
    while head and SAY_LINE.search(head[-1].strip()):
        head.pop()
    return "\n".join(head).strip()


def from_answers(path: Path) -> list[Text]:
    out: list[Text] = []
    for r in _load_jsonl(path):
        out.append(
            Text(
                f"LLM 턴 · 답 러너({r.get('system')})",
                "answer",
                turn_text(r.get("text") or ""),
                f"{path.parent.name}:{r.get('system')}:{r.get('id')}",
                cards=list(r.get("cards") or []),
                actions=[],
                group=f"{r.get('system')}:{r.get('id')}",
                meta={
                    "say": (r.get("turns") or [""])[-1],
                    "group": r.get("group"),
                    "mode": r.get("turn_mode"),
                    "tools": r.get("tools"),
                },
            )
        )
    return out


QUOTE = re.compile(r"\"([^\"]{4,})\"")


def from_flows(path: Path) -> list[Text]:
    """흐름 기록(README-llm.md)의 '비서 · 화면' 칸에서 따옴표 안 글을 뽑아요. 줄인 인용(…)은 끝말 · 길이를 보지 않아요."""
    out: list[Text] = []
    section = ""
    for ln in path.read_text(encoding="utf-8").splitlines():
        if ln.startswith("## "):
            section = ln[3:].split()[0]
            continue
        if not ln.startswith("| ") or section not in ("F1", "F2", "F3"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 3 or not cells[0].strip().isdigit():
            continue
        cell = cells[2]
        for m in QUOTE.finditer(cell):
            before = cell[: m.start()]
            q = m.group(1)
            if re.search(r"먼저 말 걸기\*\*\(AI\)\s*$|비서 소식\*\*\(AI\)\s*$", before):
                path_name, kind = "흐름 · 먼저 말 걸기 AI 글", "line"
            elif re.search(r"AI 한 줄\*\*\(Haiku\)\s*$", before):
                path_name, kind = "흐름 · 업체 브리핑 AI 한 줄", "line"
            elif re.search(r"완료\S*\s*$", before) or "채팅이 열림" in before[-10:]:
                path_name, kind = (
                    "흐름 · 승인 뒤 결과 글",
                    "label",
                )  # 실행한 뒤라 한 일처럼 말해도 돼요
            else:
                path_name, kind = "흐름 · 턴 · 화면 글(요약 인용)", "answer"
            if "…" in q:
                kind = "label"  # 줄인 인용: 끝말 · 길이는 못 봐요(R4 · R11 · R13 · R14만)
            out.append(Text(path_name, kind, q, f"{path.name}:{section}-{cells[0]}"))
    return out


def load(paths: list[Path]) -> list[Text]:
    out: list[Text] = []
    for p in paths:
        files = sorted(p.rglob("*")) if p.is_dir() else [p]
        for f in files:
            if f.name == "sim.jsonl":
                out += from_sim(f)
            elif f.name == "redteam.jsonl":
                out += from_redteam(f)
            elif f.name == "answers.jsonl":
                out += from_answers(f)
            elif f.suffix == ".md":
                out += from_flows(f)
    return out


# ---- 보고 ----


def repeats(texts: list[Text]) -> tuple[int, int, list[str]]:
    """되풀이(R8, 같은 대화 안): (이어진 두 턴의 끝 문장이 같은 수, 한 턴에 같은 카드 종류가 두 번 온 수, 예)."""
    same_tail = dup_card = 0
    examples: list[str] = []
    by: dict[str, list[Text]] = defaultdict(list)
    for t in texts:
        if t.group:
            by[t.group].append(t)
    for rows in by.values():
        rows.sort(key=lambda x: x.seq)
        prev = None
        for t in rows:
            tail = (sentences(t.text) or [""])[-1]
            if prev and tail and tail == prev:
                same_tail += 1
                if len(examples) < 3:
                    examples.append(f"끝 문장 되풀이: {tail[:50]}")
            prev = tail
            kinds = Counter(c if isinstance(c, str) else c.get("kind") for c in t.cards or [])
            if any(n > 1 for n in kinds.values()):
                dup_card += 1
                if len(examples) < 6:
                    examples.append(f"한 턴에 같은 카드 {dict(kinds)} ({t.src})")
    return same_tail, dup_card, examples


def summarize(texts: list[Text], examples: int = 2) -> dict:
    by_path: dict[str, list[Text]] = defaultdict(list)
    for t in texts:
        by_path[t.path].append(t)
    out: dict = {}
    for path, rows in sorted(by_path.items()):
        shown = [t for t in rows if t.text]
        rule_n: Counter[str] = Counter()
        why_n: Counter[str] = Counter()
        ex: dict[str, list[str]] = defaultdict(list)
        for t in shown:
            hits = check(t.text, t.kind, cards=t.cards, actions=t.actions)
            for r in sorted({h.rule if h.why != "영어 약어" else "R11(약어)" for h in hits}):
                rule_n[r] += 1
            for h in hits:
                key = h.rule if h.why != "영어 약어" else "R11(약어)"
                why_n[f"{key} {h.why}"] += 1
                if len(ex[key]) < examples and h.piece not in ex[key]:
                    ex[key].append(f"{h.piece} ({t.src})")
        sents = [len(sentences(t.text)) for t in shown]
        chars = [len(t.text) for t in shown]
        same_tail, dup_card, rep_ex = repeats(rows)
        out[path] = {
            "texts": len(rows),
            "shown": len(shown),
            "empty": len(rows) - len(shown),
            "sent_median": statistics.median(sents) if sents else 0,
            "sent_p90": sorted(sents)[int(len(sents) * 0.9) - 1]
            if len(sents) >= 10
            else max(sents or [0]),
            "chars_median": statistics.median(chars) if chars else 0,
            "rules": dict(
                sorted(rule_n.items(), key=lambda x: (int(re.sub(r"\D", "", x[0]) or 0), x[0]))
            ),
            "whys": dict(why_n.most_common()),
            "examples": dict(ex),
            "R8": {"same_tail": same_tail, "dup_card_turns": dup_card, "examples": rep_ex},
        }
    return out


def to_markdown(summary: dict) -> str:
    order = ["R1?", "R2", "R3", "R4", "R6", "R11", "R11(약어)", "R13", "R14"]
    head = (
        "| 길 | 글 수 | 문장 중앙값(p90) | "
        + " | ".join(order)
        + " | R8 끝 문장 되풀이 · 같은 카드 두 번 |"
    )
    lines = [head, "| " + " | ".join(["---"] * (len(order) + 4)) + " |"]
    for path, s in summary.items():
        n = s["shown"] or 1
        cells = [
            f"{s['rules'].get(r, 0)} ({round(100 * s['rules'].get(r, 0) / n)}%)"
            if s["rules"].get(r)
            else "0"
            for r in order
        ]
        r8 = s["R8"]
        lines.append(
            f"| {path} | {s['shown']} | {s['sent_median']}({s['sent_p90']}) | "
            + " | ".join(cells)
            + f" | {r8['same_tail']} · {r8['dup_card_turns']} |"
        )
    lines.append("")
    for path, s in summary.items():
        if not s["examples"]:
            continue
        lines.append(f"- {path}")
        for rule, ex in s["examples"].items():
            lines.append(f"  - {rule}: " + " / ".join(ex))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for st in (sys.stdout, sys.stderr):
        if hasattr(st, "reconfigure"):
            st.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="v4 비서 글 점검")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report", help="기록 폴더 · 파일의 글을 길별 · 규칙별로 세요")
    rp.add_argument("paths", nargs="+", type=Path)
    rp.add_argument("--json", type=Path, default=None, help="요약을 JSON으로도 써요")
    rp.add_argument("--examples", type=int, default=2)
    cp = sub.add_parser("check", help="글 하나를 검사해요")
    cp.add_argument("text")
    cp.add_argument("--kind", default="answer", choices=KINDS)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        for h in check(a.text, a.kind):
            print(f"{h.rule}\t{h.why}\t{h.piece}")
        return 0
    texts = load(a.paths)
    summary = summarize(texts, a.examples)
    print(to_markdown(summary))
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

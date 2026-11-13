"""지식 조각 키워드 검색 (글자 두 개 묶음 BM25 + RRF). DB · HTTP를 모르는 순수 함수.

화면 검색(frontend/components/v2/ai/rag.ts의 ragSearch7)을 그대로 옮겼다. 같은 말뭉치 · 질문이면 순위가 같다.
"""

import math
import re
from dataclasses import dataclass, field

CONF = {
    "version": "rag7-2026.11.11",
    "rrf_k": 60,
    "tier_w": 0.0008,
    "high_w": 0.0004,
    "enough_cov": 0.35,
    "cite_min": 0.18,
    # 공정별 현장 자료(kind=book): 공정이 정해지면 그 공정 조각을 field_keep자리까지 넣는다 (질문 낱말이 field_cov 이상 겹칠 때만)
    "field_keep": 2,
    "field_cov": 0.3,
}
# 현장 자료 겹침을 잴 때 빼는 말끝 · 물음말
FIELD_STOP = frozenset(
    ["있어", "어요", "되나", "나요", "뭐가", "알려", "려줘", "해요", "하나", "이는", "뭘로", "워요", "할때", "는지", "가요", "까요", "세요", "예요", "에요", "어떻", "떻게", "얼마", "하면", "려면", "인가"]
)  # fmt: skip
# 공정을 넘겨받지 못하면 질문 낱말로 코드가 고른다 (LLM 없이)
TRADE_WORDS = {
    "도배": "도배|벽지|초배|정배|합지|실크|도배풀|풀자국|벽면 시공",
    "목공": "목공|몰딩|문틀|문선|방문|도어|석고|다루끼|각재|가벽|칸막이|천장틀|걸레받이|단열|웨인스코팅|분리대",
}
TIER = {
    "law": 1.0, "gov_notice": 1.0, "gov_guide": 1.0, "gov_qa": 1.0, "kcs": 1.0, "pumsem": 1.0,
    "standard_contract": 1.0, "consumer_agency": 1.0, "official": 1.0, "public_data": 1.0,
    "gov": 0.9, "maker": 0.8, "maker_guide": 0.8, "industry": 0.8, "guide": 0.8, "book": 0.7,
    "news": 0.5, "experience": 0.5, "platform": 0.4, "blog": 0.3, "community": 0.3,
}  # fmt: skip
TYPE_KO = {
    "law": "법령", "gov_notice": "정부 고시", "gov_guide": "정부 안내", "gov_qa": "정부 안내", "kcs": "표준시방서",
    "pumsem": "표준품셈", "standard_contract": "표준계약서", "consumer_agency": "소비자원", "official": "공공기관",
    "public_data": "공공 자료", "gov": "공공기관", "maker": "제조사", "maker_guide": "제조사", "industry": "학회 · 협회",
    "guide": "공공기관", "book": "시공 안내서", "news": "뉴스", "experience": "경험담 · 후기", "platform": "후기 · 문답",
    "blog": "블로그", "community": "후기 · 문답",
}  # fmt: skip
_CASUAL = ("blog", "community", "platform", "experience")
POLICY = {
    "law": (
        "법|계약|하자|분쟁|소송|보증|배상|위약|등록|신고|허가|규약|민원|책임|환불|지체상금",
        _CASUAL,
    ),
    "safety": (
        "안전|석면|화재|가스|누전|감전|누수|곰팡이|환기|유해|새집증후군|폼알데|라돈|추락",
        _CASUAL,
    ),
    "money": (
        "얼마|비용|가격|금액|견적|단가|평당|예산|싸|비싸|부가세|계약금|잔금|아껴|절약",
        _CASUAL[:3],
    ),
}
SYN = [
    ["벽지", "도배"], ["걸레받이", "굽도리"], ["샷시", "창호", "섀시"], ["장판", "바닥재"], ["마루", "바닥재"],
    ["계약금", "선금"], ["하자", "보수", "AS"], ["실측", "현장 측정"], ["반셀프", "직영", "직접 발주"], ["턴키", "일괄"],
    ["철거", "뜯기"], ["문선", "문틀"], ["필름", "시트지"], ["페인트", "도장"], ["줄눈", "메지"], ["퍼티", "빠데"],
    ["초배", "밑지"], ["관리사무소", "관리실"], ["승강기", "엘리베이터"], ["보양", "보호"], ["덧방", "덧바르기"],
    ["합지", "종이벽지"], ["실크", "PVC 벽지"],
]  # fmt: skip
K1, B = 1.2, 0.75
_NOT_WORD = re.compile(r"[^0-9a-z가-힣]+")
_ASCII = re.compile(r"[0-9a-z]+")
REF = re.compile(r"K\d{1,5}")


@dataclass(frozen=True)
class Doc:
    title: str = ""
    pub: str = ""
    date: str = ""
    kind: str = ""
    rel: str = ""
    url: str = ""


@dataclass(frozen=True)
class Chunk:
    ref: str
    doc: str
    text: str
    sec: str = ""
    hints: tuple[str, ...] = ()
    trades: tuple[str, ...] = ()


@dataclass(eq=False)
class Item:
    chunk: Chunk
    doc: Doc
    tf: dict[str, int]
    length: int


@dataclass
class Index:
    items: list[Item]
    df: dict[str, int]
    avg: float
    version: str = ""
    by_ref: dict[str, Item] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class Hit:
    ref: str
    source_type: str
    title: str
    publisher: str
    date: str
    section: str
    text: str
    score: float


@dataclass(frozen=True)
class Result:
    hits: list[Hit]
    enough: bool
    policy: list[str]


def grams(text: str) -> list[str]:
    out: list[str] = []
    for w in _NOT_WORD.sub(" ", (text or "").lower()).split(" "):
        if not w:
            continue
        if _ASCII.fullmatch(w) or len(w) == 1:
            out.append(w)
            continue
        out.extend(w[i : i + 2] for i in range(len(w) - 1))
    return out


def build(chunks: list[Chunk], docs: dict[str, Doc], version: str = "") -> Index:
    items: list[Item] = []
    df: dict[str, int] = {}
    total = 0
    for c in chunks:
        d = docs.get(c.doc) or Doc()
        hints = " ".join(c.hints)
        toks = grams(f"{c.text} {c.sec} {hints} {hints} {d.title}")
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        for t in tf:
            df[t] = df.get(t, 0) + 1
        items.append(Item(c, d, tf, len(toks)))
        total += len(toks)
    avg = total / max(len(items), 1)
    return Index(items, df, avg, version, {x.chunk.ref: x for x in items})


def _uniq(xs) -> list:
    return list(dict.fromkeys(xs))


def _bm25(ix: Index, q: str, trade: str | None = None, n: int = 30, only=None) -> list[Item]:
    qs = _uniq(grams(q))
    out: list[tuple[float, Item]] = []
    for x in ix.items:
        if only and not only(x):
            continue
        s = 0.0
        for t in qs:
            f = x.tf.get(t)
            if not f:
                continue
            m = ix.df.get(t, 0)
            idf = math.log(1 + (ix.n - m + 0.5) / (m + 0.5))
            s += (idf * (f * (K1 + 1))) / (f + K1 * (1 - B + (B * x.length) / ix.avg))
        if trade and trade in x.chunk.trades:
            s *= 1.15
        if s > 0:
            out.append((s, x))
    out.sort(key=lambda p: -p[0])
    return [x for _, x in out[:n]]


def _syn_query(q: str) -> str | None:
    alt, hit = q or "", False
    for g in SYN:
        w = next((v for v in g if v in alt), None)
        if w:
            alt = alt.replace(w, next(v for v in g if v != w), 1)
            hit = True
    return alt if hit else None


def policy_of(q: str) -> tuple[list[str], set[str]]:
    kinds = [k for k, (pat, _) in POLICY.items() if re.search(pat, q or "")]
    return kinds, {e for k in kinds for e in POLICY[k][1]}


def _coverage(q: str, x: Item, stop: frozenset[str] = frozenset()) -> float:
    qs = [t for t in _uniq(grams(q)) if t not in stop]
    return sum(1 for t in qs if t in x.tf) / len(qs) if qs else 0.0


def trades_of(q: str) -> list[str]:
    """질문 낱말에 걸리는 공정들"""
    return [t for t, pat in TRADE_WORDS.items() if re.search(pat, q or "")]


def trade_of(q: str) -> str | None:
    """공정 하나만 걸리면 그 공정. 둘 다 걸리거나 안 걸리면 고르지 않는다"""
    hit = trades_of(q)
    return hit[0] if len(hit) == 1 else None


def _field_hits(ix: Index, qs: list[str], trades: list[str]) -> list[tuple[float, Item]]:
    """그 공정들의 현장 자료(kind=book) 중 질문과 잘 맞는 조각. 공정 표시 없는 조각도 포함"""

    def mine(x: Item) -> bool:
        return x.doc.kind == "book" and (
            not x.chunk.trades or any(t in trades for t in x.chunk.trades)
        )

    fused: dict[Item, float] = {}
    for qq in qs:
        for r, x in enumerate(_bm25(ix, qq, None, 10, mine)):
            fused[x] = fused.get(x, 0.0) + 1 / (CONF["rrf_k"] + r + 1)
    keep = [
        (s, x)
        for x, s in fused.items()
        if max(_coverage(qq, x, FIELD_STOP) for qq in qs) >= CONF["field_cov"]
    ]
    keep.sort(key=lambda p: -p[0])
    return keep


def search(
    ix: Index,
    q: str,
    *,
    queries: list[str] | tuple[str, ...] = (),
    trade: str | None = None,
    k: int = 6,
    policy_text: str | None = None,
) -> Result:
    """검색어 여러 개(+ 동의어)를 BM25로 찾고 RRF로 합친다. 법 · 안전 · 금액 질문은 블로그 · 후기를 뺀다"""
    if not ix.items:
        return Result([], False, [])
    main = (q or "")[:80]
    qs_all = _uniq(x for x in [main, *(str(x)[:80] for x in queries)] if x)[:4]
    syn = _syn_query(main)
    if syn and syn not in qs_all:
        qs_all.append(syn)
    kinds, exclude = policy_of(policy_text or main)
    tr = trade or trade_of(" ".join(qs_all))
    fused: dict[Item, float] = {}
    for qq in qs_all:
        for r, x in enumerate(_bm25(ix, qq, tr)):
            if x.doc.kind in exclude:
                continue
            fused[x] = fused.get(x, 0.0) + 1 / (CONF["rrf_k"] + r + 1)
    ranked = [
        (
            s
            + CONF["tier_w"] * TIER.get(x.doc.kind, 0.5)
            + (CONF["high_w"] if x.doc.rel == "high" else 0),
            x,
        )
        for x, s in fused.items()
    ]
    ranked.sort(key=lambda p: -p[0])
    ranked = ranked[:k]
    field_trades = [trade] if trade else trades_of(" ".join(qs_all))
    if field_trades:
        # 공정 현장 자료 자리: 이미 들어 있는 만큼 빼고 남은 자리만 아래쪽을 바꿔 넣는다
        have = sum(1 for _, x in ranked if x.doc.kind == "book")
        inside = {id(x) for _, x in ranked}
        add = [p for p in _field_hits(ix, qs_all, field_trades) if id(p[1]) not in inside]
        add = add[: max(0, CONF["field_keep"] - have)]
        if add:
            ranked = ranked[: max(0, k - len(add))] + add
    best = max(_coverage(qq, ranked[0][1]) for qq in qs_all) if ranked else 0.0
    hits = [
        Hit(
            ref=x.chunk.ref,
            source_type=TYPE_KO.get(x.doc.kind, "기타"),
            title=x.doc.title,
            publisher=x.doc.pub,
            date=x.doc.date,
            section=x.chunk.sec,
            text=x.chunk.text,
            score=round(s * 1000, 1),
        )
        for s, x in ranked
    ]
    return Result(hits, best >= CONF["enough_cov"], kinds)


def verify_cites(ix: Index, text: str) -> tuple[str, int]:
    """문장과 인용 조각의 글자 두 개 묶음 겹침이 cite_min보다 적으면 그 [K] 표시를 뗀다"""
    dropped = 0
    lines = []
    for line in (text or "").split("\n"):
        if not REF.search(line):
            lines.append(line)
            continue
        sg = set(grams(re.sub(r"\[K\d{1,5}\]", "", line)))

        def keep(m: re.Match, sg: set[str] = sg) -> str:
            nonlocal dropped
            x = ix.by_ref.get(m.group(1))
            if not x or not sg:
                return m.group(0)
            if sum(1 for t in sg if t in x.tf) / len(sg) < CONF["cite_min"]:
                dropped += 1
                return ""
            return m.group(0)

        lines.append(re.sub(r"\[(K\d{1,5})\]", keep, line))
    return "\n".join(lines), dropped

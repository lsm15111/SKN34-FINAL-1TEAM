"""지식 보강 3회차: 핵심 질문(core_questions)과 무료 모드 점검에서 '확인하지 못했어요'로 끝난 dev 질문을 주제로 묶어요.

- 점검 행: evaluation/v3/.cache/kb/coverage_rows.jsonl (3회차 전, `coverage_check.py --tag kb`로 만든 것)
- dev만 봐요: 질문 파일의 split 칸(intent · ask_back은 id 앞머리)이 dev인 줄. held-out 줄은 세지도 보이지도 않아요.
- 공종: 정답 공종(gold_trade)이 있으면 그것, 없으면 관문이 고른 첫 공종. 도배 · 목공 · 공통만 봐요.
- 주제 배정: 주제마다 정한 낱말 규칙과 공종으로 세요(대략값, 한 질문이 여러 주제에 걸릴 수 있어요).
- need: chunks = 새 조각(웹 조사)과 카드를 더하는 주제(조각 2개 이상), keys = 이미 있는 조각 · 카드로 열쇠를 넓히거나 카드를 더하는 주제.
  빠진 질문 = 규칙에 걸리고 화면에 '확인하지 못했어요'가 나온 dev 질문, 같은 유형 = 규칙에 걸린 dev 질문 전부.
출력: data/v3/knowledge/iter3/gaps.json · gaps.csv
실행: python -X utf8 data/v3/knowledge/iter3/gaps.py
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EV = ROOT / "evaluation"
OUT = Path(__file__).resolve().parent
ROWS = EV / "v3" / ".cache" / "kb" / "coverage_rows.jsonl"
CORE = EV / "v3" / "core_questions.jsonl"
KO_TRADE = {"도배": "dobae", "목공": "mokgong", "공통": "common"}
OURS = ("dobae", "mokgong", "common")

# 주제: (공종, 질문 유형, 이름, 핵심 질문 id, 같은 유형 낱말 규칙, 볼 공종)
DM, DMC, MC, D = (
    ("dobae", "mokgong", "common"),
    ("dobae", "mokgong", "common"),
    ("mokgong", "common"),
    ("dobae",),
)
TOPICS: dict[str, tuple[str, str, str, list[str], str, tuple[str, ...]]] = {
    "H01": ("mokgong", "해도 되나 · 판단", "화장실(욕실) 문 교체", ["C17"],
            r"(화장실|욕실)\s?(나무)?\s?(문|도어)|ABS", DMC),
    "H02": ("mokgong", "해도 되나 · 판단", "방문 교체 범위(문짝만 · 문틀까지 · 필름 리폼)", ["C18"],
            r"문짝|문틀|방문(?!판매)|도어(?!락|록)|문\s?교체|문\s?리폼|공틀|문.*(바꾸|바꿔|갈고|갈면|칠해)", MC),
    "H03": ("mokgong", "공법", "문 실측 · 치수 맞추기", [],
            r"(문|문틀|문짝).*(실측|치수|높이|재요|재야|안 맞|맞춰)|벽 두께", MC),
    "H04": ("mokgong", "하자 · 원인", "문 처짐 · 안 닫힘 · 경첩 · 걸쇠 손보기", [],
            r"(문|문짝|방문|문틀).*(처져|처지|처진|내려앉|긁|안 닫|안 걸|걸쇠|끼익|삐걱|소리|휘어|휜|틀어|경첩|녹슬)", MC),
    "H05": ("mokgong", "해도 되나 · 판단", "문 아래 틈 · 문턱", ["C17"],
            r"(문|방문).{0,8}(아래|하부|밑).{0,6}(틈|바람)|문턱|언더컷", MC),
    "H06": ("mokgong", "자재", "몰딩 종류", ["C10"],
            r"몰딩.*(종류|뭐가 있|어떤|차이|뭐예요)|마이너스\s?몰딩|평몰딩|계단몰딩|문선", DMC),
    "H07": ("mokgong", "해도 되나 · 판단", "천장 몰딩 없애기 · 바꾸기(무몰딩)", [],
            r"무몰딩|몰딩.*(없애|빼|떼|줄이|새로|바꾸|교체|이음|벌어|타카|선)", DMC),
    "H08": ("mokgong", "해도 되나 · 판단", "걸레받이 없애기 · 바꾸기", ["C19"],
            r"걸레받이|굽도리|벽 맨 아래.*띠", DMC),
    "H09": ("common", "순서", "목공 다음 도배 순서와 이유", ["C15"],
            r"(목공|몰딩|문틀|석고).*(도배|벽지)|(도배|벽지).*(목공|몰딩|문틀)", DMC),
    "H10": ("dobae", "준비", "도배 전 집 준비(짐 · 가구 · 콘센트 · 보양)", ["C16"],
            r"도배\s?(전|하기 전)|준비해야|짐|가구.*(옮|빼|치우)|콘센트|보양|선반|레일", ("dobae", "common")),
    "H11": ("dobae", "생활", "살면서 도배", ["C21"],
            r"살면서|사는 채로|짐이 있는 채|거주 중|짐 있는", DMC),
    "H12": ("dobae", "생활", "도배 뒤 입주 · 환기 · 가구 배치", ["C22"],
            r"(도배|벽지).*(입주|창문|환기|가구|이사|냄새)|입주\s?청소|창문.*(열|닫)", ("dobae", "common")),
    "H13": ("dobae", "해도 되나 · 판단", "천장 도배", ["C32"], r"천장", D),
    "H14": ("dobae", "하자 · 원인", "벽지 들뜸 · 울음 원인과 보수", ["C14"],
            r"들뜸|들뜨|들떠|떴|부풀|볼록|울(어|고|면|음|었)|우는|기포", D),
    "H15": ("common", "관리사무소 · 이웃", "관리사무소 신고 · 동의서 · 이웃 배려", ["C31"],
            r"관리사무소|관리실|동의서|복도|이웃|옆집|앞집|엘리베이터|승강기|먼지", DMC),
    "H16": ("dobae", "자재", "벽지 고르기(기능성 · 세입자 · 변색 · 구분)", [],
            r"실크|합지|기능성|알레르기|비염|광폭|소폭|친환경|샘플|견본|단종|변색|누렇", D),
    "H17": ("dobae", "공법", "기존 벽지 철거 · 덧방 · 초배", [],
            r"뜯|떼어|떼는|떼고|철거|덧방|초배|몇 겹|시멘트", D),
    "H18": ("dobae", "하자 · 원인", "곰팡이 핀 벽 처리", [],
            r"곰팡이|까만 점|검은 점|거뭇|결로", DMC),
    "H19": ("dobae", "해도 되나 · 판단", "부분 도배(색 차이 · 방 하나 · 벽 한 면)", [],
            r"부분\s?도배|한 칸|한 면|벽만|방만|일부만|만 도배", D),
    "H20": ("mokgong", "공법", "가벽 · 칸막이", [], r"가벽|칸막이|파티션|방을 나누|방 나누", MC),
    "H21": ("mokgong", "공법", "석고보드 · 퍼티", [], r"석고|퍼티|빠데|핸디코트", ("dobae", "mokgong")),
    "H22": ("common", "업체", "업체 고르기 · 후기 확인", ["C12"],
            r"(업체|도배사|목수|팀).*(고르|골라|걸러|후기|포트폴리오|중개|비교|믿을|경력|숙련)|후기", DMC),
    "H23": ("common", "계약 · 분쟁", "말로 정한 것 · 추가금 기록 남기기", [],
            r"카톡|말로|구두|추가금|기록|녹음|합의", ("common",)),
    "H24": ("mokgong", "해도 되나 · 판단", "천장 설비 · 벽걸이 자리 미리 정하기", [],
            r"에어컨|실링팬|TV|티비|아트월|선반", ("dobae", "mokgong")),
    "H25": ("dobae", "해도 되나 · 판단", "벽지 바꿀 때(낡은 벽지 · 교체 시기)", [],
            r"(년 된|년 넘은|년 차|년 지나|낡|칙칙|바래|부스러|바스락)|새로 해야", D),
    "H26": ("common", "가격", "견적이 적정한지 확인하기(표준견적서 · 빠진 항목 · 같은 조건)", ["C07"],
            r"견적.*(적정|적당|비싼|싼|괜찮|정상|맞는|비교|차이|두 배)|적정", DMC),
    "H27": ("common", "계약 · 분쟁", "공사 날짜 미루기 · 일정 바꾸기", ["C26"],
            r"(날짜|일정|공사|착공).*(미루|미뤄|미룬|연기|바꾸|바꿔|늦|밀리|밀려)|연기", DMC),
    "H28": ("common", "계약 · 분쟁", "계약금 · 중도금 · 잔금 나눠 내기", ["C30"],
            r"계약금|잔금|중도금|선금|선급금|착수금", DMC),
}  # fmt: skip
# 새 조각이 필요한 주제(웹 조사 · 조각 2개 이상). 나머지는 이미 있는 조각 · 카드로 열쇠를 넓히거나 카드를 더해요
NEED_CHUNKS = {
    "H01",
    "H03",
    "H04",
    "H05",
    "H08",
    "H10",
    "H11",
    "H12",
    "H13",
    "H16",
    "H22",
    "H25",
    "H26",
    "H27",
    "H28",
}


def jl(path: Path) -> list[dict]:
    if re.search(r"held_?out", path.name):
        raise SystemExit(f"held-out 파일은 열지 않아요: {path.name}")
    return [json.loads(x) for x in path.read_text(encoding="utf-8-sig").splitlines() if x.strip()]


def splits() -> dict[tuple[str, str], str]:
    """(세트, id) → split. evaluation/v3/unknown_check.splits()와 같은 규칙(글은 읽지 않고 split 칸만)."""
    out: dict[tuple[str, str], str] = {}
    qdir = ROOT / "data/v3/questions"
    for f in sorted(qdir.glob("*.jsonl")):
        for q in jl(f):
            out[("bank", q["id"])] = q["split"]
    for q in jl(qdir / "beginner_web/questions.jsonl"):
        out[("beginner", q["id"])] = q["split"]
    for name, f in (
        ("rag90", "rag/questions.jsonl"), ("rag300", "rag/questions_300.jsonl"),
        ("rag_sigong", "rag/questions_sigong.jsonl"), ("answer30", "answer/set30.jsonl"),
        ("trade18", "trade/dobae.jsonl"), ("trade18", "trade/mokgong.jsonl"),
    ):  # fmt: skip
        for q in jl(EV / f):
            out[(name, q["id"])] = q.get("split", "none")
    return out


def dev_rows() -> list[dict]:
    sp = splits()
    out = []
    for r in jl(ROWS):
        s = (
            r["id"].split("-")[0]
            if r["set"] in ("intent", "ask_back21")
            else sp.get((r["set"], r["id"]), "none")
        )
        if s != "dev":
            continue
        t = KO_TRADE.get(r.get("gold_trade") or "", r.get("gold_trade"))
        if not t:
            ts = r.get("trades") or r.get("gate_trades") or []
            t = ts[0] if ts else "common"
        r["trade_"] = t
        out.append(r)
    return out


def main() -> None:
    dev = dev_rows()
    core = {q["id"]: q["q"] for q in jl(CORE)}
    topics, covered = [], set()
    for tid, (trade, kind, name, cids, pat, look) in TOPICS.items():
        rx = re.compile(pat)
        same = [r for r in dev if r["trade_"] in look and rx.search(r["text"])]
        gap = [r for r in same if r.get("says_unknown")]
        covered |= {(r["set"], r["id"]) for r in gap}
        topics.append({
            "id": tid, "trade": trade, "kind": kind, "name": name,
            "need": "chunks" if tid in NEED_CHUNKS else "keys",
            "core": [{"id": c, "q": core[c]} for c in cids],
            "dev_gap": len(gap), "dev_same_type": len(same),
            "gap_questions": [{"set": r["set"], "qid": r["id"], "text": r["text"]} for r in gap],
        })  # fmt: skip
    pool = [r for r in dev if r["trade_"] in OURS and r.get("says_unknown")]
    res = {
        "made": "2026-11-19",
        "source": "evaluation/v3/.cache/kb/coverage_rows.jsonl(3회차 전 무료 모드 점검) · core_questions.jsonl",
        "dev_rows": len(dev),
        "dev_unknown_ours": len(pool),
        "dev_unknown_ours_in_topics": sum(1 for r in pool if (r["set"], r["id"]) in covered),
        "method": "빠진 질문 = 주제 낱말 규칙 + 공종에 걸리고 화면에 '확인하지 못했어요'가 나온 dev 질문(대략값, 겹칠 수 있어요)",
        "topics": topics,
    }
    (OUT / "gaps.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n"
    )
    with (OUT / "gaps.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "trade", "kind", "name", "need", "core", "dev_gap", "dev_same_type"])
        for t in topics:
            w.writerow([t["id"], t["trade"], t["kind"], t["name"], t["need"], ";".join(c["id"] for c in t["core"]),
                        t["dev_gap"], t["dev_same_type"]])  # fmt: skip
    print(
        f"dev {len(dev)}줄 · 도배 · 목공 · 공통 모름 {len(pool)}개 중 주제에 걸린 것 {res['dev_unknown_ours_in_topics']}개"
    )
    for t in topics:
        print(
            f"{t['id']} {t['trade']:8} {t['need']:6} {t['name']} · 핵심 {len(t['core'])} · 빠진 dev {t['dev_gap']} · 같은 유형 {t['dev_same_type']}"
        )


if __name__ == "__main__":
    main()

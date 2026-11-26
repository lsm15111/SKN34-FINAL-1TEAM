"""서울12호 열린견적서 235건의 검수 메타(<글>/<글>_상세_검수메타.csv)에서 바닥(1100) 구간을 뽑아 floor_lines.csv로 써요.

    python -I -X utf8 evaluation/floor/market/extract_seoul12.py <by_post 폴더> <저장소 밖 floor_lines.csv>

- 칸은 도배 d10-/data/seoul12/dobae_lines.csv와 같고 종류 · 두께T · 고름 · 단위_원본 · 확인필요를 더해요.
- 바닥 코드(1101~1107)는 자리 번호라 같은 코드가 강마루 · 장판일 수 있어요. 그래서 종류는 내용 글로 나눠요.
- 고름: chosen 금액 있는 줄 · option 단가만 있는 자재 후보('고객선택' 포함) · service '서비스' · none 그 밖.
- 지역: 제목의 시 · 군 · 구, 동 이름만 있으면 DONG 표로 구를 정해요(도배 dobae_lines.csv 지역과 같은 규칙).
- 확인필요: 검수 메타의 검수필요 · 판독 불확실, 또는 인건비 품 단가가 10만 원 아래(원문 그대로지만 드문 값).
- 인건비 단위 품 · M/D · ML은 '품'으로 맞추고 원문은 단위_원본에 둬요. OCR 표기 운승비 · 문씀비는 운송비로 고쳐요.
- 업체 견적 원문이라 결과 CSV는 저장소에 두지 않아요.
"""

import csv
import re
import sys
from pathlib import Path


def read(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


root, out = Path(sys.argv[1]), Path(sys.argv[2])
idx = {r["id"]: r["label"] for r in read(root / "게시글별_목록.csv")}
FIX = {"운승비": "운송비", "문씀비": "운송비"}
DONG = {"신월동": "양천구", "신정동": "양천구", "영등포": "영등포구", "당산": "영등포구",
        "대림동": "영등포구", "구로동": "구로구", "봉천": "관악구", "신림동": "관악구", "난곡": "관악구",
        "수서동": "강남구", "서대문": "서대문구", "북가좌동": "서대문구", "남가좌": "서대문구",
        "서초": "서초구", "부천": "부천시"}  # fmt: skip


def gu_of(label: str) -> str:
    body = re.sub(r"^\[[^\]]*\]\s*|^\([^)]*\)\s*", "", label.replace("\xa0", " "))
    body = re.sub(r"^서울\S*\s+", "", body)
    g = re.search(r"(?<!\S)(\S+?[구시군])(?=\s)", body)
    return g.group(1) if g else next((v for k, v in DONG.items() if k in body), "")


def kind(t):
    if re.search(r"장판|모노륨", t):
        return "sheet"
    if re.search(r"데코", t):
        return "decotile"
    if re.search(r"강화마루", t):
        return "ganghwa"
    if re.search(r"원목", t):
        return "wood"
    if re.search(r"하이브리드", t):
        return "hybrid"
    if re.search(r"온돌마루|합판마루", t):
        return "plywood"
    if re.search(r"초광폭", t):
        return "kang_wide2"
    if re.search(r"강마루|마루", t):
        return "kang"
    return ""


def cls(t):
    if "보양" in t:
        return "protect"
    if t == "인건비":
        return "labor"
    if t == "식대":
        return "meal"
    if t in ("운송비",):
        return "ship"
    return "mat" if kind(t) else "other"


def n(s):
    try:
        return float(s) if s not in ("", None) else None
    except ValueError:
        return None


COLS = [
    "글ID",
    "제목평형",
    "지역",
    "바닥코드",
    "바닥소계",
    "상세행번호",
    "코드",
    "공사명",
    "내용",
    "분류",
    "금액",
    "단가",
    "수량",
    "단위",
    "비고",
    "금액_숫자",
    "단가_숫자",
    "수량_숫자",
    "종류",
    "두께T",
    "고름",
    "단위_원본",
    "확인필요",
]
rows_out, stats = [], {"posts": 0, "rows": 0, "flag": 0}
for p in sorted(x for x in root.iterdir() if x.is_dir() and re.fullmatch(r"\d{6}", x.name)):
    lab = idx.get(p.name, "")
    m = re.search(r"(\d+)\s*평", lab)
    py = m.group(1) if m else ""
    gu = gu_of(lab)
    meta = [
        r
        for r in read(p / f"{p.name}_상세_검수메타.csv")
        if r.get("구간") == "상세" and re.fullmatch(r"11\d\d", (r.get("코드") or "").strip())
    ]
    if not meta:
        continue
    stats["posts"] += 1
    head = next((r for r in meta if r["코드"].strip() == "1100"), None)
    subtotal = head["금액_숫자"] if head else ""
    for r in meta:
        c = r["코드"].strip()
        if c == "1100":
            continue
        t = " ".join((r["내용"] or "").split())
        t = FIX.get(t, t)
        k = kind(t) if cls(t) == "mat" else ""
        th = re.search(r"(\d(?:\.\d)?)\s*[Tt]", t) if k == "sheet" else None
        amt = n(r["금액_숫자"])
        note = (r["비고"] or "").strip()
        price = n(r["단가_숫자"])
        if amt:
            pick = "chosen"
        elif note == "고객선택" or (cls(t) == "mat" and price):
            pick = "option"
        else:
            pick = "service" if note == "서비스" else "none"
        unit = (r["단위"] or "").strip()
        unit_n = "품" if cls(t) == "labor" and unit in ("품", "M/D", "ML") else unit
        low_labor = cls(t) == "labor" and amt and price is not None and price < 100_000
        flag = "Y" if (r.get("검수필요") or r.get("비전판독불확실열") or low_labor) else ""
        stats["rows"] += 1
        stats["flag"] += bool(flag)
        rows_out.append(
            [
                p.name,
                py,
                gu,
                "1100",
                subtotal,
                r["원본행번호"],
                c,
                r["공사명"],
                t,
                cls(t),
                r["금액"],
                r["단가"],
                r["수량"],
                unit_n,
                note,
                r["금액_숫자"],
                r["단가_숫자"],
                r["수량_숫자"],
                k,
                th.group(1) if th else "",
                pick,
                unit,
                flag,
            ]
        )
with open(out, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(COLS)
    w.writerows(rows_out)
print(stats)

"""서울12호 바닥 줄(floor_lines.csv)을 재요. 금액 · 수량 · 품이 평형과 어떻게 맞는지, 평당 단가에 무엇이 들었는지.

    python -I -X utf8 evaluation/floor/market/analyze_seoul12.py <floor_lines.csv> > evaluation/floor/market/seoul12.md

- 입력은 extract_seoul12.py가 저장소 밖에 쓴 표예요(업체 견적 원문이라 저장소에 두지 않아요).
- 고른 줄(chosen)만 셉니다. '고객선택' 줄은 단가 후보로만 봐요.
- 자재표 비교는 backend/app/refprice/v2_materials.json 바닥 자재 가격(㎡)을 평으로 바꿔 견줘요.
- LLM · DB 호출 없음.
"""

import csv
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = 3.3058
KO = {"kang": "강마루", "kang_wide2": "초광폭 강마루", "wood": "원목마루", "sheet": "장판", "decotile": "데코타일",
      "ganghwa": "강화마루", "hybrid": "하이브리드마루", "plywood": "합판마루"}  # fmt: skip


def q(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]


def fit(xs, ys):
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    ss = sum((y - my) ** 2 for y in ys)
    r2 = 1 - sum((y - a - b * x) ** 2 for x, y in zip(xs, ys)) / ss if ss else 1.0
    return a, b, r2


def won(x):
    return f"{x:,.0f}"


def main(path: Path) -> None:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    by = defaultdict(list)
    for r in rows:
        by[r["글ID"]].append(r)
    posts = []
    for pid, rs in by.items():
        py = float(rs[0]["제목평형"]) if rs[0]["제목평형"] else None
        mats = [r for r in rs if r["분류"] == "mat" and r["고름"] == "chosen"]
        lab = [r for r in rs if r["분류"] == "labor" and r["고름"] == "chosen"]
        sub = float(rs[0]["바닥소계"]) if rs[0]["바닥소계"] else None
        chosen_sum = sum(float(r["금액_숫자"]) for r in rs if r["고름"] == "chosen")
        posts.append(
            {
                "id": pid,
                "py": py,
                "mats": mats,
                "lab": lab,
                "sub": sub,
                "sum": chosen_sum,
                "rows": rs,
            }
        )

    print("# 서울12호 바닥(1100) 시장 견적 분석\n")
    print(
        f"- 글 {len(posts)}개 · 바닥 줄 {len(rows)}줄(소계 줄 빼고). 2026 서울 아파트 전체 철거 리모델링, 한 업체예요."
    )
    ok = sum(1 for p in posts if p["sub"] and abs(p["sub"] - p["sum"]) < 1)
    print(f"- 소계 = 고른 줄 금액 합: {ok}/{sum(1 for p in posts if p['sub'])}글\n")

    print("## 1. 줄 꼴\n")
    print("| 분류 | 고름 | 줄 수 |\n| --- | --- | --- |")
    for (c, g), n in sorted(Counter((r["분류"], r["고름"]) for r in rows).items()):
        print(f"| {c} | {g} | {n} |")

    print("\n## 2. 고른 자재\n")
    kinds = Counter(p["mats"][0]["종류"] if p["mats"] else "(없음)" for p in posts)
    print(
        "| 종류 | 글 | 평당 단가 중앙 (p25 ~ p75) | 수량 ÷ 제목평 중앙 | 수량 = a + b × 평 (R²) |"
    )
    print("| --- | --- | --- | --- | --- |")
    for k, n in kinds.most_common():
        ps = [p for p in posts if p["mats"] and p["mats"][0]["종류"] == k]
        if not ps:
            print(f"| {k} | {n} | — | — | — |")
            continue
        pr = [float(p["mats"][0]["단가_숫자"]) for p in ps]
        xs = [p["py"] for p in ps if p["py"] and p["mats"][0]["수량_숫자"]]
        ys = [float(p["mats"][0]["수량_숫자"]) for p in ps if p["py"] and p["mats"][0]["수량_숫자"]]
        rat = st.median(y / x for x, y in zip(xs, ys))
        reg = "—"
        if len(xs) >= 5:
            a, b, r2 = fit(xs, ys)
            reg = f"{a:.1f} + {b:.3f} × 평 ({r2:.2f})"
        print(
            f"| {KO.get(k, k)} | {n} | {won(st.median(pr))} ({won(q(pr, 0.25))} ~ {won(q(pr, 0.75))}) | {rat:.3f} | {reg} |"
        )
    th = Counter(
        p["mats"][0]["두께T"] for p in posts if p["mats"] and p["mats"][0]["종류"] == "sheet"
    )
    print(f"\n- 장판 두께(T): {', '.join(f'{k or "표기 없음"} {v}' for k, v in th.most_common())}")
    for k in ("kang", "sheet"):
        pr = Counter(
            int(float(p["mats"][0]["단가_숫자"]))
            for p in posts
            if p["mats"] and p["mats"][0]["종류"] == k
        )
        print(
            f"- {KO[k]} 평당 단가 분포: {', '.join(f'{won(a)} {b}' for a, b in sorted(pr.items()))}"
        )
    opt = Counter(
        (r["종류"], int(float(r["단가_숫자"])))
        for r in rows
        if r["분류"] == "mat" and r["고름"] == "option" and r["단가_숫자"]
    )
    print(
        f"- '고객선택' 후보 단가(종류 · 원/평 · 줄 수): {', '.join(f'{KO.get(k, k)} {won(v)} {n}' for (k, v), n in opt.most_common(10))}"
    )

    print("\n## 3. 인건비 · 식대 · 운송비 · 보양\n")
    lp = [float(r["단가_숫자"]) for p in posts for r in p["lab"] if r["단가_숫자"]]
    xs = [p["py"] for p in posts if p["py"] and p["lab"] and p["lab"][0]["수량_숫자"]]
    ys = [
        float(p["lab"][0]["수량_숫자"])
        for p in posts
        if p["py"] and p["lab"] and p["lab"][0]["수량_숫자"]
    ]
    a, b, r2 = fit(xs, ys)
    print(
        f"- 인건비: 품당 중앙 {won(st.median(lp))}원 ({', '.join(f'{won(k)} {v}' for k, v in Counter(lp).most_common(4))}), "
        f"단위 원문 {dict(Counter(r['단위_원본'] for p in posts for r in p['lab']))}"
    )
    print(
        f"- 품 = {a:.2f} + {b:.3f} × 평 (R² {r2:.2f}), 품 ÷ 평 중앙 {st.median(y / x for x, y in zip(xs, ys)):.3f}, "
        f"품 분포 {dict(sorted(Counter(ys).items()))}"
    )
    for k in ("kang", "sheet"):
        ps = [p for p in posts if p["mats"] and p["mats"][0]["종류"] == k and p["lab"] and p["py"]]
        if ps:
            print(
                f"  - {KO[k]}: 품 ÷ 평 중앙 {st.median(float(p['lab'][0]['수량_숫자']) / p['py'] for p in ps):.3f} ({len(ps)}글)"
            )
    meal = [p for p in posts for r in p["rows"] if r["분류"] == "meal" and r["고름"] == "chosen"]
    same = sum(
        1
        for p in posts
        for r in p["rows"]
        if r["분류"] == "meal" and p["lab"] and r["수량_숫자"] == p["lab"][0]["수량_숫자"]
    )
    print(
        f"- 식대: {len(meal)}글, 수량 = 인건비 품 {same}글, 단가 {dict(Counter(r['단가_숫자'] for r in rows if r['분류'] == 'meal'))}"
    )
    print(f"- 운송비: 단가 {dict(Counter(r['단가_숫자'] for r in rows if r['분류'] == 'ship'))}")
    print(
        f"- 보양: {dict(Counter(r['고름'] for r in rows if r['분류'] == 'protect'))}, "
        f"단가 {dict(Counter(r['단가_숫자'] for r in rows if r['분류'] == 'protect').most_common(4))}"
    )

    print("\n## 4. 소계와 몫\n")
    for k in ("kang", "sheet"):
        ps = [p for p in posts if p["mats"] and p["mats"][0]["종류"] == k and p["sub"] and p["py"]]
        per = [p["sub"] / p["py"] for p in ps]
        share = [float(p["mats"][0]["금액_숫자"]) / p["sub"] for p in ps]
        lshare = [float(p["lab"][0]["금액_숫자"]) / p["sub"] for p in ps if p["lab"]]
        print(
            f"- {KO[k]} {len(ps)}글: 소계 ÷ 제목평 중앙 {won(st.median(per))}원 (p25 {won(q(per, 0.25))} ~ p75 {won(q(per, 0.75))}), "
            f"자재 줄 몫 {st.median(share):.1%}, 인건비 몫 {st.median(lshare):.1%}"
        )

    print("\n## 5. 평당 단가에 시공이 들었나(자재표와 견줌)\n")
    with open(ROOT / "backend/app/refprice/v2_materials.json", encoding="utf-8") as f:
        mats = json.load(f)
    mats = mats if isinstance(mats, list) else next(v for v in mats.values() if isinstance(v, list))
    for kind, ko in (("maru", "마루"), ("sheet", "장판")):
        ps = [
            (m["price"]["min"] + m["price"]["max"]) / 2 * PY
            for m in mats
            if m.get("cat") == "floor" and m.get("kind") == kind and m["price"]["unit"] == "㎡"
        ]
        if ps:
            print(
                f"- 자재표 {ko} {len(ps)}개: 자재가만 평당 중앙 {won(st.median(ps))}원 (범위 {won(min(ps))} ~ {won(max(ps))})"
            )
    print(
        "- 표준시장단가 2026 하반기 플로어링 마루 설치(주재료 제외) 12,408원/㎡ = 평당 약 "
        f"{won(12408 * PY)}원 (`v2_estimate_ref.json` floor_labor.public)"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))

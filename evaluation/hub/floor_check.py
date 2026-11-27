"""바닥 전문가 점검: 고객 말투 질문 50개로 분기 · 답 종류를 본다. DB 없음.

    cd backend && uv run python ../evaluation/hub/floor_check.py          # 무료 모드(LLM 0회)
    cd backend && uv run python ../evaluation/hub/floor_check.py --llm    # LLM 모드(.env의 OPENAI_API_KEY, 유료)

--llm은 LLM_LIVE=true로 실제 모델을 부른다. 질문마다 총괄 · 전문가 호출이 최대 8번이라 비용이 든다.
"""

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (질문, 기대) floor=바닥 전문가 · multi=바닥 + 다른 공종 · other=바닥 아님
QUESTIONS = [
    ("장판이랑 마루 뭐가 나아요?", "floor"),
    ("강마루 강화마루 차이좀 알려줘", "floor"),
    ("애기 있는 집인데 바닥 뭘로 깔까요", "floor"),
    ("강아지 키우는데 마루 괜찮을까요?", "floor"),
    ("층간소음 때문에 바닥재 고민이에요", "floor"),
    ("데코타일 셀프로 깔아도 돼요?", "floor"),
    ("바닥 공사하기 전에 제가 뭐 해놔야 돼요?", "floor"),
    ("마루 시공 끝나면 뭐 확인해야 해요?", "floor"),
    ("바닥 업체 실측 올 때 뭘 물어보면 좋아요?", "floor"),
    ("장판 교체 비용 얼마나 해요?", "floor"),
    ("마루가 들떴어요 하자인가요?", "floor"),
    ("마루 들뜬 거 어떻게 고쳐요", "floor"),
    ("기존 장판 위에 덧방해도 돼요?", "floor"),
    ("마루 벽쪽 틈 원래 있는 거예요?", "floor"),
    ("원목마루 관리 어떻게 해요?", "floor"),
    ("바닥재 브랜드 추천해주세요", "floor"),
    ("바닥 업체 어디가 잘해요?", "floor"),
    ("바닥 공사 며칠 걸려요?", "floor"),
    ("우리 집 바닥 습기 많은 것 같은데 마루 깔아도 될까요", "floor"),
    ("헤링본 마루 하고 싶어요", "floor"),
    ("모노륨 두께 차이 있어요?", "floor"),
    ("장판 까는 거 하루면 끝나나요?", "floor"),
    ("장판 두께는 뭘 보고 골라요?", "floor"),
    ("깐 마루가 계약한 제품 맞는지 어떻게 확인해요?", "floor"),
    ("마루 시공하고 모래주머니 올려놓던데 왜 그래요?", "floor"),
    ("미장 끝나고 바로 마루 시공해도 되나요?", "floor"),
    ("마루 깔고 언제부터 걸어 다녀도 돼요?", "floor"),
    ("마루에서 삐걱 소리 나요", "floor"),
    ("아파트 마루 교체할 때 관리실 동의 받아야 해요?", "floor"),
    ("마루에 기스 났는데 어떻게 해요", "floor"),
    ("마루 시공하고 가구 바로 넣어도 돼요?", "floor"),
    ("가구 옮길 때 마루 안 긁히게 하려면요?", "floor"),
    ("강아지가 마루에서 미끄러져요", "floor"),
    ("LVT가 뭐예요?", "floor"),
    ("아이가 뛰는 소리 매트로 줄일 수 있어요?", "floor"),
    ("카펫 깔아도 돼요?", "floor"),
    ("우리 집에 맞는 바닥재 골라 줘", "floor"),
    ("바닥 업체에 뭘 물어봐야 해요?", "floor"),
    # 순서 질문은 바닥 전문가 하나가 답해도, 두 공종에 나눠 맡겨도 맞아요
    ("도배랑 장판 순서 어떻게 해요?", "multi|floor"),
    ("몰딩 바꾸고 마루도 새로 깔려는데 뭐부터 해요?", "multi|floor"),
    ("마루 깔고 보일러 바로 틀어도 되나요", "floor"),
    ("마루 바꾸면 난방 배관도 손대요?", "floor"),
    ("현관 바닥 타일 바꾸려고요", "other"),
    ("욕실 바닥 타일 줄눈 곰팡이 어떻게 해요", "other"),
    ("싱크대 문짝 시트지 붙여도 돼요?", "other"),
    ("실크 벽지 합지 차이가 뭐예요?", "other"),
    ("방문 교체하려면 뭐 확인해요?", "other"),
    ("오늘 점심 뭐 먹지", "other"),
    ("강아지 산책 몇 번 해요?", "other"),
    ("매트리스 버리는 법 알려줘", "other"),
]


def kind(a) -> str:
    titles = " ".join(s.title for s in a.sections)
    srcs = {s.source for s in a.sections}
    if a.ask is not None:
        return "되묻기"
    for key, name in (("체크", "체크리스트"), ("맞는 바닥재", "맞춤"), ("순서", "순서"),
                      ("견적서에서", "견적 항목"), ("들뜸 · 단차", "하자 안내")):  # fmt: skip
        if key in titles:
            return name
    if any(c.kind == "compare" for c in a.cards):
        return "비교표"
    if "llm" in srcs:
        return "LLM 글"
    if a.vendor and srcs <= {"template"}:
        return "업체 질문"
    if "card" in srcs:
        return "검증 카드"
    if "extract" in srcs:
        return "자료 발췌"
    return "정해 둔 글" if srcs else "모름"


def _env_file() -> Path | None:
    """저장소 루트의 .env. worktree(.claude/worktrees/<이름>)에서 돌리면 메인 작업 폴더의 .env를 쓴다."""
    for d in (ROOT, *ROOT.parents[:3]):
        if (d / ".env").exists() and (d / ".git").exists():
            return d / ".env"
    return None


def _load_key() -> bool:
    env = _env_file()
    if env is not None:  # OPENAI_ 설정만 읽는다. 값은 찍지 않는다
        for line in env.read_text(encoding="utf-8").splitlines():
            k, _, v = line.strip().partition("=")
            if k.startswith("OPENAI_") and v.strip():
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
    os.environ["LLM_LIVE"] = "true"
    return bool(os.environ.get("OPENAI_API_KEY"))


async def main(use_llm: bool, limit: int | None, out: Path | None, pick: str = "") -> None:
    sys.path.insert(0, str(ROOT / "backend" / "tests"))
    from v3_kb import repo_kb

    from app.agent.hub import concierge
    from app.agent.v3.schemas import TurnContext

    ctx = TurnContext(user_id=uuid.uuid4(), today=date.today(), mode="llm" if use_llm else "free")
    kb = repo_kb()
    ok = unknown = 0
    took: list[float] = []
    qs = QUESTIONS[:limit] if limit else QUESTIONS
    if pick:  # 1부터 센 번호(예: 8,39,41)
        qs = [QUESTIONS[int(i) - 1] for i in pick.split(",") if i.strip()]
    rows = []
    for q, want in qs:
        t0 = time.perf_counter()
        a = (await concierge.run_turn(q, ctx, kb=kb)).answer
        took.append(time.perf_counter() - t0)
        rows.append(
            {"q": q, "want": want, "took": round(took[-1], 1), "answer": a.model_dump(mode="json")}
        )
        floor = "trade:floor" in a.trace.parts
        got = "multi" if floor and a.trace.route == "multi" else ("floor" if floor else "other")
        hit = got in want.split("|")
        ok += hit
        k = kind(a)
        unknown += k == "모름" and want != "other"
        first = a.lead or next(
            (x.text for s in a.sections for x in s.sentences), (a.unknown or [""])[0]
        )
        mark = "O" if hit else "X"
        print(
            f"{mark} [{want:5}→{got:5}] {k:6} {took[-1]:4.1f}s | {q}\n      {first[:100]}",
            flush=True,
        )
    n = len(qs)
    print(f"\n분기 맞음 {ok}/{n} · 바닥 질문인데 모름 {unknown} · 평균 {sum(took) / n:.1f}s")
    if out is not None:
        out.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="실제 LLM으로(유료)")
    ap.add_argument("--limit", type=int, default=None, help="앞에서부터 이만큼만")
    ap.add_argument("--out", type=Path, default=None, help="질문별 전체 답을 jsonl로")
    ap.add_argument("--pick", default="", help="이 번호 질문만(1부터, 쉼표로)")
    a = ap.parse_args()
    if a.llm and not _load_key():
        sys.exit(".env에 OPENAI_API_KEY가 없어요. 키를 넣고 다시 돌려 주세요.")
    asyncio.run(main(a.llm, a.limit, a.out, a.pick))

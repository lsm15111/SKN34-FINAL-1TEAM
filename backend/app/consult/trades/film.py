"""필름 공정 스펙: 붙일 곳(방문 문짝 · 문틀 · 현관문 · 천장 몰딩 · 붙박이장 · 주방 문짝)과 필름 등급,
방문 개수를 묻고 calc.film으로 계산한다. 방문 개수는 문짝 · 문틀을 고를 때만 묻고,
목공 · 도장과 같이 쓰는 칸(share="doors")이다."""

from app.agent.trade import TradeAgent
from app.calc import film as calc
from app.consult.trades.base import Choice, Common, FieldSpec, TradeSpec, Values
from app.refprice.film import FILM_2026H2

ITEMS = (
    Choice("door", "방문 문짝", "문짝 양면"),
    Choice("frame", "방문 문틀", "문틀 · 문선"),
    Choice("entrance", "현관문 (안쪽)", "현관문 안쪽 면과 문틀"),
    Choice("molding", "천장 몰딩", "천장과 벽이 만나는 선"),
    Choice("closet", "붙박이장 문", "붙박이장 문 바깥 면"),
    Choice("kitchen", "주방 문짝", "싱크대 · 수납장 문 바깥 면"),
)
ITEM_LABEL = {c.value: c.label for c in ITEMS}
GRADES = (
    Choice("basic", "일반 필름", "나무결 · 단색처럼 흔한 무늬예요. 값이 싸요"),
    Choice("premium", "고급 필름", "메탈 · 스톤 질감이나 긁힘에 강한 제품이에요. 값이 더 들어요"),
)
GRADE_LABEL = {c.value: c.label for c in GRADES}


def _doors(v: Values) -> bool:
    return any(i in v.get("items", ()) for i in ("door", "frame"))


def _build(c: Common, v: Values) -> calc.FilmQuote:
    return calc.quote(
        calc.FilmInput(
            area_m2=c.area_m2,
            area_basis=c.area_basis,
            items=tuple(v["items"]),
            occupied=c.occupied,
            grade=v["grade"],
            doors=v["doors"] if _doors(v) else 0,
        ),
        FILM_2026H2,
    )


def _card_lines(c: Common, v: Values) -> list[str]:
    rows = [
        "필름 붙일 곳: " + ", ".join(ITEM_LABEL[i] for i in v["items"]),
        f"필름 등급: {GRADE_LABEL[v['grade']]}",
    ]
    if "doors" in v:
        rows.append(f"필름 붙일 방문: {v['doors']}개")
    return rows


SPEC = TradeSpec(
    key="film",
    label="필름",
    order=75,
    fields=(
        FieldSpec(
            key="items",
            label="필름 붙일 곳",
            question="어디에 필름을 붙일까요? 여러 개 골라도 돼요.",
            kind="multi",
            choices=ITEMS,
            max=len(ITEMS),
            hint="창틀(샷시) 필름 · 유리 시트지는 이 칸이 아니에요",
        ),
        FieldSpec(
            key="grade",
            label="필름 등급",
            question="필름은 어떤 걸로 할까요?",
            kind="choice",
            choices=GRADES,
            unknown="basic",
        ),
        FieldSpec(
            key="doors",
            label="필름 붙일 방문 개수",
            question="필름을 붙일 방문은 몇 개예요?",
            kind="count",
            min=1,
            max=10,
            unknown=3,
            when=_doors,
            hint="필름 붙일 방문 개수를 숫자로 말했을 때만",
            share="doors",
        ),
    ),
    agent=TradeAgent.load("film", "필름", "film_v1.md"),
    build=_build,
    card_lines=_card_lines,
)

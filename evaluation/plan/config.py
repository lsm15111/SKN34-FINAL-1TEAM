"""공정 의견 평가의 공정별 얇은 설정. 설정이 없는 공정은 스펙에서 뽑은 기본값으로 돈다.

설정으로 바꿀 수 있는 것
- rules: 규칙 id → 규칙. 스펙 화면 말에서 뽑은 기본 규칙을 바꾸거나 이 공정만의 규칙을 더한다
- extra(카드 JSON, 이 공정 칸 값) → (must, must_not): 이 공정만의 규칙 id를 사례에 붙인다
- scope_exempt: '고르지 않은 공정 언급' 검사에서 뺄 말. None이면 이 공정 지식(쓰는 법 · 출처 밖)에 나오는 말을 뺀다
- count_buckets: 숫자 칸의 구간 (기본은 범위를 셋으로 나눔)
- witness: 손으로 쓴 모범 답 (없으면 규칙 예문으로 만든다)
- prefix · salt: 사례 id 앞머리 · 난수 이름 (도배 · 목공은 A5 사례와 같게 wallpaper · carpentry)
도배 · 목공 키워드는 지난 도배 의견 135건으로 맞춘 A5 규칙을 그대로 옮겼다.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from evaluation.scorers import witness
from evaluation.scorers.rules import ALL, VC, Rule, rule

Extra = Callable[[dict, dict], tuple[list[str], list[str]]]


@dataclass(frozen=True)
class PlanConfig:
    prefix: str = ""
    salt: str = ""
    rules: dict[str, Rule] = field(default_factory=dict)
    extra: Extra | None = None
    scope_exempt: tuple[str, ...] | None = None
    count_buckets: dict[str, dict[str, tuple[int, int]]] = field(default_factory=dict)
    witness: Callable[[dict], dict] | None = None


_DOOR = r"문틀|문짝|문선|경첩|손잡이|방문\s?(교체|개수|크기|을|은|이|도|만|마다)|문\s?(교체|아래)"


def _dobae_extra(card: dict, v: dict) -> tuple[list[str], list[str]]:
    must, must_not = [], []
    if card["balcony_ext"]:
        must.append("balcony.check")
    else:
        must_not.append("balcony.none")
    if v["include_ceiling"] == "no":
        must_not.append("not_chosen.include_ceiling")
    return must, must_not


DOBAE = PlanConfig(
    prefix="wp",
    salt="wallpaper",
    rules={
        "sum.include_ceiling.yes": rule(
            "요약에 천장 포함 여부", ("summary",), r"천장", example="천장"
        ),
        "sum.include_ceiling.no": rule(
            "요약에 천장 포함 여부", ("summary",), r"천장", example="천장"
        ),
        "check.grade": rule(
            "모르는 등급을 실측 때 정함",
            VC,
            r"등급|합지|실크|벽지\s?종류|어떤\s?벽지",
            example="실크와 합지 중 어떤 벽지로 할지 실측 때 정해요.",
        ),
        "check.include_ceiling": rule(
            "모르는 천장 포함을 실측 때 정함", VC, r"천장", example="천장도 바를지 실측 때 정해요."
        ),
        "not_chosen.include_ceiling": rule(
            "천장 안 함인데 천장 작업 언급", ALL, r"천장(?!\s?(높이|몰딩|평탄화))", neg=True
        ),
        "balcony.check": rule(
            "발코니 확장부 결로 · 곰팡이 확인",
            ALL,
            r"발코니|베란다|확장",
            example="발코니를 넓힌 곳은 결로나 곰팡이가 생기기 쉬워요.",
        ),
        "balcony.none": rule("발코니 확장이 아닌데 발코니 언급", ALL, r"발코니|베란다"),
    },
    extra=_dobae_extra,
    scope_exempt=("붙박이장", "단열", "방수"),
    witness=witness.dobae,
)

MOKGONG = PlanConfig(
    prefix="cp",
    salt="carpentry",
    rules={
        "sum.items.door": rule(
            "요약에 방문", ("summary",), r"방문|문짝|문틀|문\s?교체", example="방문 교체"
        ),
        "sum.items.flatten": rule(
            "요약에 천장 평탄화",
            ("summary",),
            r"평탄화|평평|우물\s?천장|등박스",
            example="천장 평탄화",
        ),
        "check.doors": rule(
            "모르는 방문 개수를 실측 때 확인",
            VC,
            r"문.{0,8}(개수|몇)|몇\s?(개|짝)",
            example="바꿀 방문 개수를 실측 때 같이 세어 봐요.",
        ),
        "check.door_frame": rule(
            "모르는 문틀 교체를 실측 때 정함",
            VC,
            r"문틀",
            example="문틀까지 바꿀지 문짝만 바꿀지 실측 때 정해요.",
        ),
        "not_chosen.items.door": rule("고르지 않은 방문 언급", ALL, _DOOR, neg=True),
        "not_chosen.items.flatten": rule(
            "고르지 않은 천장 평탄화 언급",
            ALL,
            r"평탄화|우물\s?천장|등박스|천장틀|석고보드",
            neg=True,
        ),
        "balcony.any": rule("목공 지식에 없는 발코니 언급", ALL, r"발코니|베란다"),
    },
    extra=lambda card, v: ([], ["balcony.any"]),
    scope_exempt=(),
    count_buckets={"doors": {"few": (1, 2), "mid": (3, 4), "many": (5, 6)}},
    witness=witness.mokgong,
)

CONFIGS = {"dobae": DOBAE, "mokgong": MOKGONG}


def get(trade: str) -> PlanConfig:
    return CONFIGS.get(trade, PlanConfig())

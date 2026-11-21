"""반셀프 직접 할 일 알아 두기(`diy.json`): 칩 키마다 언제(도배 · 목공 기준) · 하는 방법 · 준비물 · 주의점 · 출처.
DB · HTTP를 모르는 순수 함수예요.

- 키는 project.diy.DIY와 같아요(paint · outlet · light · silicone · handle · clean). 날짜는 계산 엔진 calc.diy가 만들어요.
- 글에는 숫자 · 금액을 넣지 않아요(정해 둔 글). why · living · pet 줄은 믿집 안내예요.
- 출처는 공공 · 제조사 자료를 먼저 두고, 칸마다 확인 날짜 · 확인 방법을 적었어요. 블로그 자료는 kind blog예요.
"""

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PATH = Path(__file__).resolve().parent / "diy.json"
KIND_ORDER = {"public": 0, "maker": 1, "press": 2, "blog": 3}


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    publisher: str
    kind: str  # public 공공 · maker 제조사 · press 언론 · blog 블로그
    url: str
    checked: str


@dataclass(frozen=True)
class Item:
    key: str
    label: str
    when: str
    why: str
    how: tuple[str, ...]
    tools: tuple[str, ...]
    cautions: tuple[str, ...]
    living: tuple[str, ...]
    pet: tuple[str, ...]
    sources: tuple[Source, ...]

    def source_line(self, limit: int = 3) -> str:
        """카드 출처 한 줄: 공공 → 제조사 → 언론 → 블로그 순 발행처(겹치면 한 번)."""
        ranked = sorted(self.sources, key=lambda x: KIND_ORDER.get(x.kind, 9))
        names = list(dict.fromkeys(x.publisher for x in ranked))
        return " · ".join([*names[:limit], "믿집 안내"])


@dataclass(frozen=True)
class Book:
    version: str
    items: dict[str, Item]


@cache
def book() -> Book:
    raw = json.loads(PATH.read_text(encoding="utf-8"))
    srcs = {
        k: Source(k, v["title"], v["publisher"], v["kind"], v["url"], v["checked"])
        for k, v in raw["sources"].items()
    }
    items = {
        k: Item(
            key=k,
            label=v["label"],
            when=v["when"],
            why=v.get("why", ""),
            how=tuple(v.get("how", ())),
            tools=tuple(v.get("tools", ())),
            cautions=tuple(v.get("cautions", ())),
            living=tuple(v.get("living", ())),
            pet=tuple(v.get("pet", ())),
            sources=tuple(srcs[s] for s in v.get("sources", ())),
        )
        for k, v in raw["items"].items()
    }
    return Book(raw["version"], items)


def item(key: str) -> Item:
    """키 하나의 알아 두기. 모르는 키면 KeyError."""
    return book().items[key]

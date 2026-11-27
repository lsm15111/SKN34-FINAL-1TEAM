"""공종 전문가 등록부. 이 폴더 아래 공종 코드 이름의 폴더가 `build() -> Expert`를 내면 자동으로 붙는다.

- 폴더 이름 = v3 공종 코드(trades.BY_CODE). 공종 낱말 · 공정 순서는 v3 설정을 그대로 쓴다.
- 전문가가 없는 공종은 총괄이 v3 공종 담당(카드 · 조각 답)에 맡긴다. 공종을 하나씩 옮기면 된다.
"""

from __future__ import annotations

import re
from functools import cache
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.hub.experts.base import Expert

ROOT = Path(__file__).parent


@cache
def registered() -> dict[str, Expert]:
    from app.agent.v3.trades import BY_CODE

    out: dict[str, Expert] = {}
    for path in sorted(ROOT.iterdir()):
        if not (path.is_dir() and re.fullmatch(r"[a-z][a-z0-9_]*", path.name)):
            continue
        if not (path / "__init__.py").is_file():
            continue
        if path.name not in BY_CODE or path.name == "common":
            raise ValueError(f"전문가 폴더 이름은 등록된 공종 코드여야 해요: {path.name}")
        x = import_module(f".{path.name}", __name__).build()
        if x.code != path.name:
            raise ValueError(f"전문가 코드가 폴더와 달라요: {path.name}")
        out[x.code] = x
    return out


def get(code: str | None) -> Expert | None:
    return registered().get(code or "")

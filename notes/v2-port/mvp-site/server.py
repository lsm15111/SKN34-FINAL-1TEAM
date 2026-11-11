"""믿집 커스텀 MVP 로컬 서버.

- site/ 폴더의 화면 파일을 보여 준다.
- POST /api/claude 를 Claude API(Messages)로 넘긴다. API 키는 이 프로세스 안에만 둔다.
- 도구(화면 바꾸기)는 브라우저가 실행하고, 서버는 한 번의 요청 · 응답만 중계한다.

실행: uv run --with anthropic python server.py
"""

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import anthropic

HERE = Path(__file__).resolve().parent
SITE = HERE / "site"
PORT = int(os.environ.get("MJ_PORT", "8780"))
MODEL = "claude-opus-5-5"
MAX_BODY = 12 * 1024 * 1024  # 사진 몇 장까지
ALLOWED_TOOLS = {"set_style", "set_home_info", "set_scope", "set_budget", "pick_material", "show_step", "suggest_questions", "search_knowledge", "set_schedule_constraints", "price_reference"}


KEY_SOURCE = "없음"


def load_key() -> None:
    """ANTHROPIC_API_KEY를 이 순서로 찾는다: 환경변수 → 이 폴더 .env → 프로젝트 .env. 값은 출력하지 않는다."""
    global KEY_SOURCE
    if os.environ.get("ANTHROPIC_API_KEY"):
        KEY_SOURCE = "환경변수"
        return
    for env_file in (HERE / ".env", Path(os.environ.get("MJ_ENV_FILE", HERE.parent / "SKN34-FINAL-1TEAM" / ".env"))):
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    os.environ["ANTHROPIC_API_KEY"] = value
                    KEY_SOURCE = str(env_file)
                    return


load_key()
client = anthropic.Anthropic(max_retries=2, timeout=120.0) if os.environ.get("ANTHROPIC_API_KEY") else None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def log_message(self, fmt, *args):  # 요청 본문 · 키는 남기지 않는다
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    def send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/health":
            return self.send_json(200, {"ok": True, "claude": client is not None, "model": MODEL})
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/claude":
            return self.send_json(404, {"error": {"code": "not_found", "message": "없는 주소예요."}})
        origin = self.headers.get("Origin")
        if origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self.send_json(403, {"error": {"code": "origin", "message": "이 주소에서만 쓸 수 있어요."}})
        if client is None:
            return self.send_json(503, {"error": {"code": "no_key", "message": "ANTHROPIC_API_KEY가 없어요."}})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self.send_json(413, {"error": {"code": "too_large", "message": "요청이 너무 커요. 사진 수를 줄여 주세요."}})
        try:
            req = json.loads(self.rfile.read(length))
            system = str(req.get("system", ""))[:60000]
            messages = req["messages"]
            tools = [
                {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
                for t in req.get("tools", [])
                if t.get("name") in ALLOWED_TOOLS
            ]
            if not isinstance(messages, list) or not messages:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return self.send_json(400, {"error": {"code": "bad_request", "message": "요청 모양이 맞지 않아요."}})

        params = dict(
            model=MODEL,
            max_tokens=16000,
            system=system,
            messages=messages,
            output_config={"effort": "low"},  # 대화형이라 빠른 답 우선
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # 안전 분류기 거절 때 서버가 다른 모델로 이어서 답한다
        )
        if tools:
            params["tools"] = tools
        try:
            res = client.beta.messages.create(**params)
        except anthropic.BadRequestError as e:
            return self.send_json(400, {"error": {"code": "bad_request", "message": e.message}})
        except anthropic.AuthenticationError:
            return self.send_json(401, {"error": {"code": "auth", "message": f"API 키가 맞지 않아요(읽은 곳: {Path(KEY_SOURCE).name if KEY_SOURCE != '환경변수' else KEY_SOURCE})."}})
        except anthropic.PermissionDeniedError:
            return self.send_json(403, {"error": {"code": "permission", "message": "이 키로는 쓸 수 없어요."}})
        except anthropic.RateLimitError:
            return self.send_json(429, {"error": {"code": "rate_limited", "message": "요청이 많아요. 잠시 뒤 다시 해 주세요."}})
        except anthropic.APIStatusError as e:
            return self.send_json(502, {"error": {"code": "api", "message": f"Claude API 오류({e.status_code})예요."}})
        except anthropic.APIConnectionError:
            return self.send_json(502, {"error": {"code": "network", "message": "Claude API에 연결하지 못했어요."}})
        data = res.to_dict()
        return self.send_json(200, {"content": data.get("content", []), "stop_reason": data.get("stop_reason"), "model": data.get("model")})


if __name__ == "__main__":
    print(f"믿집 MVP: http://127.0.0.1:{PORT}  (Claude {'켜짐, 키 위치: ' + KEY_SOURCE if client else '꺼짐 - ANTHROPIC_API_KEY 없음'})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

"""DB 없이 tests/test_mvp_v2.py를 돌린다: 로그인만 바꿔 끼운다 (signup → 로그인 상태로)."""
import sys, traceback, uuid
from types import SimpleNamespace as N
sys.modules.setdefault("tests.conftest", N(query=None))
from fastapi.testclient import TestClient
from app.main import app
from app.auth.deps import current_user
import tests.test_mvp_v2 as T
ME = N(id=uuid.uuid4(), role="customer")
c = TestClient(app)
T.signup = lambda api: app.dependency_overrides.__setitem__(current_user, lambda: ME)
ok = bad = 0
for name in [n for n in dir(T) if n.startswith("test_")]:
    app.dependency_overrides.clear()
    try:
        getattr(T, name)(c); ok += 1; print("PASS", name)
    except Exception:
        bad += 1; print("FAIL", name); traceback.print_exc()
print("passed", ok, "failed", bad)

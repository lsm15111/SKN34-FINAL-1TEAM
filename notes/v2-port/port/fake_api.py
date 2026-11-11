"""화면 점검용 가짜 API (커밋 안 함). /mvp는 진짜 router · service · calc, 로그인 · 프로젝트 읽기만 가짜."""
import uuid
from types import SimpleNamespace as N
from fastapi import FastAPI
from app.auth.deps import current_user
from app.db import get_session
from app.mvp.router import router
from app.project import service as ps
from app.shared.errors import AppError, app_error_handler

PID = uuid.UUID("01900000-0000-7000-8000-000000000001")
ME = {"id": str(uuid.uuid4()), "email": "c@mitjip.test", "name": "고객", "phone": None, "role": "customer", "created_at": "2026-11-01T00:00:00Z"}
SP = [str(uuid.uuid4()) for _ in range(3)]
PROJECT = {"id": str(PID), "code": "MJ-2611-0001", "rev": 1, "locked": False, "sido": "seoul", "sgg": "마포구", "region": "서울 마포구", "house_type": "apt", "built_year": 2009,
           "size": {"band": "30", "basis": None, "m2": None}, "balcony_ext": True, "when": {"kind": "unknown", "start": None, "end": None}, "occupied": True, "budget": "500-700",
           "spaces": [{"id": SP[0], "name": "거실"}, {"id": SP[1], "name": "방"}, {"id": SP[2], "name": "방 2"}],
           "trades": {"dobae": {"spaces": SP, "grade": "basic"}, "mokgong": {"spaces": SP[:1], "items": ["molding", "base"]}}, "photos": [], "plans": [], "created_at": "2026-11-01T00:00:00Z"}
async def get_for(s, user, project_id):
    if project_id != PID: raise AppError(404, "not_found", "프로젝트를 찾을 수 없어요.")
    return N(id=PID, rev=1, occupied=True, balcony_ext=True, size=N(band="30", m2=None, basis=None), trades=N(dobae=N(grade="basic"), mokgong=N(items=["molding", "base"])))
ps.get_for = get_for
app = FastAPI()
app.add_exception_handler(AppError, app_error_handler)
async def no_session(): yield None
app.dependency_overrides[get_session] = no_session
app.dependency_overrides[current_user] = lambda: N(id=uuid.UUID(ME["id"]), role="customer")
app.include_router(router)
@app.get("/me")
def me(): return ME
@app.get("/projects/{pid}")
def project(pid: str):
    if pid != str(PID): raise AppError(404, "not_found", "없어요")
    return PROJECT

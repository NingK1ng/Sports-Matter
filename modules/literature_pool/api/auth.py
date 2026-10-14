"""Public access with signed anonymous sessions and daily API allowances."""
from datetime import datetime, timezone
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db
from core.visitor_session import prepare_visitor
from modules.literature_pool.models.user import User
from modules.literature_pool.services.auth_service import AuthService
from modules.literature_pool.services.daily_quota_service import DailyQuotaService

router = APIRouter(prefix="/auth", tags=["Public session"])
ANON_OPENID_PREFIX = "anon:"

def is_guest_user(user):
    return (user.wechat_openid or "").startswith(ANON_OPENID_PREFIX) or user.wechat_openid == "public_guest"

async def get_current_user(request: Request, authorization: str | None = Header(default=None),
                           auth_token: str | None = Cookie(default=None),
                           db: AsyncSession = Depends(get_db)) -> User:
    # Existing valid sessions can keep their own data, but receive the same public allowance.
    service = AuthService(db)
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else auth_token
    user_id = service.verify_jwt_token(token) if token else None
    if user_id:
        user = await service.get_user_by_id(user_id)
        if user and user.wechat_openid != "public_guest":
            return user
    if not getattr(request.state, "visitor_id", None):
        prepare_visitor(request)
    now = datetime.now(timezone.utc)
    stmt = insert(User).values(wechat_openid=ANON_OPENID_PREFIX + request.state.visitor_id,
        wechat_nickname="访客", wechat_avatar="", login_source="anonymous", last_login_at=now)
    stmt = stmt.on_conflict_do_update(index_elements=["wechat_openid"],
        set_={"last_login_at": now}).returning(User)
    result = await db.execute(stmt)
    user = result.scalar_one()
    await db.commit()
    return user

async def get_current_user_id(user: User = Depends(get_current_user)) -> int:
    return user.id

async def consume_daily_quota(db, user, feature_key):
    result = await DailyQuotaService(db).consume(user.id, feature_key)
    if not result.allowed:
        raise HTTPException(status_code=429, detail=result.detail())
    return result

def require_daily_quota(feature_key):
    async def dependency(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
        await consume_daily_quota(db, user, feature_key)
        return user
    return dependency

@router.get("/session")
async def get_session(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return JSONResponse({"logged_in": True, "access_mode": "public", "login_required": False,
        "user": {"id": user.id, "nickname": user.wechat_nickname or "访客",
                 "avatar": user.wechat_avatar or "", "is_guest": is_guest_user(user)},
        "quota": await DailyQuotaService(db).usage(user.id)}, headers={"Cache-Control": "no-store"})

@router.get("/qq/login")
@router.get("/qq/callback")
@router.get("/wechat/login")
@router.get("/wechat/callback")
@router.post("/dev/login")
@router.post("/invite/redeem")
async def retired_login():
    raise HTTPException(status_code=410, detail={"code": "PUBLIC_ACCESS", "message": "本站已全部免费开放，无需登录或会员。"})

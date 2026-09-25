"""
Auth API - 第三方登录和开发模式认证

支持QQ互联登录 + 基于HttpOnly Cookie的会话管理
"""
from datetime import datetime, timedelta, timezone
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Header, Cookie
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import secrets
import re
from urllib.parse import urlparse

from core.database import get_db
from core.config import settings
from modules.literature_pool.services.auth_service import AuthService
from modules.literature_pool.schemas.auth import TokenResponse, InviteRedeemRequest
from modules.literature_pool.models.activation_code import MembershipActivationCode
from modules.literature_pool.models.user import User
from modules.literature_pool.services.usage_limit_service import UsageLimitService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

ANON_COOKIE_KEY = "sm_anon_id"
LEGACY_GUEST_OPENID = "public_guest"
ANON_OPENID_PREFIX = "anon:"

WEEKLY_FEATURE_LIMITS: dict[str, int] = {
    "sports_data_search": 5,
    "sports_data_article_metrics": 5,
    "wiw_generate": 3,
    "assistant_chat": 3,
}

def _cookie_domain_for(host: str | None) -> str | None:
    """
    生产环境支持 www / apex 共享 Cookie（避免登录后切换域名丢会话）。
    """
    if not host:
        return None
    host = host.split(":")[0].strip().lower()
    if host.endswith("sports-matter.com"):
        return ".sports-matter.com"
    return None


def _set_auth_cookie(response: RedirectResponse, *, token: str, secure: bool, domain: str | None) -> None:
    """
    设置登录 Cookie（domain cookie + host-only cookie），兼容历史/浏览器差异。
    """
    # domain cookie（覆盖 www 与 apex）
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        domain=domain,
        path="/",
        max_age=7 * 24 * 60 * 60,
    )
    # host-only cookie（覆盖旧的 host-only auth_token，避免极端情况下 Cookie 解析选错）
    response.set_cookie(
        key="auth_token",
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=7 * 24 * 60 * 60,
    )


def is_guest_user(user: User) -> bool:
    openid = (getattr(user, "wechat_openid", None) or "").strip()
    return openid == LEGACY_GUEST_OPENID or openid.startswith(ANON_OPENID_PREFIX)


def is_member_user(user: User) -> bool:
    if not user:
        return False
    if bool(getattr(user, "membership_is_lifetime", False)):
        return True
    exp = getattr(user, "membership_expires_at", None)
    if not exp:
        return False
    now = datetime.now(timezone.utc)
    if getattr(exp, "tzinfo", None) is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > now


async def get_current_user(
    authorization: str | None = Header(default=None),
    auth_token: str | None = Cookie(default=None),
    anon_id: str | None = Cookie(default=None, alias=ANON_COOKIE_KEY),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    获取当前用户（无凭证时返回“访客”用户）
    """
    auth_service = AuthService(db)

    token: str | None = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "", 1).strip() or None
    if not token:
        token = auth_token

    user_id = auth_service.verify_jwt_token(token) if token else None
    if user_id:
        user = await auth_service.get_user_by_id(user_id)
        if user:
            return user

    effective_anon = (anon_id or "").strip()
    if effective_anon:
        # 仅允许 URL-safe 字符，避免超长/异常值导致 openid 超出字段长度
        effective_anon = re.sub(r"[^a-zA-Z0-9_-]", "", effective_anon)[:48]
    if effective_anon:
        openid = f"{ANON_OPENID_PREFIX}{effective_anon}"
    else:
        openid = LEGACY_GUEST_OPENID

    return await auth_service.get_or_create_user(
        openid=openid,
        unionid=None,
        nickname="访客",
        avatar="",
    )


async def require_login_user(user: User = Depends(get_current_user)) -> User:
    if is_guest_user(user):
        raise HTTPException(
            status_code=401,
            detail={"code": "LOGIN_REQUIRED", "message": "该模块需要登录后使用"},
        )
    return user


async def require_member_user(user: User = Depends(get_current_user)) -> User:
    if is_guest_user(user):
        raise HTTPException(
            status_code=401,
            detail={"code": "LOGIN_REQUIRED", "message": "该模块需要登录后使用"},
        )
    if not is_member_user(user):
        raise HTTPException(
            status_code=403,
            detail={"code": "MEMBERSHIP_REQUIRED", "message": "该模块仅会员可用"},
        )
    return user


@router.post("/invite/redeem")
async def redeem_invite_code(
    data: InviteRedeemRequest,
    user: User = Depends(require_login_user),
    db: AsyncSession = Depends(get_db),
):
    """
    邀请码兑换：支持“终身邀请码 / 一次性激活码 / 新用户一周体验”

    支持两类邀请码：
    1) 一次性激活码（DB 表 membership_activation_codes，保存 code_hash，使用后不可重复）
    2) 全局邀请码（受环境变量开关控制：INVITE_LIFETIME_ENABLED，默认 BSU）
    3) 新用户一周会员（受环境变量开关控制：INVITE_WEEK_ENABLED，默认 sports-matter.com）
    """
    code = (data.code or "").strip()
    if not code:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_INVITE_CODE", "message": "请输入邀请码"},
        )

    now = datetime.now(timezone.utc)

    def _membership_payload(u: User) -> dict:
        return {
            "tier": getattr(u, "membership_tier", None),
            "is_lifetime": bool(getattr(u, "membership_is_lifetime", False)),
            "started_at": u.membership_started_at.isoformat() if getattr(u, "membership_started_at", None) else None,
            "expires_at": u.membership_expires_at.isoformat() if getattr(u, "membership_expires_at", None) else None,
        }

    # 0) 新用户一周会员（仅首次生效；优先级最高，避免与其他邀请码冲突）
    #    ⚠️ 需求：sports-matter.com 只能解锁 7 天，绝不应触发终身逻辑。
    week_code = (getattr(settings, "invite_week_code", "") or "").strip()
    if bool(getattr(settings, "invite_week_enabled", False)) and week_code and code.lower() == week_code.lower():
        # 已终身会员：直接返回（不改变会员状态）
        if bool(getattr(user, "membership_is_lifetime", False)):
            return {"ok": True, "membership": _membership_payload(user)}

        # 仅新用户（未有任何会员历史）可领取
        started_at = getattr(user, "membership_started_at", None)
        if started_at is None:
            try:
                days = int(getattr(settings, "invite_week_days", 7) or 7)
            except Exception:
                days = 7
            days = max(1, min(days, 30))

            user.membership_tier = "weekly_invite"
            user.membership_is_lifetime = False
            user.membership_started_at = now
            user.membership_expires_at = now + timedelta(days=days)
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return {"ok": True, "membership": _membership_payload(user)}

        # 幂等：如果已经领取且当前仍在有效期内，则直接返回
        tier = (getattr(user, "membership_tier", "") or "").strip().lower()
        exp = getattr(user, "membership_expires_at", None)
        if tier == "weekly_invite" and exp is not None:
            if getattr(exp, "tzinfo", None) is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > now:
                return {"ok": True, "membership": _membership_payload(user)}
            raise HTTPException(
                status_code=400,
                detail={"code": "INVITE_CODE_USED", "message": "该邀请码仅限新用户首次使用"},
            )

        raise HTTPException(
            status_code=400,
            detail={"code": "INVITE_CODE_NOT_ELIGIBLE", "message": "该邀请码仅限新用户首次使用"},
        )

    # 1) 一次性激活码：优先匹配（即使关闭全局邀请码也可用）
    try:
        code_hash = hashlib.sha256(code.lower().encode("utf-8")).hexdigest()
        stmt = select(MembershipActivationCode).where(MembershipActivationCode.code_hash == code_hash).with_for_update()
        result = await db.execute(stmt)
        activation = result.scalar_one_or_none()
    except Exception:
        activation = None

    if activation is not None:
        # 可选的禁用/过期逻辑
        if not bool(getattr(activation, "is_active", False)):
            raise HTTPException(
                status_code=400,
                detail={"code": "INVITE_CODE_DISABLED", "message": "邀请码无效"},
            )
        exp = getattr(activation, "expires_at", None)
        if exp is not None:
            if getattr(exp, "tzinfo", None) is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= now:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "INVITE_CODE_EXPIRED", "message": "邀请码已过期"},
                )

        used_at = getattr(activation, "used_at", None)
        used_by = getattr(activation, "used_by_user_id", None)
        if used_at is not None:
            # 幂等：同一用户重复兑换（不再消耗/报错）
            if used_by == user.id:
                return {"ok": True, "membership": _membership_payload(user)}

            raise HTTPException(
                status_code=400,
                detail={"code": "INVITE_CODE_USED", "message": "邀请码已被使用"},
            )

        # 若已是终身会员，不消耗一次性码（避免误伤）
        if bool(getattr(user, "membership_is_lifetime", False)):
            return {"ok": True, "membership": _membership_payload(user)}

        activation.used_at = now
        activation.used_by_user_id = user.id

        activation_tier = (getattr(activation, "tier", None) or "lifetime").strip().lower()
        if activation_tier == "lifetime":
            user.membership_tier = "lifetime"
            user.membership_is_lifetime = True
            user.membership_started_at = getattr(user, "membership_started_at", None) or now
            user.membership_expires_at = None
        elif activation_tier in {"monthly", "quarterly", "yearly"}:
            duration_days = 30 if activation_tier == "monthly" else 90 if activation_tier == "quarterly" else 365
            exp = getattr(user, "membership_expires_at", None)
            base = now
            is_active_member = False
            if exp is not None:
                if getattr(exp, "tzinfo", None) is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp > now:
                    base = exp
                    is_active_member = True

            current_tier = (getattr(user, "membership_tier", "") or "").strip().lower()
            # 不降级：如果用户当前仍在有效期内且为 yearly，monthly/quarterly 激活码只延长有效期，不改 tier
            if not (
                activation_tier in {"monthly", "quarterly"}
                and is_active_member
                and current_tier == "yearly"
            ):
                user.membership_tier = activation_tier

            user.membership_is_lifetime = False
            user.membership_started_at = getattr(user, "membership_started_at", None) or now
            user.membership_expires_at = base + timedelta(days=duration_days)
        else:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVITE_CODE_INVALID_TIER", "message": "邀请码配置错误"},
            )

        db.add(activation)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return {"ok": True, "membership": _membership_payload(user)}

    # 2) 全局邀请码（可随时关闭）
    expected = (getattr(settings, "invite_lifetime_code", "") or "").strip()
    if bool(getattr(settings, "invite_lifetime_enabled", False)) and expected and code.lower() == expected.lower():
        if not bool(getattr(user, "membership_is_lifetime", False)):
            user.membership_tier = "lifetime"
            user.membership_is_lifetime = True
            user.membership_started_at = getattr(user, "membership_started_at", None) or now
            user.membership_expires_at = None
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return {"ok": True, "membership": _membership_payload(user)}

    # 未命中任何邀请码
    raise HTTPException(
        status_code=400,
        detail={"code": "INVALID_INVITE_CODE", "message": "邀请码无效"},
    )


def require_weekly_quota(feature_key: str, limit: int):
    """
    依赖工厂：对未登录/非会员用户执行“每周 N 次”额度限制；会员不限额
    """

    async def _dep(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if is_member_user(user):
            return user

        limiter = UsageLimitService(db)
        result = await limiter.consume_weekly_quota(
            user_id=user.id,
            feature_key=feature_key,
            limit=limit,
        )
        if not result.allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "WEEKLY_LIMIT_EXCEEDED",
                    "message": f"本功能每周最多 {result.limit} 次（本周已用 {result.used} 次）",
                    "feature": result.feature_key,
                    "week_start": result.week_start.isoformat(),
                    "week_end": result.week_end.isoformat(),
                    "limit": result.limit,
                    "used": result.used,
                    "remaining": result.remaining,
                },
            )
        return user

    return _dep


# ==========================================
# 微信登录路由
# ==========================================

@router.get("/wechat/login")
async def wechat_login(db: AsyncSession = Depends(get_db)):
    """
    生成微信扫码登录URL

    Returns:
        包含qr_url的响应，供前端iframe展示
    """
    auth_service = AuthService(db)

    # 生成随机state防CSRF
    state = secrets.token_urlsafe(32)

    # 生成微信扫码URL
    qr_url = auth_service.generate_wechat_qr_url(state)

    return {"qr_url": qr_url, "state": state}


@router.get("/wechat/callback")
async def wechat_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db)
):
    """
    微信扫码登录回调，设置HttpOnly Cookie

    Args:
        code: 微信返回的授权码
        state: 防CSRF的state参数

    Returns:
        重定向到前端首页，并设置HttpOnly Cookie
    """
    auth_service = AuthService(db)

    try:
        # 1. 用code换取access_token和openid
        print(f"✅ Wechat callback: code={code[:10]}..., state={state[:10]}...")
        token_data = await auth_service.exchange_code_for_token(code)

        # 2. 获取微信用户信息
        user_info = await auth_service.get_wechat_user_info(
            token_data["access_token"],
            token_data["openid"]
        )
        print(f"✅ Wechat user info: openid={user_info['openid'][:10]}..., nickname={user_info.get('nickname')}")

        # 3. 创建或更新用户
        user = await auth_service.get_or_create_user(
            openid=user_info["openid"],
            unionid=user_info.get("unionid"),
            nickname=user_info.get("nickname", "微信用户"),
            avatar=user_info.get("avatar", "")
        )
        print(f"✅ User created/updated: id={user.id}, nickname={user.wechat_nickname}")

        # 4. 签发JWT
        jwt_token = auth_service.create_jwt_token(user.id)

        # 5. 重定向到前端，并设置HttpOnly Cookie
        frontend_home = "http://localhost:3000"
        if settings.wechat_redirect_uri:
            parsed = urlparse(settings.wechat_redirect_uri)
            if parsed.scheme and parsed.netloc:
                frontend_home = f"{parsed.scheme}://{parsed.netloc}"

        response = RedirectResponse(url=frontend_home, status_code=302)
        _set_auth_cookie(
            response,
            token=jwt_token,
            secure=frontend_home.startswith("https"),
            domain=_cookie_domain_for(urlparse(frontend_home).hostname),
        )

        print(f"✅ Login successful, redirecting to frontend")
        return response

    except ValueError as e:
        # 微信授权失败或取消
        error_msg = str(e)
        print(f"❌ Wechat auth failed: {error_msg}")
        frontend_home = "http://localhost:3000"
        if settings.wechat_redirect_uri:
            parsed = urlparse(settings.wechat_redirect_uri)
            if parsed.scheme and parsed.netloc:
                frontend_home = f"{parsed.scheme}://{parsed.netloc}"
        return RedirectResponse(url=f"{frontend_home}?error=wechat_auth_failed&detail={error_msg}")
    except Exception as e:
        # 其他系统错误
        print(f"❌ System error in wechat callback: {type(e).__name__}: {e}")
        frontend_home = "http://localhost:3000"
        if settings.wechat_redirect_uri:
            parsed = urlparse(settings.wechat_redirect_uri)
            if parsed.scheme and parsed.netloc:
                frontend_home = f"{parsed.scheme}://{parsed.netloc}"
        return RedirectResponse(url=f"{frontend_home}?error=system_error")


# ==========================================
# QQ登录路由（QQ互联 OAuth2）
# ==========================================

@router.get("/qq/login")
async def qq_login(db: AsyncSession = Depends(get_db)):
    """
    生成QQ互联登录URL（供前端iframe展示/跳转）
    """
    auth_service = AuthService(db)
    state = secrets.token_urlsafe(32)
    try:
        login_url = auth_service.generate_qq_login_url(state)
    except ValueError as e:
        raise HTTPException(status_code=501, detail=str(e))
    return {"qr_url": login_url, "state": state}


@router.get("/qq/callback")
async def qq_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    """
    QQ登录回调，设置HttpOnly Cookie
    """
    auth_service = AuthService(db)
    frontend_home = "http://localhost:3000"
    if settings.qq_redirect_uri:
        parsed = urlparse(settings.qq_redirect_uri)
        if parsed.scheme and parsed.netloc:
            frontend_home = f"{parsed.scheme}://{parsed.netloc}"

    try:
        token_data = await auth_service.exchange_qq_code_for_token(code)
        openid_data = await auth_service.get_qq_openid(token_data["access_token"])
        qq_openid = str(openid_data["openid"])
        qq_unionid = openid_data.get("unionid")

        user_info = None
        try:
            user_info = await auth_service.get_qq_user_info(token_data["access_token"], qq_openid)
        except Exception as e:
            # user_info 获取失败不应阻断登录（至少让用户能进站）
            logger.warning("QQ user_info failed, continue with minimal profile: %s", str(e))
            user_info = {"nickname": "QQ用户", "avatar": ""}

        user = await auth_service.get_or_create_user(
            openid=f"qq:{qq_openid}",
            unionid=f"qq:{qq_unionid}" if qq_unionid else None,
            nickname=user_info.get("nickname") or "QQ用户",
            avatar=user_info.get("avatar") or "",
            login_source="qq",
        )

        jwt_token = auth_service.create_jwt_token(user.id)

        response = RedirectResponse(url=frontend_home, status_code=302)
        _set_auth_cookie(
            response,
            token=jwt_token,
            secure=frontend_home.startswith("https"),
            domain=_cookie_domain_for(urlparse(frontend_home).hostname),
        )
        return response

    except ValueError as e:
        logger.warning("QQ callback failed: %s", str(e))
        return RedirectResponse(url=f"{frontend_home}?error=qq_auth_failed&detail={str(e)}")
    except Exception:
        logger.exception("QQ callback system error")
        return RedirectResponse(url=f"{frontend_home}?error=system_error")


@router.get("/session")
async def get_session(
    authorization: str | None = Header(default=None),
    auth_token: str | None = Cookie(default=None),
    anon_id: str | None = Cookie(default=None, alias=ANON_COOKIE_KEY),
    db: AsyncSession = Depends(get_db),
):
    """
    查询当前会话状态（基于HttpOnly Cookie）

    Returns:
        未登录: {"logged_in": false}
        已登录: {"logged_in": true, "user": {...}}
    """
    user = await get_current_user(
        authorization=authorization,
        auth_token=auth_token,
        anon_id=anon_id,
        db=db,
    )
    is_guest = is_guest_user(user)
    is_member = is_member_user(user)
    payload = {
        "logged_in": True,
        "user": {
            "id": user.id,
            "nickname": user.wechat_nickname or ("访客" if is_guest else "用户"),
            "avatar": user.wechat_avatar or "",
            "is_guest": is_guest,
            "is_member": is_member,
            "membership_tier": getattr(user, "membership_tier", None),
            "membership_is_lifetime": bool(getattr(user, "membership_is_lifetime", False)),
            "membership_expires_at": (
                user.membership_expires_at.isoformat()
                if getattr(user, "membership_expires_at", None)
                else None
            ),
        },
    }

    # 试用次数展示：返回本周使用情况（会员不限制，但仍返回 week 范围便于前端展示）
    try:
        limiter = UsageLimitService(db)
        week_start, week_end, counts = await limiter.get_weekly_usage_counts(
            user_id=user.id,
            feature_keys=list(WEEKLY_FEATURE_LIMITS.keys()),
        )
        features = {}
        for feature_key, limit in WEEKLY_FEATURE_LIMITS.items():
            used = int(counts.get(feature_key, 0) or 0)
            remaining = None if is_member else max(0, int(limit) - used)
            features[feature_key] = {
                "limit": None if is_member else int(limit),
                "used": used,
                "remaining": remaining,
            }
        payload["quota"] = {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "features": features,
        }
    except Exception:
        payload["quota"] = None

    # 仅对访客补齐 anon cookie，确保试用次数按浏览器隔离
    response = JSONResponse(content=payload)
    effective_anon_cookie = re.sub(r"[^a-zA-Z0-9_-]", "", (anon_id or "").strip())[:48]
    if is_guest and not effective_anon_cookie:
        new_anon = secrets.token_urlsafe(16)
        cookie_domain = None
        try:
            cookie_domain = _cookie_domain_for(urlparse(str(getattr(settings, "qq_redirect_uri", "") or "")).hostname)
        except Exception:
            cookie_domain = None
        response.set_cookie(
            key=ANON_COOKIE_KEY,
            value=new_anon,
            httponly=False,
            secure=str(settings.app_env).lower() == "production",
            samesite="lax",
            domain=cookie_domain,
            max_age=365 * 24 * 60 * 60,
        )
    return response


@router.post("/dev/login", response_model=TokenResponse)
async def dev_login(db: AsyncSession = Depends(get_db)):
    """
    开发模式下的模拟登录（便于本地调试，无需微信）
    - 仅在 development/staging 下可用
    """
    from core.config import settings as app_settings
    if str(app_settings.app_env).lower() not in ["development", "dev", "local", "staging"]:
        raise HTTPException(status_code=403, detail="DEV_LOGIN_DISABLED")

    auth_service = AuthService(db)
    # 固定一个开发用openid
    user = await auth_service.get_or_create_user(
        openid="dev_openid",
        unionid=None,
        nickname="开发者",
        avatar="https://avatars.githubusercontent.com/u/0?v=4",
    )
    token = auth_service.create_jwt_token(user.id)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=user.id,
        nickname=user.wechat_nickname or "开发者",
        avatar=user.wechat_avatar or "",
    )


async def get_current_user_id(
    authorization: str | None = Header(default=None),
    auth_token: str | None = Cookie(default=None),
    anon_id: str | None = Cookie(default=None, alias=ANON_COOKIE_KEY),
    db: AsyncSession = Depends(get_db)
) -> int:
    """
    依赖注入：从JWT获取当前用户ID
    
    Args:
        authorization: Authorization header
        db: 数据库会话
    
    Returns:
        用户ID
    
    Raises:
        HTTPException: 认证失败
    """
    user = await get_current_user(
        authorization=authorization,
        auth_token=auth_token,
        anon_id=anon_id,
        db=db,
    )
    return user.id

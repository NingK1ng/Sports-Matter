"""
Auth Service - 第三方登录和JWT认证

目前支持：
- 微信开放平台（历史保留，可能不可用）
- QQ互联（PC网站OAuth2）
"""
import httpx
import json
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.literature_pool.models.user import User
from urllib.parse import urlencode, quote, parse_qs


class AuthService:
    """认证服务"""
    
    def __init__(self, session: AsyncSession):
        self.session = session

    # ==========================================
    # QQ互联 OAuth2
    # ==========================================
    def _get_qq_redirect_uri(self) -> str:
        return settings.qq_redirect_uri or "http://localhost:8000/api/v1/pool/auth/qq/callback"

    def _parse_qq_text_response(self, text: str) -> Dict[str, Any]:
        raw = (text or "").strip()
        if not raw:
            return {}

        # 1) callback( {...} );
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass

        # 2) query string: a=b&c=d
        try:
            qs = parse_qs(raw, keep_blank_values=True)
            if qs:
                return {k: (v[0] if isinstance(v, list) and v else "") for k, v in qs.items()}
        except Exception:
            pass

        # 3) plain JSON
        try:
            return json.loads(raw)
        except Exception:
            return {"raw": raw}

    def generate_qq_login_url(self, state: str) -> str:
        """
        生成QQ互联登录URL

        Args:
            state: 防CSRF的随机state参数
        """
        if not settings.qq_app_id:
            raise ValueError("QQ_OAUTH_NOT_CONFIGURED: missing QQ_APP_ID (client_id)")
        if not settings.qq_redirect_uri and str(settings.app_env).lower() not in ["development", "dev", "local", "staging"]:
            raise ValueError("QQ_OAUTH_NOT_CONFIGURED: missing QQ_REDIRECT_URI (callback url)")
        redirect_uri = self._get_qq_redirect_uri()
        params = {
            "response_type": "code",
            "client_id": settings.qq_app_id,
            "redirect_uri": redirect_uri,
            "scope": "get_user_info",
            "state": state,
        }
        query_string = urlencode(params, quote_via=quote, safe="")
        return f"https://graph.qq.com/oauth2.0/authorize?{query_string}"

    async def exchange_qq_code_for_token(self, code: str) -> Dict[str, Any]:
        """
        用code换取QQ access_token
        """
        if not settings.qq_app_id or not settings.qq_app_key:
            raise ValueError("QQ_OAUTH_NOT_CONFIGURED: missing QQ_APP_ID/QQ_APP_KEY (client_id/client_secret)")
        if not settings.qq_redirect_uri and str(settings.app_env).lower() not in ["development", "dev", "local", "staging"]:
            raise ValueError("QQ_OAUTH_NOT_CONFIGURED: missing QQ_REDIRECT_URI (callback url)")
        redirect_uri = self._get_qq_redirect_uri()

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.qq.com/oauth2.0/token",
                params={
                    "grant_type": "authorization_code",
                    "client_id": settings.qq_app_id,
                    "client_secret": settings.qq_app_key,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "fmt": "json",
                },
                timeout=10.0,
            )
        data = self._parse_qq_text_response(resp.text)
        if any(k in data for k in ("error", "errcode")):
            raise ValueError(f"QQ_AUTH_FAILED: {data}")
        if not data.get("access_token"):
            raise ValueError(f"QQ_AUTH_FAILED: invalid token response: {data}")
        return {
            "access_token": data.get("access_token"),
            "expires_in": data.get("expires_in"),
            "refresh_token": data.get("refresh_token"),
        }

    async def get_qq_openid(self, access_token: str) -> Dict[str, Any]:
        """
        获取QQ openid/unionid
        """
        async with httpx.AsyncClient() as client:
            # 先尝试带 unionid（部分应用未配置 CompanyID 会报错 100048）
            resp = await client.get(
                "https://graph.qq.com/oauth2.0/me",
                params={
                    "access_token": access_token,
                    "unionid": 1,
                    "fmt": "json",
                },
                timeout=10.0,
            )
            data = self._parse_qq_text_response(resp.text)
            # 兼容：未设置 CompanyID 时不要阻断登录，退回只取 openid
            if str(data.get("error")) == "100048" or "CompanyID not set" in str(data.get("error_description", "")):
                resp = await client.get(
                    "https://graph.qq.com/oauth2.0/me",
                    params={
                        "access_token": access_token,
                        "fmt": "json",
                    },
                    timeout=10.0,
                )
                data = self._parse_qq_text_response(resp.text)

        if any(k in data for k in ("error", "errcode")):
            raise ValueError(f"QQ_OPENID_FAILED: {data}")
        openid = data.get("openid")
        if not openid:
            raise ValueError(f"QQ_OPENID_FAILED: invalid response: {data}")
        return {
            "openid": openid,
            "unionid": data.get("unionid"),
        }

    async def get_qq_user_info(self, access_token: str, openid: str) -> Dict[str, Any]:
        """
        获取QQ用户信息
        """
        if not settings.qq_app_id:
            raise ValueError("QQ_OAUTH_NOT_CONFIGURED: missing QQ_APP_ID")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.qq.com/user/get_user_info",
                params={
                    "access_token": access_token,
                    "oauth_consumer_key": settings.qq_app_id,
                    "openid": openid,
                    "fmt": "json",
                },
                timeout=10.0,
            )
        # QQ接口偶发返回 callback(...) 或 querystring，统一走文本解析更稳
        data = self._parse_qq_text_response(resp.text)
        if int(data.get("ret", -1)) != 0:
            raise ValueError(f"QQ_USERINFO_FAILED: {data}")

        avatar = (
            data.get("figureurl_qq_2")
            or data.get("figureurl_qq_1")
            or data.get("figureurl_2")
            or data.get("figureurl_1")
            or data.get("figureurl")
            or ""
        )
        return {
            "openid": openid,
            "nickname": data.get("nickname", ""),
            "avatar": avatar,
        }
    
    # ==========================================
    # 微信开放平台 OAuth2（保留）
    # ==========================================
    def generate_wechat_qr_url(self, state: str) -> str:
        """
        生成微信扫码登录URL
        
        Args:
            state: 防CSRF的随机state参数
        
        Returns:
            微信授权URL
        """
        # 允许本地开发默认回调到后端托管的前端
        redirect_uri = (
            settings.wechat_redirect_uri
            or "http://localhost:8000/frontend/auth/wechat/callback"
        )
        params = {
            "appid": settings.wechat_app_id or "",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "snsapi_login",
            "state": state,
        }
        # 按规范对 redirect_uri 进行 URL 编码
        query_string = urlencode(params, quote_via=quote, safe="")
        return f"https://open.weixin.qq.com/connect/qrconnect?{query_string}#wechat_redirect"
    
    async def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        """
        用code换取access_token
        
        Args:
            code: 微信回调返回的授权码
        
        Returns:
            包含access_token和openid的字典
        
        Raises:
            ValueError: 换取token失败
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.weixin.qq.com/sns/oauth2/access_token",
                params={
                    "appid": settings.wechat_app_id,
                    "secret": settings.wechat_app_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
                timeout=10.0
            )
            
            data = response.json()
            
            if "errcode" in data:
                raise ValueError(f"WECHAT_AUTH_FAILED: {data.get('errmsg', 'Unknown error')}")
            
            return {
                "access_token": data["access_token"],
                "openid": data["openid"],
                "unionid": data.get("unionid"),  # 可能没有unionid
            }
    
    async def get_wechat_user_info(self, access_token: str, openid: str) -> Dict[str, Any]:
        """
        获取微信用户信息
        
        Args:
            access_token: 微信access_token
            openid: 微信openid
        
        Returns:
            用户信息字典
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.weixin.qq.com/sns/userinfo",
                params={
                    "access_token": access_token,
                    "openid": openid,
                },
                timeout=10.0
            )
            
            data = response.json()
            
            if "errcode" in data:
                raise ValueError(f"WECHAT_USERINFO_FAILED: {data.get('errmsg', 'Unknown error')}")
            
            return {
                "openid": data["openid"],
                "nickname": data.get("nickname", ""),
                "avatar": data.get("headimgurl", ""),
                "unionid": data.get("unionid"),
            }
    
    async def get_or_create_user(
        self,
        openid: str,
        unionid: Optional[str],
        nickname: str,
        avatar: str,
        login_source: str = "wechat_open",
    ) -> User:
        """
        获取或创建用户
        
        Args:
            openid: 微信openid
            unionid: 微信unionid（可选）
            nickname: 微信昵称
            avatar: 微信头像URL
        
        Returns:
            User对象
        """
        # 查找用户
        stmt = select(User).where(User.wechat_openid == openid)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user:
            # 更新最后登录时间和信息
            user.last_login_at = datetime.now()
            user.wechat_nickname = nickname
            user.wechat_avatar = avatar
            user.login_source = login_source
            if unionid:
                user.wechat_unionid = unionid
        else:
            # 创建新用户
            user = User(
                wechat_openid=openid,
                wechat_unionid=unionid,
                wechat_nickname=nickname,
                wechat_avatar=avatar,
                login_source=login_source,
                last_login_at=datetime.now(),
            )
            self.session.add(user)
        
        await self.session.commit()
        await self.session.refresh(user)
        
        return user
    
    def create_jwt_token(self, user_id: int) -> str:
        """
        创建JWT token
        
        Args:
            user_id: 用户ID
        
        Returns:
            JWT token字符串
        """
        expire = datetime.utcnow() + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )
        
        payload = {
            "sub": str(user_id),
            "exp": expire,
            "iat": datetime.utcnow(),
        }
        
        token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm
        )
        
        return token
    
    def verify_jwt_token(self, token: str) -> Optional[int]:
        """
        验证JWT token
        
        Args:
            token: JWT token字符串
        
        Returns:
            用户ID，验证失败返回None
        """
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm]
            )
            user_id = int(payload.get("sub"))
            return user_id
        except Exception:
            return None
    
    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        """
        通过ID获取用户
        
        Args:
            user_id: 用户ID
        
        Returns:
            User对象，未找到返回None
        """
        stmt = select(User).where(User.id == user_id, User.is_active == True)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

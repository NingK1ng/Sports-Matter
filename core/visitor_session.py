"""Signed anonymous browser identity; no login or shared guest account."""
import hashlib
import hmac
import re
import secrets
from core.config import settings

COOKIE_NAME = "sm_visitor"
MAX_AGE = 365 * 24 * 60 * 60

def _signature(identifier: str) -> str:
    return hmac.new(settings.jwt_secret_key.encode(), ("visitor:" + identifier).encode(), hashlib.sha256).hexdigest()

def prepare_visitor(request):
    token = request.cookies.get(COOKIE_NAME, "")
    identifier, _, signature = token.partition(".")
    valid = bool(re.fullmatch(r"[A-Za-z0-9_-]{32}", identifier)) and hmac.compare_digest(signature, _signature(identifier))
    if not valid:
        identifier = secrets.token_urlsafe(24)
        token = identifier + "." + _signature(identifier)
    request.state.visitor_id = identifier
    request.state.visitor_cookie = None if valid else token

def set_visitor_cookie(request, response):
    token = getattr(request.state, "visitor_cookie", None)
    if token:
        response.set_cookie(COOKIE_NAME, token, max_age=MAX_AGE, httponly=True,
                            secure=str(settings.app_env).lower() == "production",
                            samesite="lax", path="/")
    return response

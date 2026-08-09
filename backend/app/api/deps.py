from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import token_digest
from app.db.models import ApiToken, UserAccount, WebSession
from app.db.session import get_db


@dataclass
class AuthContext:
    account: UserAccount
    session: WebSession | None
    via_token: bool


def require_auth(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        raw = authorization.removeprefix("Bearer ").strip()
        token = db.scalar(
            select(ApiToken).where(
                ApiToken.token_hash == token_digest(raw, settings),
                ApiToken.revoked_at.is_(None),
            )
        )
        if token:
            account = db.get(UserAccount, token.account_id)
            if account and account.active:
                token.last_used_at = datetime.now(UTC)
                db.commit()
                return AuthContext(account=account, session=None, via_token=True)

    raw_cookie = request.cookies.get(settings.session_cookie_name)
    if raw_cookie:
        web_session = db.scalar(
            select(WebSession).where(
                WebSession.token_hash == token_digest(raw_cookie, settings),
                WebSession.expires_at > datetime.now(UTC),
            )
        )
        if web_session:
            account = db.get(UserAccount, web_session.account_id)
            if account and account.active:
                return AuthContext(account=account, session=web_session, via_token=False)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")


def require_write_auth(
    request: Request,
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    if not auth.via_token:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not auth.session or supplied != auth.session.csrf_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return auth

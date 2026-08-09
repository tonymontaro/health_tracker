from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, require_auth, require_write_auth
from app.core.config import Settings, get_settings
from app.core.security import new_token, session_expiry, token_digest, verify_password
from app.db.models import ApiToken, UserAccount, WebSession
from app.db.session import get_db
from app.schemas.api import (
    ApiTokenCreated,
    ApiTokenResponse,
    LoginRequest,
    SessionResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=SessionResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SessionResponse:
    account = db.scalar(select(UserAccount).where(UserAccount.email == payload.email.lower()))
    if (
        not account
        or not account.active
        or not verify_password(payload.password, account.password_hash)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    raw_token = new_token()
    csrf_token = new_token()
    web_session = WebSession(
        account_id=account.id,
        token_hash=token_digest(raw_token, settings),
        csrf_token=csrf_token,
        expires_at=session_expiry(settings),
    )
    db.add(web_session)
    db.commit()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=settings.session_days * 86400,
        path="/",
    )
    return SessionResponse(authenticated=True, email=account.email, csrf_token=csrf_token)


@router.get("/session", response_model=SessionResponse)
def session(auth: AuthContext = Depends(require_auth)) -> SessionResponse:
    csrf = auth.session.csrf_token if auth.session else ""
    return SessionResponse(authenticated=True, email=auth.account.email, csrf_token=csrf)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    auth: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    if auth.session:
        db.delete(auth.session)
        db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/tokens", response_model=list[ApiTokenResponse])
def list_tokens(
    _: AuthContext = Depends(require_auth), db: Session = Depends(get_db)
) -> list[ApiToken]:
    return list(db.scalars(select(ApiToken).order_by(ApiToken.created_at.desc())))


@router.post("/tokens", response_model=ApiTokenCreated)
def create_token(
    name: str = "Chrome extension",
    auth: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ApiTokenCreated:
    raw = new_token()
    token = ApiToken(
        account_id=auth.account.id,
        name=name[:100],
        token_hash=token_digest(raw, settings),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return ApiTokenCreated(
        id=token.id,
        name=token.name,
        created_at=token.created_at,
        revoked_at=token.revoked_at,
        token=raw,
    )


@router.delete("/tokens/{token_id}", status_code=204)
def revoke_token(
    token_id: UUID,
    _: AuthContext = Depends(require_write_auth),
    db: Session = Depends(get_db),
) -> Response:
    token = db.get(ApiToken, token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    token.revoked_at = datetime.now(UTC)
    db.commit()
    return Response(status_code=204)

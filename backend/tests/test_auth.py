import asyncio

from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import WebSession
from app.db.session import get_db
from app.main import app


def test_password_change_revokes_other_sessions_and_logout_ends_current_session(
    db: Session, settings: Settings, seeded
) -> None:
    current_password = settings.bootstrap_password.get_secret_value()
    new_password = "a-stronger-test-password"
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: settings

    async def make_requests() -> dict[str, Response]:
        transport = ASGITransport(app=app)
        async with (
            AsyncClient(transport=transport, base_url="http://testserver") as current_client,
            AsyncClient(transport=transport, base_url="http://testserver") as other_client,
            AsyncClient(transport=transport, base_url="http://testserver") as anonymous_client,
        ):
            login_payload = {"email": settings.bootstrap_email, "password": current_password}
            current_login = await current_client.post("/api/v1/auth/login", json=login_payload)
            other_login = await other_client.post("/api/v1/auth/login", json=login_payload)
            current_csrf = current_login.json()["csrf_token"]

            anonymous_change = await anonymous_client.post(
                "/api/v1/auth/password",
                json={
                    "current_password": current_password,
                    "new_password": new_password,
                },
            )
            missing_csrf = await current_client.post(
                "/api/v1/auth/password",
                json={
                    "current_password": current_password,
                    "new_password": new_password,
                },
            )
            wrong_current = await current_client.post(
                "/api/v1/auth/password",
                headers={"X-CSRF-Token": current_csrf},
                json={
                    "current_password": "not-the-current-password",
                    "new_password": new_password,
                },
            )
            weak_password = await current_client.post(
                "/api/v1/auth/password",
                headers={"X-CSRF-Token": current_csrf},
                json={
                    "current_password": current_password,
                    "new_password": "too-short",
                },
            )
            changed = await current_client.post(
                "/api/v1/auth/password",
                headers={"X-CSRF-Token": current_csrf},
                json={
                    "current_password": current_password,
                    "new_password": new_password,
                },
            )
            other_session = await other_client.get("/api/v1/auth/session")
            current_session = await current_client.get("/api/v1/auth/session")
            logged_out = await current_client.post(
                "/api/v1/auth/logout",
                headers={"X-CSRF-Token": current_csrf},
            )
            after_logout = await current_client.get("/api/v1/auth/session")
            old_password_login = await anonymous_client.post(
                "/api/v1/auth/login",
                json={"email": settings.bootstrap_email, "password": current_password},
            )
            new_password_login = await anonymous_client.post(
                "/api/v1/auth/login",
                json={"email": settings.bootstrap_email, "password": new_password},
            )
        return {
            "current_login": current_login,
            "other_login": other_login,
            "anonymous_change": anonymous_change,
            "missing_csrf": missing_csrf,
            "wrong_current": wrong_current,
            "weak_password": weak_password,
            "changed": changed,
            "other_session": other_session,
            "current_session": current_session,
            "logged_out": logged_out,
            "after_logout": after_logout,
            "old_password_login": old_password_login,
            "new_password_login": new_password_login,
        }

    try:
        responses = asyncio.run(make_requests())
    finally:
        app.dependency_overrides.clear()

    assert responses["current_login"].status_code == 200
    assert responses["other_login"].status_code == 200
    assert responses["anonymous_change"].status_code == 401
    assert responses["missing_csrf"].status_code == 403
    assert responses["wrong_current"].status_code == 400
    assert responses["weak_password"].status_code == 422
    assert responses["changed"].status_code == 204
    assert responses["other_session"].status_code == 401
    assert responses["current_session"].status_code == 200
    assert responses["logged_out"].status_code == 204
    assert responses["after_logout"].status_code == 401
    assert responses["old_password_login"].status_code == 401
    assert responses["new_password_login"].status_code == 200
    assert db.scalar(select(func.count()).select_from(WebSession)) == 1

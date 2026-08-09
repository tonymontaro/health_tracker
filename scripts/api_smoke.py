"""Exercise authenticated API reads and a reversible token mutation."""

import httpx

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    with httpx.Client(base_url=settings.api_base_url, timeout=90) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": settings.bootstrap_email,
                "password": settings.bootstrap_password.get_secret_value(),
            },
        )
        login.raise_for_status()
        csrf = login.json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}
        checks = {}
        for name, path in {
            "session": "/api/v1/auth/session",
            "today": "/api/v1/today",
            "details": "/api/v1/today/details",
            "history": "/api/v1/history",
            "shopping": "/api/v1/shopping/current",
            "shopping_migros": "/api/v1/shopping/current?retailer=Migros",
            "profile": "/api/v1/profile",
            "equipment": "/api/v1/equipment",
            "settings": "/api/v1/settings",
        }.items():
            response = client.get(path)
            response.raise_for_status()
            checks[name] = response.status_code

        history = client.get("/api/v1/history")
        if history.json():
            history_day = client.get(f"/api/v1/history/{history.json()[0]['date']}")
            history_day.raise_for_status()
            checks["history_day"] = history_day.status_code

        created = client.post(
            "/api/v1/auth/tokens?name=API%20smoke%20test",
            headers=headers,
        )
        created.raise_for_status()
        token_id = created.json()["id"]
        bearer_check = httpx.get(
            f"{settings.api_base_url}/api/v1/today",
            headers={"Authorization": f"Bearer {created.json()['token']}"},
            timeout=90,
        )
        bearer_check.raise_for_status()
        checks["extension_bearer"] = bearer_check.status_code
        revoked = client.delete(f"/api/v1/auth/tokens/{token_id}", headers=headers)
        revoked.raise_for_status()
        checks["token_revoke"] = revoked.status_code
        logout = client.post("/api/v1/auth/logout", headers=headers)
        logout.raise_for_status()
        checks["logout"] = logout.status_code
        print({"authenticated_api": True, "checks": checks})


if __name__ == "__main__":
    main()

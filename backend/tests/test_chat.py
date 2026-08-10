import asyncio
from datetime import timedelta

from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.today import local_today
from app.core.config import Settings, get_settings
from app.core.security import token_digest
from app.db.models import ApiToken, ChatMessage
from app.db.session import get_db
from app.main import app
from app.services.planner.orchestrator import generate_daily_plan


def test_questions_and_answers_are_persisted_and_listed_newest_first(db: Session, seeded) -> None:
    api_settings = Settings(
        DATABASE_URL="postgresql+psycopg://health:health@localhost:55432/health_test",
        SESSION_SECRET="test-session-secret-with-more-than-32-characters",
        _env_file=None,
    )
    target = local_today(api_settings)
    generate_daily_plan(db, api_settings, target, use_ai=False)
    raw_token = "test-chat-token"
    db.add(
        ApiToken(
            account_id=seeded.account_id,
            name="chat test",
            token_hash=token_digest(raw_token, api_settings),
        )
    )
    db.add(
        ChatMessage(
            message_date=target - timedelta(days=1),
            question="What did yesterday's plan prioritize?",
            answer="Yesterday's plan prioritized recovery.",
            proposal_json=None,
        )
    )
    db.commit()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_settings] = lambda: api_settings

    async def make_requests() -> tuple[Response, Response, Response, Response, Response]:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            unauthenticated = await client.get("/api/v1/today/questions")
            first = await client.post(
                "/api/v1/today/questions",
                headers={"Authorization": f"Bearer {raw_token}"},
                json={"question": "Why is today's workout easy?"},
            )
            second = await client.post(
                "/api/v1/today/questions",
                headers={"Authorization": f"Bearer {raw_token}"},
                json={"question": "What should I focus on during the run?"},
            )
            messages = await client.get(
                f"/api/v1/today/questions?date={target.isoformat()}",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
            previous = await client.get(
                f"/api/v1/today/questions?before={target.isoformat()}",
                headers={"Authorization": f"Bearer {raw_token}"},
            )
        return unauthenticated, first, second, messages, previous

    try:
        unauthenticated, first, second, messages, previous = asyncio.run(make_requests())
    finally:
        app.dependency_overrides.clear()

    assert unauthenticated.status_code == 401
    assert first.status_code == 200
    assert second.status_code == 200
    assert messages.status_code == 200
    assert previous.status_code == 200
    assert [item["question"] for item in messages.json()] == [
        "What should I focus on during the run?",
        "Why is today's workout easy?",
    ]
    assert all(item["answer"] for item in messages.json())
    assert all(item["message_date"] == target.isoformat() for item in messages.json())
    assert [item["question"] for item in previous.json()] == [
        "What did yesterday's plan prioritize?"
    ]
    assert len(list(db.scalars(select(ChatMessage)))) == 3

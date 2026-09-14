"""Check the selected AI provider with synthetic data and no database access."""

import json
from time import monotonic

from app.core.config import get_settings
from app.schemas.api import QAResponse
from app.services.ai import (
    AIConfigurationError,
    AIProviderError,
    AISchemaError,
    generate_structured,
)
from app.services.workout_log import WorkoutLogExtractionError, WorkoutLogExtractor


def main() -> None:
    settings = get_settings()
    started = monotonic()
    try:
        answer = generate_structured(
            settings,
            task="qa",
            system_prompt="Answer briefly using only the supplied facts. Propose no plan changes.",
            user_prompt="Synthetic test: today's workout is a 10-minute walk. What is planned?",
            response_model=QAResponse,
        )
        workout = WorkoutLogExtractor(settings).extract(
            "I walked for 10 minutes. Difficulty was 2 out of 10. No pain.", []
        )
        if (
            workout.did_no_workout
            or len(workout.workouts) != 1
            or workout.workouts[0].duration_seconds != 600
            or workout.workouts[0].pain_flag
        ):
            raise AISchemaError("Synthetic workout extraction did not preserve the supplied facts")
    except (
        AIConfigurationError,
        AIProviderError,
        AISchemaError,
        WorkoutLogExtractionError,
    ) as exc:
        raise SystemExit(f"AI smoke check failed: {exc}") from None
    print(
        json.dumps(
            {
                "provider": settings.ai_provider,
                "model": settings.ai_model("workout_log"),
                "qa_parsed": bool(answer.answer),
                "workout_parsed": True,
                "duration_seconds": workout.workouts[0].duration_seconds,
                "elapsed_seconds": round(monotonic() - started, 1),
            }
        )
    )


if __name__ == "__main__":
    main()

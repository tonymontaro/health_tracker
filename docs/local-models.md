# Local AI with Ollama and Qwen3.8

The backend can send all planning, diary extraction, Q&A, and coaching requests directly to Ollama.
The initial model is `qwen3.8:27b-q4_K_M`, a 4-bit build suitable for evaluation on a 32 GB M1 Max Mac Studio.
Install or update [Ollama](https://ollama.com/download) to version 0.34 or newer.

## Start Ollama and download the model

If Ollama is already running, use that instance rather than starting another server.
For a terminal-managed server, run:

```bash
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 ollama serve
```

In a second terminal, download the model and check that it appears in the list:

```bash
ollama pull qwen3.8:27b-q4_K_M
curl -fsS http://127.0.0.1:11434/api/tags
```

The [model download](https://ollama.com/library/qwen3.8:27b-q4_K_M) is approximately 18 GB.
Leave memory available for macOS, the app, and the context cache.
When using the Ollama desktop app or another service manager, set the concurrency limits in that server's environment instead.

## Connect Health Autopilot

Add or update these keys in the existing private `.env`, preserving its other values:

```dotenv
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.8:27b-q4_K_M
OLLAMA_TIMEOUT_SECONDS=600
OLLAMA_NUM_CTX=16384
OLLAMA_NUM_PREDICT=8192
OLLAMA_PLANNER_THINK=true
OLLAMA_THINK=false
```

Restart the backend and scheduler after changing configuration.
Use `make api` to start the backend, and the existing scheduler commands if you run scheduled jobs.
The backend calls Ollama's `/api/chat` endpoint; the browser continues to use the application's API.
No OpenAI key is required in Ollama mode, and local failures never trigger a hosted OpenAI request.
To switch back, set `AI_PROVIDER=openai` and configure the existing `OPENAI_*` keys.
OpenAI remains the default for existing installations that omit `AI_PROVIDER`.

## Verify the connection

From the repository root, run:

```bash
AI_PROVIDER=ollama .venv/bin/python scripts/ai_smoke.py
```

This checks Q&A JSON and a synthetic workout diary through the same provider code used by the app, without accessing the database.
Success prints `qa_parsed: true`, `workout_parsed: true`, and a 600-second walk.
The first request can take longer while the model loads.

The app sends Pydantic schemas using [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs) and validates the result again before use.
Large string limits remain in the prompt and application validation but are omitted from the decoding schema to avoid a [llama.cpp grammar compilation bug](https://github.com/ggml-org/llama.cpp/issues/27087).
Planning enables thinking by default; diary extraction, Q&A, and coach messages disable it for shorter responses.
`OLLAMA_NUM_PREDICT` limits generated tokens, including thinking.
Incomplete output is rejected, and requests disable prompt truncation and context shifting.
If a request exceeds the context budget, increase `OLLAMA_NUM_CTX` cautiously, for example to `32768`, while watching memory pressure.
For output-limit failures, reduce thinking or increase `OLLAMA_NUM_PREDICT` within the available context budget.

An HTTP 404 usually means the configured model has not been pulled.
Diary errors include sanitized provider or validation details; HTTP failures stop immediately instead of retrying with a revised prompt.
Connection errors mean Ollama is unreachable, and timeouts may require a larger `OLLAMA_TIMEOUT_SECONDS`.
Planning retains its bounded repair and deterministic fallback; failed diary extraction leaves recorded data unchanged.

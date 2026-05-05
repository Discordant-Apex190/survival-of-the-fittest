## Survival of the Fittest

Autonomous evolution simulation where AI-generated creatures fight, evolve, and spawn rivals over time.

Current status: backend foundation is scaffolded (FastAPI app, SQLite models, health routes, tests).

## Stack (current)

- Python 3.11+
- FastAPI
- SQLModel + SQLite
- Loguru
- Pytest + Ruff

## Quick Start

1. Install dependencies:

```powershell
uv sync --extra dev --extra ai
```

2. Run the API locally:

```powershell
uv run uvicorn backend.main:app --reload
```

3. Run tests:

```powershell
uv run pytest
```

4. Run lint:

```powershell
uv run ruff check .
uv run ruff format .
```

## Endpoints (initial)

- `GET /` returns backend status message
- `GET /health` returns environment-aware health payload

## Project Structure

```text
backend/
	api/routes/health.py
	core/config.py
	core/logging.py
	db/models.py
	db/session.py
	graphs/state.py
	main.py
tests/
	conftest.py
	test_health.py
```

## Environment Variables

The app reads environment variables from `secrets.env`.

Required later for AI/TTS integrations:

- `GOOGLE_API_KEY`
- `CARTESIA_API_KEY`

## Next Milestone

Implement Graph 1 (`creature_factory_graph`) with mock-first provider adapters and the first generation endpoint.

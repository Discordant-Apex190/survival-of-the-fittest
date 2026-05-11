## Survival of the Fittest

Autonomous evolution simulation where AI-generated creatures fight, evolve, and spawn rivals over time.

## Stack

**Backend**
- Python 3.11+
- FastAPI + Uvicorn
- SQLModel + SQLite
- LangGraph (AI orchestration graphs)
- Google Gemini (creature generation, evolution, commentary)
- Cartesia (TTS for taunts)
- Loguru

**Frontend**
- SvelteKit (static adapter)
- PixiJS 8 (arena renderer with particles and physics)
- Matter.js (physics engine)
- Zod (schema validation)
- TypeScript

**Testing / Tooling**
- Pytest + pytest-asyncio
- Ruff (lint + format)
- Jest (frontend)

## Quick Start

1. Install dependencies:

```bash
uv sync --extra dev --extra ai
```

2. Copy the env file and fill in your API keys:

```bash
cp frontend/.env.example secrets.env
# Edit secrets.env: set GOOGLE_API_KEY and CARTESIA_API_KEY
```

3. Run the API:

```bash
uv run uvicorn backend.main:app --reload
```

4. Run the frontend dev server:

```bash
cd frontend && npm install && npm run dev
```

5. Run backend tests:

```bash
uv run pytest
```

6. Lint:

```bash
uv run ruff check .
uv run ruff format .
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Backend status |
| GET | `/health` | Environment-aware health payload |
| GET/POST | `/creatures` | List and generate creatures |
| GET | `/creatures/{id}` | Creature detail with abilities and taunts |
| GET/POST | `/fights` | Fight history and trigger manual fights |
| POST | `/simulation/tick` | Run one full simulate tick |
| GET | `/analytics/*` | Win rates, element matchups, lineage stats |
| POST | `/betting/*` | Place and settle token bets |
| WS | `/ws` | Real-time fight and simulation events |

## Project Structure

```
backend/
  api/routes/        # FastAPI routers: creatures, fights, simulation, analytics, betting, ws
  core/              # Settings (pydantic-settings) and logging config
  db/                # SQLModel models and session management
  fight/             # Fight engine: behavior trees, genetic mixing, win probability
  graphs/            # LangGraph graphs and shared state
    nodes/           # Graph nodes: Gemini, TTS, validators, DB writers
    creature_factory.py
    evolution.py
    rival.py
    commentary.py
  simulation/        # Tick loop: populate → matchmake → fight → evolve/rival
  ws/                # WebSocket connection manager

frontend/src/
  lib/
    api/             # REST client and WebSocket wrapper
    components/      # Arena.svelte (PixiJS host)
    pixi/            # Animator, arena, particles, physics, sprite helpers
    schemas/         # Zod schemas for creatures, fights, commentary, WS events
    stores/          # Svelte stores: fight, bet, votes, leaderboard, commentary
  routes/
    +page.svelte     # Main arena + betting UI
    analytics/       # Win/loss stats and element matchup charts
    builder/         # Manual creature builder
    debug/           # Dev controls: manual tick, raw state inspector
    lineage/         # Creature family tree
    replay/          # Fight replay viewer

tests/               # Pytest: fight engine, creature generation, evolution, rival,
                     # commentary, simulation engine, token rewards, TTS node, graph nodes
```

## AI Graphs

Each graph is a LangGraph `StateGraph` that runs a prompt pipeline and writes results to SQLite.

| Graph | Trigger | What it does |
|-------|---------|--------------|
| `creature_factory_graph` | Population low / manual | Generates concept → stats → taunts → validates → writes DB → queues TTS |
| `evolution_graph` | Creature reaches win threshold | Analyses fight history → decides stat boosts / new ability → updates lore → writes child creature |
| `rival_graph` | Dominant creature detected | Designs a counter-creature seeded against the dominant one's weaknesses |
| `commentary_graph` | Post-fight | Generates multi-line commentary with narrative threads |

## Simulation Tick

One tick (`POST /simulation/tick`) runs the full cycle:

1. **Populate** — spawn new creatures if population is below threshold
2. **Matchmake** — pair active creatures by tier
3. **Fight** — run behavior-tree fights, emit WS events per turn
4. **Resolve** — evolve winners above threshold, trigger rival generation, retire losers

## Environment Variables

Loaded from `secrets.env` in the project root.

| Variable | Required for |
|----------|-------------|
| `GOOGLE_API_KEY` | Gemini creature generation, evolution, commentary |
| `CARTESIA_API_KEY` | TTS audio for creature taunts |
| `DATABASE_URL` | SQLite path (defaults to `sqlite:///./data/sotf.db`) |
| `APP_ENV` | `development` / `production` / `test` |

## Known Gaps / Next Up

- **Commentary not wired into the tick loop** — `commentary_graph` exists but `simulation/engine.py` doesn't call it yet; post-fight commentary is the next integration point
- **Replay serialization** — `Fight.fight_log` is stored but the fight engine needs to write structured per-turn events for the replay page to consume
- **Per-creature PixiJS sprites** — the arena renderer uses the PixiJS layer but creature-specific visuals are not yet driven by `visual_descriptor` data
- **CORS** — currently `allow_origins=["*"]`; restrict to the frontend origin before any public deployment

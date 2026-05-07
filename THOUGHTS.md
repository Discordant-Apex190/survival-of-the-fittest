# Project Thoughts — Survival of the Fittest

## What This Is

An autonomous, self-running spectator sport. AI creatures are generated, fight in a turn-based arena, evolve when they win enough, and get a hand-crafted rival spawned against them when they dominate too long. Viewers watch in real time, bet on outcomes, and hear AI-generated commentary with TTS audio. The simulation ticks on its own; humans just watch.

---

## What's Working Well

### The simulation loop is clean

`run_tick` in `simulation/engine.py` cleanly separates the four concerns — populate, matchmake, fight, resolve — into discrete steps. Each step is independently testable and the tick result carries a full audit trail. That's a good foundation.

### The fight engine is richer than it needs to be (in a good way)

The `transitions` state machine (`fight/engine.py`) gives each combatant a proper state graph (Idle → Engage → Attack/Defend/Flee/Rage) rather than a flat random number. Behavior weights (`aggression`, `caution`, `cunning`, `risk_tolerance`) and a behavior tree (`fight/behavior_tree.py`) produce emergent fighting styles. The flee-bait/counter mechanic for high-cunning creatures is a nice touch — it creates narrative moments, not just damage numbers.

### LangGraph pipelines are well-scoped

Each graph (creature factory, evolution, rival, commentary) has a defined input/output contract through `GraphState`, with validation nodes and retry loops baked in. The mock-first design pattern (provider injected, not hardcoded) makes tests cheap to write and run offline.

### WebSocket + betting window is a solid real-time hook

Opening the betting window before broadcasting the fight preview, then blocking until ≥50% of clients have bet (or 12s max), is a smart pressure mechanic. It keeps viewers engaged without hard-blocking the simulation indefinitely.

---

## Things Worth Thinking About

### `wait_for_bets` blocks the simulation thread

`step_fight` calls `manager.wait_for_bets(fight_id, max_wait=12.0)` synchronously inside a FastAPI route/background task. If a tick runs fights sequentially (`for pair in matchmake.pairs`), each fight adds up to 12s of wall-clock delay. With 3 fights per tick that's potentially 36s of blocking. Consider running fights concurrently (asyncio gather or a thread pool) or making the betting wait async-native.

### `_build_fight_history` drops opponent context

`opponent_element` is hardcoded to `None` and `abilities_used` is always `[]`. The evolution graph receives this and uses it to decide stat boosts. The AI is flying blind on what it actually fought — it can't notice "I keep losing to fire types" or "my opponent always used the same ability." Worth filling in from `FightEvent` rows while the session is open.

### Matchmaking can produce zero pairs at small population

If `min_population` is e.g. 6 and all creatures happen to be the same tier, the shuffle-and-pair loop works. But if tiers are uneven (5 common, 1 rare), the rare creature never fights. Cross-tier matching as a fallback when a tier has only one creature would keep things moving.

### `fight_log` stores only counts, not the actual events

`Fight.fight_log = {"turns": outcome.turns, "events": len(outcome.events)}` throws away the event detail that `FightEvent` rows already store. Either drop `fight_log` entirely and query events when needed, or store something genuinely useful (final HP, abilities triggered, KO turn).

### Frontend routes exist but may not all be wired

There are routes for `/analytics`, `/lineage`, `/replay`, and `/debug`. Worth auditing which are fully functional versus scaffolded placeholders before adding more features.

---

## Architectural Questions

**Commentary cadence**: Commentary currently triggers every `commentary_interval` total fights, checked at tick end. This means commentary fires on a global count, not per-creature narrative arc. A creature that just evolved or triggered a rival is a richer commentary moment than "fight #50 happened."

**Audio delivery**: TTS files are served as static files from `/audio`. If the simulation runs for days, audio files accumulate without a cleanup policy. Worth deciding early whether to evict old files or store only the most recent N.

**SQLite ceiling**: SQLite is fine for development and single-machine deployment. If this ever needs to be shared across workers (e.g., multiple uvicorn processes), it'll hit write-lock contention. Not urgent, but worth flagging before scaling.

**Rival spawn rate**: The rival check fires on every fight resolution once `wins >= rival_dominance_threshold`. A dominant creature could trigger multiple rival spawns in quick succession if the threshold is low. Consider a cooldown — one rival spawned per creature per N ticks.

---

## What Makes This Interesting

The core loop — generate, fight, evolve, rival — is self-sustaining. The system produces its own narrative without human input: a legendary fire berserker goes on a 7-fight streak, spawns a rival, the rival defeats it, the community had bet on the wrong side. That's a compelling spectator experience. The challenge is making the individual moments feel distinct enough that viewers don't tune out after a few cycles.

The behavior tree + personality weights approach is the right call over pure stat comparison. A creature with high cunning that keeps fleeing and counter-attacking *feels* different from a berserker that rages through every fight, even if their win rates end up similar.

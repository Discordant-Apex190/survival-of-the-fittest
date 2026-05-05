"""Tests for Graph 4 (commentary_graph) — node-level and integration."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from backend.db.models import Commentary
from backend.db.session import engine, init_db
from backend.graphs.commentary import CommentaryResult, run_commentary_graph

# Ensure test DB tables exist (shared isolated DB from conftest)
init_db()
from backend.graphs.nodes.gemini import MockGeminiProvider
from backend.graphs.nodes.validators import (
    node_retry_commentary_patch,
    node_validate_commentary,
    route_after_commentary_validate,
    validate_commentary_payload,
)

PROVIDER = MockGeminiProvider()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "top_creatures": [
            {"id": "c1", "name": "Blaze Titan Surge", "wins": 10, "element": "fire"},
            {"id": "c2", "name": "Frost Sentinel Mark", "wins": 7, "element": "ice"},
        ],
        "creature_names": ["Blaze Titan Surge", "Frost Sentinel Mark"],
        "element_counts": {"fire": 4, "ice": 3, "nature": 2, "void": 1, "electric": 2},
        "total_fights": 20,
        "trigger_event": "periodic",
    }
    base.update(overrides)
    return base


_UNSET = object()


def _make_state(
    trigger_event: str = "periodic",
    commentary_lines: object = _UNSET,
    validation_errors: list[str] | None = None,
    commentary_retry_count: int = 0,
    **overrides: Any,
) -> dict[str, Any]:
    if commentary_lines is _UNSET:
        commentary_lines = ["The arena churns. Blood and glory. Nothing more."]
    base: dict[str, Any] = {
        "seed_params": {},
        "dominant_creature": None,
        "parent_creature": None,
        "fight_history": [],
        "concept": None,
        "stats": None,
        "abilities": None,
        "taunts": None,
        "visual_descriptor": None,
        "evolution_decision": None,
        "evolution_analysis": None,
        "evolution_new_ability": None,
        "evolution_updated_lore": None,
        "counter_design": None,
        "trigger_event": trigger_event,
        "simulation_snapshot": _make_snapshot(trigger_event=trigger_event),
        "narrative_threads": ["A thread here."],
        "commentary_lines": commentary_lines,
        "commentary_retry_count": commentary_retry_count,
        "validation_errors": validation_errors or [],
        "retry_count": 0,
        "creature_id": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# MockGeminiProvider — gather_context
# ---------------------------------------------------------------------------


class TestGatherContext:
    def test_returns_required_keys(self):
        snapshot = _make_snapshot()
        result = PROVIDER.gather_context("periodic", snapshot)
        for key in [
            "trigger_event", "top_creatures", "recent_fights", "element_counts", "total_fights"
        ]:
            assert key in result

    def test_preserves_top_creatures(self):
        snapshot = _make_snapshot()
        result = PROVIDER.gather_context("extinction", snapshot)
        assert result["top_creatures"] == snapshot["top_creatures"]
        assert result["trigger_event"] == "extinction"

    def test_empty_snapshot_returns_defaults(self):
        result = PROVIDER.gather_context("periodic", {})
        assert result["top_creatures"] == []
        assert result["element_counts"] == {}


# ---------------------------------------------------------------------------
# MockGeminiProvider — identify_narrative_threads
# ---------------------------------------------------------------------------


class TestIdentifyNarrativeThreads:
    def test_extinction_trigger_gives_bloodline_thread(self):
        context = _make_snapshot(trigger_event="extinction")
        threads = PROVIDER.identify_narrative_threads(context)
        assert any("bloodline" in t.lower() or "ends" in t.lower() for t in threads)

    def test_rival_trigger_gives_rival_thread(self):
        context = _make_snapshot(trigger_event="rival_spawned")
        threads = PROVIDER.identify_narrative_threads(context)
        assert any("rival" in t.lower() for t in threads)

    def test_periodic_trigger_gives_arena_thread(self):
        context = _make_snapshot(trigger_event="periodic")
        threads = PROVIDER.identify_narrative_threads(context)
        assert len(threads) >= 1

    def test_top_creature_referenced_in_thread(self):
        context = _make_snapshot(trigger_event="periodic")
        threads = PROVIDER.identify_narrative_threads(context)
        all_text = " ".join(threads)
        assert "Blaze Titan Surge" in all_text

    def test_returns_list(self):
        context = _make_snapshot()
        threads = PROVIDER.identify_narrative_threads(context)
        assert isinstance(threads, list)
        assert all(isinstance(t, str) for t in threads)


# ---------------------------------------------------------------------------
# MockGeminiProvider — generate_commentary
# ---------------------------------------------------------------------------


class TestGenerateCommentary:
    def test_returns_list_of_strings(self):
        threads = ["The arena churns. Blood and glory."]
        snapshot = _make_snapshot()
        lines = PROVIDER.generate_commentary("periodic", threads, snapshot)
        assert isinstance(lines, list)
        assert all(isinstance(line, str) for line in lines)

    def test_returns_at_least_one_line(self):
        lines = PROVIDER.generate_commentary("periodic", ["A thread."], _make_snapshot())
        assert len(lines) >= 1

    def test_deterministic_with_same_inputs(self):
        threads = ["The arena churns."]
        r1 = PROVIDER.generate_commentary("periodic", threads, {})
        r2 = PROVIDER.generate_commentary("periodic", threads, {})
        assert r1 == r2

    def test_empty_threads_returns_fallback(self):
        lines = PROVIDER.generate_commentary("periodic", [], {})
        assert len(lines) >= 1


# ---------------------------------------------------------------------------
# node_validate_commentary
# ---------------------------------------------------------------------------


class TestNodeValidateCommentary:
    def test_valid_lines_no_errors(self):
        state = _make_state()
        result = node_validate_commentary(state)
        assert result["validation_errors"] == []

    def test_none_lines_errors(self):
        state = _make_state(commentary_lines=None)
        result = node_validate_commentary(state)
        assert result["validation_errors"]

    def test_empty_lines_errors(self):
        state = _make_state(commentary_lines=[])
        result = node_validate_commentary(state)
        assert result["validation_errors"]

    def test_too_short_line_errors(self):
        state = _make_state(commentary_lines=["Hi"])
        result = node_validate_commentary(state)
        assert any("short" in e for e in result["validation_errors"])

    def test_too_many_lines_errors(self):
        state = _make_state(
            commentary_lines=[
                "Line one here.",
                "Line two here.",
                "Line three here.",
                "Line four here.",
            ]
        )
        result = node_validate_commentary(state)
        assert any("max" in e for e in result["validation_errors"])


# ---------------------------------------------------------------------------
# validate_commentary_payload
# ---------------------------------------------------------------------------


class TestValidateCommentaryPayload:
    def test_valid_payload_no_errors(self):
        errors = validate_commentary_payload(
            commentary_lines=["The strong survive. The weak become legend."],
            simulation_snapshot=_make_snapshot(),
        )
        assert errors == []

    def test_exceeds_max_lines(self):
        errors = validate_commentary_payload(
            commentary_lines=["Line one.", "Line two.", "Line three.", "Line four."],
            simulation_snapshot={},
        )
        assert any("max" in e for e in errors)

    def test_line_too_short(self):
        errors = validate_commentary_payload(
            commentary_lines=["Short"],
            simulation_snapshot={},
        )
        assert errors


# ---------------------------------------------------------------------------
# node_retry_commentary_patch
# ---------------------------------------------------------------------------


class TestNodeRetryCommentaryPatch:
    def test_increments_retry_count(self):
        state = _make_state(commentary_retry_count=0)
        result = node_retry_commentary_patch(state)
        assert result["commentary_retry_count"] == 1

    def test_clears_commentary_lines(self):
        state = _make_state()
        result = node_retry_commentary_patch(state)
        assert result["commentary_lines"] is None

    def test_clears_validation_errors(self):
        state = _make_state(validation_errors=["some error"])
        result = node_retry_commentary_patch(state)
        assert result["validation_errors"] == []


# ---------------------------------------------------------------------------
# route_after_commentary_validate
# ---------------------------------------------------------------------------


class TestRouteAfterCommentaryValidate:
    def test_routes_to_write_when_valid(self):
        route = route_after_commentary_validate(max_retries=2)
        state = _make_state(validation_errors=[])
        assert route(state) == "write_commentary"

    def test_routes_to_retry_when_errors_and_under_limit(self):
        route = route_after_commentary_validate(max_retries=2)
        state = _make_state(validation_errors=["bad"], commentary_retry_count=0)
        assert route(state) == "retry_commentary"

    def test_routes_to_failed_at_max_retries(self):
        route = route_after_commentary_validate(max_retries=2)
        state = _make_state(validation_errors=["bad"], commentary_retry_count=2)
        assert route(state) == "failed"


# ---------------------------------------------------------------------------
# run_commentary_graph — integration
# ---------------------------------------------------------------------------


class TestRunCommentaryGraph:
    def test_produces_commentary_result(self):
        snapshot = _make_snapshot()
        with Session(engine) as session:
            result = run_commentary_graph(
                session,
                trigger_event="periodic",
                simulation_snapshot=snapshot,
                provider=PROVIDER,
            )
        assert isinstance(result, CommentaryResult)
        assert result.trigger == "periodic"
        assert len(result.lines) >= 1
        assert result.retry_count == 0

    def test_commentary_persisted_in_db(self):
        snapshot = _make_snapshot(trigger_event="evolution")
        with Session(engine) as session:
            run_commentary_graph(
                session,
                trigger_event="evolution",
                simulation_snapshot=snapshot,
                provider=PROVIDER,
            )
            rows = session.exec(
                select(Commentary).where(Commentary.trigger == "evolution")
            ).all()
        assert len(rows) >= 1
        assert rows[0].text

    def test_extinction_trigger_produces_appropriate_commentary(self):
        snapshot = _make_snapshot(trigger_event="extinction")
        with Session(engine) as session:
            result = run_commentary_graph(
                session,
                trigger_event="extinction",
                simulation_snapshot=snapshot,
                provider=PROVIDER,
            )
        assert len(result.lines) >= 1
        assert result.trigger == "extinction"

    def test_rival_spawned_trigger(self):
        snapshot = _make_snapshot(trigger_event="rival_spawned")
        with Session(engine) as session:
            result = run_commentary_graph(
                session,
                trigger_event="rival_spawned",
                simulation_snapshot=snapshot,
                provider=PROVIDER,
            )
        assert result.trigger == "rival_spawned"
        assert len(result.lines) >= 1

    def test_all_triggers_complete_without_error(self):
        from backend.graphs.commentary import TRIGGER_PRIORITY

        snapshot = _make_snapshot()
        for trigger in TRIGGER_PRIORITY:
            snapshot["trigger_event"] = trigger
            with Session(engine) as session:
                result = run_commentary_graph(
                    session,
                    trigger_event=trigger,
                    simulation_snapshot=snapshot,
                    provider=PROVIDER,
                )
            assert len(result.lines) >= 1, f"No lines for trigger: {trigger}"


# ---------------------------------------------------------------------------
# WebSocket manager
# ---------------------------------------------------------------------------


class TestConnectionManager:
    def test_initial_connection_count_is_zero(self):
        from backend.ws.manager import ConnectionManager

        mgr = ConnectionManager()
        assert mgr.connection_count == 0

    def test_broadcast_sync_with_no_connections_does_not_raise(self):
        from backend.ws.manager import ConnectionManager

        mgr = ConnectionManager()
        mgr.broadcast_sync({"type": "test", "data": "hello"})


# ---------------------------------------------------------------------------
# GET /ws — WebSocket connection test
# ---------------------------------------------------------------------------


class TestWebSocketEndpoint:
    def test_websocket_connects_and_receives_pong(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_text("ping")
            data = ws.receive_text()
            assert "pong" in data

    def test_websocket_connection_count_increases(self, client):
        from backend.ws.manager import manager as app_manager

        initial = app_manager.connection_count
        with client.websocket_connect("/ws"):
            assert app_manager.connection_count == initial + 1
        assert app_manager.connection_count == initial

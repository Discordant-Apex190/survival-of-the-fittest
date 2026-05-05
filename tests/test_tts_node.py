from __future__ import annotations

from pathlib import Path

from backend.graphs.nodes.tts import _audio_path, node_queue_tts


def test_node_queue_tts_skips_in_test_env() -> None:
    """node_queue_tts must be a no-op in test environment (no API key, APP_ENV=test)."""
    state = {
        "creature_id": "test-creature-id",
        "taunts": {"intro": ["Hello, I am a test creature!"]},
    }
    result = node_queue_tts(state)
    assert result == {}


def test_node_queue_tts_skips_without_creature_id() -> None:
    state: dict = {"creature_id": None, "taunts": {"intro": ["Hello!"]}}
    result = node_queue_tts(state)
    assert result == {}


def test_node_queue_tts_skips_empty_state() -> None:
    result = node_queue_tts({})
    assert result == {}


def test_audio_path_constructs_correctly(tmp_path: Path) -> None:
    path = _audio_path("creature123", "taunt456", tmp_path)
    assert path == tmp_path / "creatures" / "creature123" / "taunt456.mp3"


def test_audio_path_creates_parent_directory(tmp_path: Path) -> None:
    path = _audio_path("creature123", "taunt456", tmp_path)
    assert path.parent.exists()


def test_audio_path_different_creatures_isolated(tmp_path: Path) -> None:
    path_a = _audio_path("creature-a", "t1", tmp_path)
    path_b = _audio_path("creature-b", "t1", tmp_path)
    assert path_a.parent != path_b.parent

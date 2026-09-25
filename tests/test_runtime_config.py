import copy

import pytest

from src.runtime.audio_out import RecordingSink
from src.runtime.config import (
    REPO_ROOT,
    build_audio_stage,
    detector_weights_path,
    load_runtime_config,
)
from src.runtime.tts import NullTTS, build_tts


def test_shipped_runtime_config_loads():
    cfg = load_runtime_config()
    assert cfg["audio"]["tts"]["backend"] in ("piper", "none")


def test_detector_weights_come_from_config():
    cfg = load_runtime_config()
    p = detector_weights_path(cfg)
    assert p.is_absolute()
    assert p == REPO_ROOT / cfg["detector"]["weights"]
    assert p.is_file(), f"configured weights {p} missing -- commit them to models/"
    other = {"detector": {"weights": "models/v5.pt"}}
    assert detector_weights_path(other) == REPO_ROOT / "models" / "v5.pt"


def test_missing_section_fails_loudly(tmp_path):
    bad = tmp_path / "runtime.yaml"
    bad.write_text("schema_version: 1\naudio: {}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="detector"):
        load_runtime_config(bad)


def test_missing_voice_model_degrades_to_null_tts(tmp_path):
    backend, warn = build_tts({"backend": "piper", "voice_model": "nope/missing.onnx"}, tmp_path)
    assert isinstance(backend, NullTTS)
    assert warn and "falling back" in warn


def test_unknown_tts_backend_is_a_config_error(tmp_path):
    with pytest.raises(ValueError):
        build_tts({"backend": "espeak"}, tmp_path)


def test_audio_disabled_builds_no_worker():
    cfg = copy.deepcopy(load_runtime_config())
    cfg["audio"]["enabled"] = False
    stage = build_audio_stage(cfg)
    assert stage.worker is None


def test_stage_with_injected_sink_and_no_voice(tmp_path):
    pytest.importorskip("numpy")
    cfg = copy.deepcopy(load_runtime_config())
    cfg["audio"]["tts"]["voice_model"] = "does/not/exist.onnx"
    stage = build_audio_stage(cfg, repo_root=tmp_path, sink=RecordingSink())
    assert stage.tts_backend == "none"
    assert stage.warnings
    # every earcon the announcer can request must exist in config
    from src.runtime.announcer import EARCON_STEP, EARCON_WAKE

    assert {"advisory", "caution", "warning", EARCON_STEP, EARCON_WAKE} <= set(stage.worker.earcons)

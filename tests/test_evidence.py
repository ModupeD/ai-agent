import json

import numpy as np
import pytest
import soundfile as sf

from patient_probe.artifacts import CallArtifacts, audit, campaign_lock
from patient_probe.config import TEST_NUMBER, Settings
from patient_probe.evaluation import Review, validate_evidence


def test_campaign_prevents_switching_caller_and_concurrent_runs(tmp_path):
    with campaign_lock(tmp_path, "+12125550123"):
        with pytest.raises(ValueError, match="Another campaign"):
            with campaign_lock(tmp_path, "+12125550123"):
                pass
    with pytest.raises(ValueError, match="different caller"):
        with campaign_lock(tmp_path, "+12125550124"):
            pass
    with campaign_lock(tmp_path, "+12125550123"):
        assert json.loads((tmp_path / "campaign.json").read_text())["destination"] == TEST_NUMBER


def test_audit_requires_actual_recording_both_sides_and_full_calls(tmp_path):
    for index in range(10):
        call = CallArtifacts(tmp_path, {"id": str(index)}, "+12125550123")
        for _ in range(3):
            call.turn("patient", "May I confirm the appointment details?")
            call.turn("clinic", "Yes, let me check that.")
        call.save(
            status="complete",
            connected_seconds=65,
            audio={"active_seconds": {"patient": 8, "clinic": 10}},
        )
        # Short synthetic tones only in temp tests, never submission evidence.
        sf.write(
            call.path / "recording.ogg",
            np.zeros((61 * 8000, 2)),
            8000,
            format="OGG",
            subtype="VORBIS",
        )
    assert audit(tmp_path)["mechanically_ready"]
    (call.path / "recording.ogg").unlink()
    result = audit(tmp_path)
    assert not result["mechanically_ready"]
    assert result["passing_calls"] == 9


def test_audit_rejects_failed_silent_or_single_turn_capture(tmp_path):
    call = CallArtifacts(tmp_path, {"id": "pilot"}, "+12125550123")
    call.turn("patient", "Hello")
    call.save(status="failed", connected_seconds=5)
    sf.write(call.path / "recording.ogg", np.zeros((8000, 2)), 8000, format="OGG", subtype="VORBIS")
    result = audit(tmp_path)
    assert not result["mechanically_ready"]
    problems = result["calls"][0]["problems"]
    assert "call status: failed" in problems
    assert "fewer than 3 clinic turns" in problems
    assert "missing or nearly silent clinic audio" in problems


def review_with_quote(turn_id, quote):
    return Review.model_validate(
        {
            "summary": "An observed contradiction",
            "goal_status": "blocked",
            "simulator_issues": [],
            "findings": [
                {
                    "title": "Conflicting time",
                    "severity": "medium",
                    "explanation": "Conflicting times",
                    "expected": "Clarify the time",
                    "evidence": [{"turn_id": turn_id, "quote": quote}],
                }
            ],
        }
    )


def test_analysis_rejects_invented_quotes_and_blame_without_clinic_evidence():
    turns = [
        {"id": 1, "speaker": "clinic", "text": "We close at five."},
        {"id": 2, "speaker": "patient", "text": "You said six?"},
    ]
    validate_evidence(review_with_quote(1, "close at five"), turns)
    for turn_id, quote in [(1, "close at six"), (99, "We close at five."), (2, "six?")]:
        with pytest.raises(ValueError):
            validate_evidence(review_with_quote(turn_id, quote), turns)


@pytest.fixture
def configured_env(monkeypatch):
    monkeypatch.setattr("patient_probe.config.load_dotenv", lambda: None)
    for name, value in {
        "LIVEKIT_URL": "wss://test.livekit.cloud",
        "LIVEKIT_API_KEY": "test",
        "LIVEKIT_API_SECRET": "test",
        "SIP_OUTBOUND_TRUNK_ID": "ST_test",
        "CALLER_NUMBER": "+12125550123",
    }.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("caller", [TEST_NUMBER, "8054398008", "+1", ""])
def test_invalid_caller_configuration_is_rejected(configured_env, monkeypatch, caller):
    monkeypatch.setenv("CALLER_NUMBER", caller)
    with pytest.raises(ValueError):
        Settings.load()


def test_speech_to_speech_configuration_is_rejected(configured_env, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "openai/realtime")
    with pytest.raises(ValueError, match="separate STT"):
        Settings.load()

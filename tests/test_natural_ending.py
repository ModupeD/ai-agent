import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from livekit.agents import Agent, ModelSettings, ToolError, llm

from patient_probe import caller
from patient_probe.config import Settings
from patient_probe.scenarios import SCENARIOS


def patient_with_session():
    patient = caller.Patient(
        SCENARIOS[0],
        Settings("wss://example.livekit.cloud", "key", "secret", "ST_1", "+12125550123"),
        asyncio.Event(),
    )
    session = SimpleNamespace(say=Mock())
    patient._activity = SimpleNamespace(session=session)
    return patient, session


@pytest.mark.parametrize("outcome", ["resolved", "blocked"])
async def test_end_waits_for_spoken_recap_and_clinic_reply_before_hangup(monkeypatch, outcome):
    monkeypatch.setattr(caller, "AUDIO_DRAIN_SECONDS", 0)
    patient, session = patient_with_session()
    release_audio = asyncio.Event()
    session.say.return_value = SimpleNamespace(
        wait_for_playout=release_audio.wait,
        interrupted=False,
    )
    context = SimpleNamespace(wait_for_playout=AsyncMock())
    ending = asyncio.create_task(
        patient.finish_call(context, outcome, "I understand the next step.")
    )
    await asyncio.sleep(0)
    assert patient.closing and not patient.done.is_set()
    assert not patient.farewell_played
    release_audio.set()
    assert await ending is None  # no generated follow-up after goodbye
    assert patient.farewell_played and not patient.done.is_set()
    assert session.say.call_args.args[0] == (
        "I understand the next step. Thank you for your help. Goodbye."
    )
    assert session.say.call_args.kwargs["allow_interruptions"] is False
    listening = asyncio.create_task(patient.wait_for_clinic_reply())
    await asyncio.sleep(0)
    assert not patient.done.is_set()
    # This notification is invoked by the call loop after saving the clinic transcript.
    patient.note_clinic_turn()
    await listening
    assert patient.finish_completed and patient.done.is_set()
    # Duplicate tools cannot speak another goodbye.
    await patient.finish_call(context, outcome, "I understand the next step.")
    session.say.assert_called_once()


async def test_silent_clinic_gets_a_grace_period_without_inventing_its_farewell(monkeypatch):
    monkeypatch.setattr(caller, "AUDIO_DRAIN_SECONDS", 0)
    monkeypatch.setattr(caller, "CLOSING_REPLY_TIMEOUT_SECONDS", 0.01)
    patient, session = patient_with_session()
    session.say.return_value = SimpleNamespace(wait_for_playout=AsyncMock(), interrupted=False)
    await patient.finish_call(
        SimpleNamespace(wait_for_playout=AsyncMock()),
        "blocked",
        "I'll contact support before booking.",
    )
    await patient.wait_for_clinic_reply()
    assert patient.finish_completed
    assert not patient.clinic_reply_recorded.is_set()


async def test_clinic_speech_is_not_cut_off_at_the_quiet_grace_deadline(monkeypatch):
    monkeypatch.setattr(caller, "AUDIO_DRAIN_SECONDS", 0)
    monkeypatch.setattr(caller, "CLOSING_REPLY_TIMEOUT_SECONDS", 0.001)
    patient, session = patient_with_session()
    patient.farewell_played = True
    patient.note_clinic_state("speaking")
    listening = asyncio.create_task(patient.wait_for_clinic_reply())
    await asyncio.sleep(0.01)
    assert not listening.done() and not patient.done.is_set()
    patient.note_clinic_state("listening")
    patient.note_clinic_turn()
    await listening
    assert patient.finish_completed


async def test_interrupted_goodbye_never_claims_a_complete_ending():
    patient, session = patient_with_session()
    session.say.return_value = SimpleNamespace(wait_for_playout=AsyncMock(), interrupted=True)
    with pytest.raises(RuntimeError, match="interrupted"):
        await patient.finish_call(
            SimpleNamespace(wait_for_playout=AsyncMock()),
            "resolved",
            "The office confirmed my appointment.",
        )
    assert not patient.farewell_played and not patient.finish_completed
    assert not patient.done.is_set()


async def test_recap_must_be_a_short_statement():
    patient, session = patient_with_session()
    with pytest.raises(ToolError):
        await patient.finish_call(
            SimpleNamespace(wait_for_playout=AsyncMock()), "blocked", "Where is your office?"
        )
    session.say.assert_not_called()
    assert not patient.closing


async def test_deadline_forces_finish_tool_and_closing_suppresses_extra_questions(monkeypatch):
    patient, session = patient_with_session()
    choices = []

    async def fake_llm(agent, chat_ctx, tools, model_settings):
        choices.append(model_settings.tool_choice)
        yield "mock tool response"

    monkeypatch.setattr(Agent.default, "llm_node", fake_llm)
    patient.wrap_up_requested = True
    result = [part async for part in patient.llm_node(llm.ChatContext(), [], ModelSettings())]
    assert result == ["mock tool response"]
    assert choices == [{"type": "function", "function": {"name": "finish_call"}}]
    patient.closing = True
    result = [part async for part in patient.llm_node(llm.ChatContext(), [], ModelSettings())]
    assert result == [] and len(choices) == 1


async def test_turn_commit_before_listening_state_does_not_stall_closing(monkeypatch):
    monkeypatch.setattr(caller, "AUDIO_DRAIN_SECONDS", 0)
    patient, session = patient_with_session()
    patient.farewell_played = True
    patient.note_clinic_state("speaking")
    patient.note_clinic_turn()
    listening = asyncio.create_task(patient.wait_for_clinic_reply())
    await asyncio.sleep(0.01)
    assert not listening.done()
    patient.note_clinic_state("listening")
    await asyncio.wait_for(listening, timeout=0.1)
    assert patient.finish_completed

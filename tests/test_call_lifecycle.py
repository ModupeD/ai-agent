import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from livekit.agents import Agent, inference, llm
from livekit.agents.llm.chat_context import AgentHandoff
from livekit.agents.metrics.usage import AgentSessionUsage
from livekit.agents.utils import http_context

from patient_probe import caller
from patient_probe.config import TEST_NUMBER, Settings
from patient_probe.scenarios import SCENARIOS


@pytest.fixture
def harness(monkeypatch, tmp_path):
    settings = Settings(
        "wss://example.livekit.cloud", "key", "secret", "ST_1", "+12125550123", artifacts=tmp_path
    )
    service = SimpleNamespace(
        outcome="blocked",
        speech_interrupted=False,
        sip=SimpleNamespace(
            list_sip_outbound_trunk=AsyncMock(
                return_value=SimpleNamespace(
                    items=[SimpleNamespace(sip_trunk_id="ST_1", numbers=[settings.caller_number])]
                )
            ),
            create_sip_participant=AsyncMock(),
        ),
        room=SimpleNamespace(
            create_room=AsyncMock(), delete_room=AsyncMock(), remove_participant=AsyncMock()
        ),
        aclose=AsyncMock(),
    )
    session = Mock()
    session.history.to_dict.return_value = {"items": []}
    callbacks = {}
    session.on.side_effect = lambda name, fn: callbacks.update({name: fn})
    session.aclose = AsyncMock()

    async def start(**kwargs):
        agent = kwargs["agent"]
        agent._activity = SimpleNamespace(session=session)
        session.patient = agent
        # Probe the real SDK HTTP context, without making a network request.
        session.provider_http = http_context.http_session()
        assert not session.provider_http.closed
        callbacks["conversation_item_added"](
            SimpleNamespace(item=AgentHandoff(new_agent_id="patient"))
        )
        # Simulate a realistic callback stream without contacting any service.
        callbacks["agent_state_changed"](
            SimpleNamespace(type="agent_state_changed", new_state="speaking")
        )
        callbacks["session_usage_updated"](SimpleNamespace(usage=AgentSessionUsage(model_usage=[])))
        for role, content in [
            ("user", "Hello, how can I help?"),
            ("assistant", "I'd like to schedule a checkup."),
        ]:
            callbacks["conversation_item_added"](
                SimpleNamespace(
                    item=llm.ChatMessage(
                        role=role, content=[content], metrics={"llm_node_ttft": 0.2}
                    )
                )
            )

        async def answered(*args, **kw):
            async def played():
                callbacks["conversation_item_added"](
                    SimpleNamespace(
                        item=llm.ChatMessage(
                            role="assistant", content=[session.say.call_args.args[0]]
                        )
                    )
                )

                async def clinic_farewell():
                    await asyncio.sleep(0)
                    callbacks["user_state_changed"](
                        SimpleNamespace(type="user_state_changed", new_state="listening")
                    )
                    callbacks["conversation_item_added"](
                        SimpleNamespace(
                            item=llm.ChatMessage(role="user", content=["You're welcome. Goodbye."])
                        )
                    )

                asyncio.create_task(clinic_farewell())

            session.say = Mock(
                return_value=SimpleNamespace(
                    wait_for_playout=played,
                    interrupted=service.speech_interrupted,
                )
            )
            await agent.finish_call(
                SimpleNamespace(wait_for_playout=AsyncMock()),
                service.outcome,
                "I'll contact support to create my record.",
            )

        if service.sip.create_sip_participant.side_effect is None:
            service.sip.create_sip_participant.side_effect = answered

    session.start = AsyncMock(side_effect=start)
    room = SimpleNamespace(connect=AsyncMock(), disconnect=AsyncMock())
    recorder = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(
            return_value={"errors": [], "captured_seconds": {"patient": 10, "clinic": 10}}
        ),
    )
    monkeypatch.setattr(caller.api, "LiveKitAPI", Mock(return_value=service))
    monkeypatch.setattr(caller.rtc, "Room", Mock(return_value=room))
    monkeypatch.setattr(caller, "StereoRecorder", Mock(return_value=recorder))
    monkeypatch.setattr(caller, "AgentSession", Mock(return_value=session))
    monkeypatch.setattr(caller.silero.VAD, "load", Mock(return_value=object()))
    for name in ("STT", "LLM", "TTS"):
        monkeypatch.setattr(caller.inference, name, Mock(return_value=object()))
    monkeypatch.setattr(caller, "GREETING_WAIT_SECONDS", 0.001)
    monkeypatch.setattr(caller, "AUDIO_DRAIN_SECONDS", 0)
    monkeypatch.setattr(caller, "CLINIC_QUIET_SECONDS", 0)
    return settings, service, session, recorder


async def test_fixed_destination_explicit_caller_and_complete_evidence(harness):
    settings, service, session, recorder = harness
    result = await caller.run_call(settings, SCENARIOS[0])
    request = service.sip.create_sip_participant.call_args.args[0]
    assert request.sip_call_to == TEST_NUMBER
    assert request.sip_number == settings.caller_number
    assert request.max_call_duration.seconds == settings.max_call_seconds + 60
    service.room.delete_room.assert_awaited_once()
    recorder.close.assert_awaited_once()
    transcript = json.loads(next(settings.artifacts.glob("*/transcript.json")).read_text())
    assert [turn["speaker"] for turn in transcript] == ["clinic", "patient", "patient", "clinic"]
    assert transcript[-2]["text"].endswith("Goodbye.")
    assert transcript[-1]["text"] == "You're welcome. Goodbye."
    assert result["outcome"] == "blocked"
    assert result["farewell_played"] and result["ending_complete"]
    assert result["clinic_reply_captured"]
    assert result["status"] == "complete"
    assert session.provider_http.closed
    assert session.start.call_args.kwargs["session_host"] is False
    assert session.start.call_args.kwargs["room_options"].text_output is False
    assert (
        '"item_type": "agent_handoff"'
        in next(settings.artifacts.glob("*/events.jsonl")).read_text()
    )


async def test_sip_failure_cleans_up_and_preserves_diagnostic(harness):
    settings, service, session, recorder = harness
    service.sip.create_sip_participant.side_effect = RuntimeError("SIP 403 forbidden")
    with pytest.raises(RuntimeError, match="403"):
        await caller.run_call(settings, SCENARIOS[0])
    service.room.delete_room.assert_awaited_once()
    session.aclose.assert_awaited_once()
    recorder.close.assert_awaited_once()
    manifest = json.loads(next(settings.artifacts.glob("*/manifest.json")).read_text())
    assert manifest["status"] == "failed"
    assert "403" in next(settings.artifacts.glob("*/events.jsonl")).read_text()


async def test_unapproved_caller_on_trunk_never_dials(harness):
    settings, service, session, recorder = harness
    service.sip.list_sip_outbound_trunk.return_value.items[0].numbers = ["+12125550999"]
    with pytest.raises(ValueError, match="not one of"):
        await caller.run_call(settings, SCENARIOS[0])
    service.sip.create_sip_participant.assert_not_called()
    service.room.create_room.assert_not_called()


def test_pipeline_sdk_and_patient_tool_can_be_constructed_without_job_context():
    # Uses the installed SDK, not a worker-context mock. No network or model requests.
    patient = caller.Patient(
        SCENARIOS[0],
        Settings("wss://example.livekit.cloud", "key", "secret", "ST_1", "+12125550123"),
        asyncio.Event(),
    )
    assert isinstance(patient, Agent)
    assert "finish_call" in [tool.info.name for tool in patient.tools]
    assert "Current date/time" in patient.instructions


async def test_fatal_pipeline_startup_error_never_dials(harness):
    settings, service, session, recorder = harness
    original = session.start.side_effect

    async def broken_start(**kwargs):
        await original(**kwargs)
        callback = next(args[1] for args, kw in session.on.call_args_list if args[0] == "error")
        callback(SimpleNamespace(error=SimpleNamespace(recoverable=False)))

    session.start.side_effect = broken_start
    with pytest.raises(RuntimeError, match="before dialing"):
        await caller.run_call(settings, SCENARIOS[0])
    service.sip.create_sip_participant.assert_not_called()
    recorder.close.assert_awaited_once()
    service.room.delete_room.assert_awaited_once()
    assert session.provider_http.closed


async def test_installed_speech_plugins_have_http_session_outside_worker():
    # This reproduces the real failure without substituting speech plugins or
    # opening a provider connection. The context is inherited by provider tasks.
    async with http_context.open() as shared:
        stt = inference.STT(model="deepgram/nova-3", api_key="test", api_secret="test")
        tts = inference.TTS(
            model="cartesia/sonic-3", voice="test", api_key="test", api_secret="test"
        )

        async def ensure_sessions():
            assert stt._ensure_session() is shared
            assert tts._ensure_session() is shared

        await asyncio.create_task(ensure_sessions())
        await stt.aclose()
        await tts.aclose()
    assert shared.closed


async def test_deadline_reminder_waits_for_a_clinic_turn_and_respects_call_budget():
    patient = caller.Patient(
        SCENARIOS[0],
        Settings(
            "wss://example.livekit.cloud",
            "key",
            "secret",
            "ST_1",
            "+12125550123",
            max_call_seconds=120,
        ),
        asyncio.Event(),
    )
    message = llm.ChatMessage(role="user", content=["Our support team can create your record."])
    early = llm.ChatContext()
    early.add_message(role=message.role, content=message.text_content)
    await patient.on_user_turn_completed(early, message)
    assert len(early.items) == 1  # no timer before the phone call answers
    patient.connected_at = caller.time.monotonic() - 10
    await patient.on_user_turn_completed(early, message)
    assert len(early.items) == 1
    patient.connected_at = caller.time.monotonic() - 100
    late = llm.ChatContext()
    late.add_message(role=message.role, content=message.text_content)
    await patient.on_user_turn_completed(late, message)
    assert late.items[-1].role == "system"
    assert "using finish_call" in late.items[-1].text_content
    assert "Do not ask another question" in late.items[-1].text_content
    assert patient.wrap_up_requested


async def test_unresolved_wrapup_saves_evidence_but_is_not_a_completed_task(harness):
    settings, service, session, recorder = harness
    service.outcome = "unresolved"
    result = await caller.run_call(settings, SCENARIOS[0])
    assert result["status"] == "incomplete"
    assert result["end_reason"] == "unresolved_wrapup"
    assert result["farewell_played"] and result["ending_complete"]
    assert result["clinic_reply_captured"]
    recorder.close.assert_awaited_once()
    assert next(settings.artifacts.glob("*/transcript.txt")).exists()


async def test_early_peer_disconnect_is_not_mislabeled_as_completed(harness):
    settings, service, session, recorder = harness

    async def peer_left(*args, **kwargs):
        callback = next(args[1] for args, kw in session.on.call_args_list if args[0] == "close")
        callback(SimpleNamespace(reason="client_initiated", error=None))

    service.sip.create_sip_participant.side_effect = peer_left
    result = await caller.run_call(settings, SCENARIOS[0])
    assert result["status"] == "incomplete"
    assert not result["ending_complete"] and not result["farewell_played"]
    recorder.close.assert_awaited_once()


async def test_hard_deadline_cannot_be_reclassified_by_cleanup_disconnect(harness):
    from dataclasses import replace

    settings, service, session, recorder = harness
    # A zero deadline exercises timeout immediately without a paid call or long wait.
    settings = replace(settings, max_call_seconds=0)

    async def room_deleted(*args, **kwargs):
        callback = next(args[1] for args, kw in session.on.call_args_list if args[0] == "close")
        callback(SimpleNamespace(reason="room_deleted", error=None))

    service.room.delete_room.side_effect = room_deleted
    result = await caller.run_call(settings, SCENARIOS[0])
    assert result["status"] == "incomplete"
    assert result["end_reason"] == "max_duration"
    assert result["farewell_played"] and not result["ending_complete"]
    recorder.close.assert_awaited_once()


async def test_interrupted_closing_saves_incomplete_without_repeating_goodbye(harness):
    settings, service, session, recorder = harness
    service.speech_interrupted = True
    result = await caller.run_call(settings, SCENARIOS[0])
    assert result["status"] == "incomplete"
    assert result["end_reason"] == "closing_interrupted"
    assert result["farewell_interrupted"] and not result["ending_complete"]
    session.say.assert_called_once()
    recorder.close.assert_awaited_once()

"""A local AgentSession connects directly to a LiveKit room; no worker deployment."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import asdict, replace
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from google.protobuf.duration_pb2 import Duration
from livekit import api, rtc
from livekit.agents import (
    Agent,
    AgentSession,
    ModelSettings,
    RunContext,
    ToolError,
    function_tool,
    inference,
    llm,
    room_io,
)
from livekit.agents.utils import http_context
from livekit.plugins import silero

from .artifacts import CallArtifacts
from .config import CLINIC_IDENTITY, PATIENT_IDENTITY, TEST_NUMBER, Settings
from .recording import StereoRecorder, room_token
from .scenarios import Scenario, patient_instructions

logger = logging.getLogger(__name__)
GREETING_WAIT_SECONDS = 12.0
CLOSING_REPLY_TIMEOUT_SECONDS = 8.0
AUDIO_DRAIN_SECONDS = 0.4
CLINIC_QUIET_SECONDS = 1.2


async def validate_trunk(client: api.LiveKitAPI, settings: Settings) -> None:
    response = await client.sip.list_sip_outbound_trunk(api.ListSIPOutboundTrunkRequest())
    trunk = next((t for t in response.items if t.sip_trunk_id == settings.trunk_id), None)
    if trunk is None:
        raise ValueError("Configured outbound SIP trunk was not found in this LiveKit project")
    if settings.caller_number not in trunk.numbers:
        raise ValueError("CALLER_NUMBER is not one of the configured outbound trunk numbers")


class Patient(Agent):
    def __init__(self, scenario: Scenario, settings: Settings, done: asyncio.Event):
        now = datetime.now(ZoneInfo("America/New_York")).isoformat()
        super().__init__(
            instructions=patient_instructions(scenario, settings.caller_number)
            + f"\nCurrent date/time in America/New_York: {now}"
        )
        self.done = done
        self.connected_at: float | None = None
        self.max_call_seconds = settings.max_call_seconds
        self.wrap_up_requested = False
        self.closing = False
        self.outcome: str | None = None
        self.recap: str | None = None
        self.farewell_played = False
        self.farewell_interrupted = False
        self.closing_speech_started = False
        self.finish_completed = False
        self.clinic_speaking = False
        self.clinic_activity_at = 0.0
        self.clinic_reply_recorded = asyncio.Event()
        self.clinic_state_changed = asyncio.Event()
        self._ending_lock = asyncio.Lock()

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        if self.closing or self.connected_at is None:
            return
        remaining = self.max_call_seconds - (time.monotonic() - self.connected_at)
        if remaining <= min(35, self.max_call_seconds / 2):
            self.wrap_up_requested = True
            turn_ctx.add_message(
                role="system",
                content="End this call now using finish_call. Supply a brief first-person recap "
                "based only on the conversation. Outcome is resolved if the goal was achieved, "
                "blocked if the office cannot proceed and gave a next step, or unresolved if "
                "the task is still pending. Do not ask another question or invent completion.",
            )

    async def llm_node(self, chat_ctx, tools, model_settings: ModelSettings):
        # Continue accepting clinic audio/transcripts during closing, without
        # generating a new patient question or paying for another LLM request.
        if self.closing:
            return
        if self.wrap_up_requested:
            model_settings = replace(
                model_settings,
                tool_choice={"type": "function", "function": {"name": "finish_call"}},
            )
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            yield chunk

    def note_clinic_state(self, state: str) -> None:
        self.clinic_speaking = state == "speaking"
        self.clinic_activity_at = time.monotonic()
        self.clinic_state_changed.set()

    def note_clinic_turn(self) -> None:
        # Called only after the clinic's actual transcript has been persisted.
        self.clinic_activity_at = time.monotonic()
        self.clinic_state_changed.set()
        if self.farewell_played or self.farewell_interrupted:
            self.clinic_reply_recorded.set()

    async def wait_for_clinic_quiet(self) -> None:
        # A tool can be invoked while the other party is already speaking.
        # Wait for sustained silence, restarting the window if speech resumes.
        await asyncio.sleep(0)
        while True:
            self.clinic_state_changed.clear()
            remaining = CLINIC_QUIET_SECONDS - (time.monotonic() - self.clinic_activity_at)
            if not self.clinic_speaking and remaining <= 0:
                return
            try:
                await asyncio.wait_for(
                    self.clinic_state_changed.wait(),
                    timeout=None if self.clinic_speaking else remaining,
                )
            except asyncio.TimeoutError:
                pass

    @function_tool
    async def finish_call(
        self,
        context: RunContext,
        outcome: Literal["resolved", "blocked", "unresolved"],
        recap: str,
    ) -> None:
        """Finish as soon as the task is resolved or blocked and a next step is clear.

        outcome: resolved = goal achieved; blocked = cannot proceed, next step provided;
            unresolved = time is short but no final result/next step is established.
        recap: A short factual outcome summary for the saved report, under 240 characters.
            This summary is not spoken. Do not invent next steps or a successful booking.
        The tool speaks a short natural thank-you and goodbye. Do not narrate a report,
        repeat the conversation, ask optional questions, or say a separate goodbye first.
        """
        recap = recap.strip()
        if not recap or len(recap) > 240 or "?" in recap:
            raise ToolError("Provide a short factual recap statement without a question.")
        async with self._ending_lock:
            if self.closing:
                return
            await context.wait_for_playout()
            self.closing = True
            self.outcome, self.recap = outcome, recap
            try:
                await self.wait_for_clinic_quiet()
                self.closing_speech_started = True
                handle = self.session.say(
                    "Okay, thanks for your help. Goodbye.",
                    allow_interruptions=True,
                )
                await handle.wait_for_playout()
            except asyncio.CancelledError:
                if self.closing_speech_started:
                    # Do not replay a partially spoken goodbye. Keep listening
                    # and preserve the attempt as incomplete for review.
                    self.farewell_interrupted = True
                else:
                    self.closing = False
                    self.outcome, self.recap = None, None
                raise
            if handle.interrupted:
                self.farewell_interrupted = True
                return
            self.farewell_played = True
        # Returning None suppresses an automatic LLM follow-up. The call loop
        # listens for the clinic's farewell before disconnecting either audio track.

    async def wait_for_clinic_reply(self) -> None:
        try:
            await asyncio.wait_for(
                self.clinic_reply_recorded.wait(),
                timeout=CLOSING_REPLY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            # Never cut off an ongoing reply just because the quiet grace elapsed.
            # The unchanged outer call deadline remains the absolute limit.
            if self.clinic_speaking:
                await self.clinic_reply_recorded.wait()
        while True:
            while self.clinic_speaking:
                self.clinic_state_changed.clear()
                await self.clinic_state_changed.wait()
            await asyncio.sleep(AUDIO_DRAIN_SECONDS)
            if not self.clinic_speaking:
                break
        self.finish_completed = self.farewell_played and not self.farewell_interrupted
        self.done.set()


async def run_call(settings: Settings, scenario: Scenario) -> dict:
    # The CLI does not run inside a worker; bind the HTTP session before creating
    # provider tasks, and keep it alive until pipeline teardown completes.
    async with http_context.open():
        return await _run_call(settings, scenario)


async def _run_call(settings: Settings, scenario: Scenario) -> dict:
    evidence = CallArtifacts(settings.artifacts, scenario.to_dict(), settings.caller_number)
    room_name = "probe-" + evidence.path.name
    evidence.save(
        room=room_name,
        pipeline={
            "stt": settings.stt_model,
            "llm": settings.llm_model,
            "tts": settings.tts_model,
            "voice": settings.tts_voice,
        },
    )
    client = api.LiveKitAPI(settings.url, settings.api_key, settings.api_secret)
    room = rtc.Room()
    recorder = StereoRecorder(settings, room_name, evidence.path, evidence.started)
    done = asyncio.Event()
    session = None
    patient = None
    connected_at = None
    last_activity = time.monotonic()
    close_reason = "unknown"
    failed = False
    room_created = False
    tearing_down = False

    def on_turn(event):
        nonlocal last_activity
        item = event.item
        if not isinstance(item, llm.ChatMessage):
            evidence.event("history_item", item_type=getattr(item, "type", "unknown"))
            return
        if item.role in ("user", "assistant"):
            evidence.turn(
                "clinic" if item.role == "user" else "patient",
                item.text_content,
                getattr(item, "interrupted", False),
            )
            if item.role == "user" and patient is not None:
                patient.note_clinic_turn()
            logger.info("%s: %s", "clinic" if item.role == "user" else "patient", item.text_content)
            if item.role == "assistant" and getattr(item, "metrics", None):
                evidence.event("turn_metrics", data=item.metrics)
            last_activity = time.monotonic()

    def on_close(event):
        nonlocal close_reason, failed
        if patient and patient.farewell_played and not tearing_down and not event.error:
            patient.finish_completed = True
            close_reason = "clinic_hung_up_after_goodbye"
        elif close_reason == "unknown":
            close_reason = str(event.reason)
        if getattr(event, "error", None):
            failed = True
            evidence.event("session_error", error=str(event.error))
        done.set()

    def on_state(event):
        nonlocal last_activity
        if event.new_state == "speaking":
            last_activity = time.monotonic()
        if event.type == "user_state_changed" and patient is not None:
            patient.note_clinic_state(event.new_state)
        evidence.event("state", state_event=event.type, state=event.new_state)

    def on_error(event):
        nonlocal failed, close_reason
        error = event.error
        evidence.event(
            "pipeline_error", data=str(error), recoverable=getattr(error, "recoverable", False)
        )
        if not getattr(error, "recoverable", False):
            failed = True
            close_reason = "pipeline_error"
            done.set()

    async def conversation():
        nonlocal last_activity, close_reason
        # Let the clinic greet first. Only prompt if both sides remain quiet.
        try:
            await asyncio.wait_for(done.wait(), timeout=GREETING_WAIT_SECONDS)
            return
        except asyncio.TimeoutError:
            pass
        if not evidence.turns:
            session.generate_reply(
                instructions="The office is quiet. Briefly say hello and ask "
                "whether someone can help you."
            )
            last_activity = time.monotonic()
        nudges = 0
        while not done.is_set():
            if patient is not None and patient.closing:
                if patient.farewell_played or patient.farewell_interrupted:
                    await patient.wait_for_clinic_reply()
                    return
                try:
                    await asyncio.wait_for(done.wait(), timeout=0.1)
                except asyncio.TimeoutError:
                    pass
                continue
            try:
                await asyncio.wait_for(done.wait(), timeout=2)
            except asyncio.TimeoutError:
                pass
            if time.monotonic() - last_activity > 25 and not done.is_set():
                if nudges >= 2:
                    close_reason = "silence_timeout"
                    return
                session.generate_reply(
                    instructions="There has been a long silence. Briefly ask "
                    "if they are still there, without repeating "
                    "your entire request."
                )
                last_activity = time.monotonic()
                nudges += 1

    try:
        await validate_trunk(client, settings)
        await client.room.create_room(api.CreateRoomRequest(name=room_name, empty_timeout=30))
        room_created = True
        await room.connect(settings.url, room_token(settings, room_name, PATIENT_IDENTITY, True))
        await recorder.start()
        session = AgentSession(
            stt=inference.STT(model=settings.stt_model, language="en"),
            llm=inference.LLM(model=settings.llm_model),
            tts=inference.TTS(model=settings.tts_model, voice=settings.tts_voice),
            vad=silero.VAD.load(),
            turn_handling={
                "turn_detection": "vad",
                "endpointing": {"min_delay": 1.3, "max_delay": 3.0},
                "interruption": {
                    "mode": "vad",
                    "min_duration": 0.8,
                    "min_words": 3,
                    "discard_audio_if_uninterruptible": False,
                },
                "preemptive_generation": {"enabled": False},
            },
        )
        session.on("conversation_item_added", on_turn)
        session.on("close", on_close)
        session.on("agent_state_changed", on_state)
        session.on("user_state_changed", on_state)
        session.on(
            "session_usage_updated",
            lambda event: evidence.event("usage", data=asdict(event.usage)),
        )
        session.on("error", on_error)
        patient = Patient(scenario, settings, done)
        await session.start(
            agent=patient,
            room=room,
            session_host=False,
            room_options=room_io.RoomOptions(
                participant_identity=CLINIC_IDENTITY,
                close_on_disconnect=True,
                text_input=False,
                text_output=False,
            ),
        )
        # Let queued startup events run before spending on a telephone call.
        await asyncio.sleep(0)
        if done.is_set():
            raise RuntimeError("Voice pipeline stopped before dialing; inspect events.jsonl")
        evidence.save(status="dialing")
        # Fixed destination; caller ID explicitly selected even on multi-number trunks.
        await client.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=settings.trunk_id,
                sip_call_to=TEST_NUMBER,
                sip_number=settings.caller_number,
                room_name=room_name,
                participant_identity=CLINIC_IDENTITY,
                participant_name="Assessment test line",
                wait_until_answered=True,
                ringing_timeout=Duration(seconds=45),
                max_call_duration=Duration(seconds=settings.max_call_seconds + 60),
            ),
            timeout=60,
        )
        connected_at = time.monotonic()
        patient.connected_at = connected_at
        last_activity = connected_at
        evidence.event("answered")
        evidence.save(status="connected", answered_offset=evidence.elapsed())
        try:
            await asyncio.wait_for(conversation(), timeout=settings.max_call_seconds)
            if close_reason == "unknown":
                close_reason = (
                    "patient_finished"
                    if patient.finish_completed
                    else (
                        "closing_interrupted"
                        if patient.farewell_interrupted
                        else "remote_disconnect"
                    )
                )
        except asyncio.TimeoutError:
            close_reason = "max_duration"
    except BaseException as exc:
        failed = True
        close_reason = type(exc).__name__
        evidence.event(
            "call_error",
            error=f"{type(exc).__name__}: {exc}",
            sip_status_code=getattr(exc, "sip_status_code", None),
            sip_status=getattr(exc, "sip_status", None),
        )
        raise
    finally:
        tearing_down = True
        ended = time.monotonic()
        evidence.save(
            status="finalizing",
            end_reason=close_reason,
            connected_seconds=round(ended - connected_at, 3) if connected_at else 0,
        )
        # Disconnect the telephone first, even if model teardown fails.
        if room_created:
            try:
                await client.room.delete_room(api.DeleteRoomRequest(room=room_name))
            except Exception as exc:
                failed = True
                evidence.event("hangup_error", error=str(exc))
                with contextlib.suppress(Exception):
                    await client.room.remove_participant(
                        api.RoomParticipantIdentity(room=room_name, identity=CLINIC_IDENTITY)
                    )
        if session is not None:
            try:
                await asyncio.wait_for(session.aclose(), timeout=15)
            except Exception as exc:
                evidence.event("session_cleanup_error", error=str(exc))
            evidence.save_transcript()
            with contextlib.suppress(Exception):
                from .artifacts import write_json

                write_json(evidence.path / "history.json", session.history.to_dict())
        try:
            audio = await recorder.close()
            evidence.save(audio=audio)
            if audio["errors"] or not all(audio["captured_seconds"].values()):
                failed = True
        except Exception as exc:
            failed = True
            evidence.event("recording_error", error=str(exc))
        await room.disconnect()
        await client.aclose()
        ending_complete = bool(patient and patient.finish_completed)
        outcome = patient.outcome if patient else None
        status = (
            "failed"
            if failed
            else (
                "complete"
                if ending_complete and outcome in ("resolved", "blocked")
                else "incomplete"
            )
        )
        if ending_complete and outcome == "unresolved":
            close_reason = "unresolved_wrapup"
        evidence.save(
            status=status,
            end_reason=close_reason,
            outcome=outcome,
            recap=patient.recap if patient else None,
            farewell_played=bool(patient and patient.farewell_played),
            farewell_interrupted=bool(patient and patient.farewell_interrupted),
            ending_complete=ending_complete,
            clinic_reply_captured=bool(patient and patient.clinic_reply_recorded.is_set()),
            connected_seconds=round(ended - connected_at, 3) if connected_at else 0,
            duration_seconds=evidence.elapsed(),
        )
    logger.info("Saved call: %s", evidence.path)
    return evidence.manifest

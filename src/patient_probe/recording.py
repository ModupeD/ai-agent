"""An independent read-only room participant records both actual audio tracks."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

import numpy as np
from livekit import api, rtc

from .config import CLINIC_IDENTITY, PATIENT_IDENTITY, SAMPLE_RATE, Settings

logger = logging.getLogger(__name__)


def room_token(settings: Settings, room: str, identity: str, publish: bool) -> str:
    return (
        api.AccessToken(settings.api_key, settings.api_secret)
        .with_identity(identity)
        .with_grants(
            api.VideoGrants(room_join=True, room=room, can_publish=publish, can_subscribe=True)
        )
        .to_jwt()
    )


class StereoRecorder:
    """Left = patient; right = clinic. Gaps are silence, not concatenated speech.

    Each continuous stream advances by sample count. Arrival time only anchors a
    stream or recovers after a real gap, avoiding cumulative frame-jitter drift.
    """

    def __init__(self, settings: Settings, room_name: str, path: Path, origin: float):
        self.settings, self.room_name, self.path = settings, room_name, path
        self.origin = origin
        self.room = rtc.Room()
        self.tasks: list[asyncio.Task] = []
        self.streams: list[rtc.AudioStream] = []
        self.errors: list[str] = []
        self.capacity = (settings.max_call_seconds + 120) * SAMPLE_RATE
        self.pcm_files = [
            (path / f"audio-{speaker}.pcm").open("wb", buffering=0)
            for speaker in ("patient", "clinic")
        ]
        self.end = 0
        self.frames = [0, 0]
        self.active = [0, 0]
        self.closed = False
        self.room.on("track_subscribed", self._subscribed)

    async def start(self) -> None:
        await self.room.connect(
            self.settings.url, room_token(self.settings, self.room_name, "audio-recorder", False)
        )

    def _subscribed(self, track, publication, participant) -> None:
        if self.closed or track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        channels = {PATIENT_IDENTITY: 0, CLINIC_IDENTITY: 1}
        if participant.identity not in channels:
            return
        stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
        self.streams.append(stream)
        self.tasks.append(
            asyncio.create_task(self._capture(stream, channels[participant.identity]))
        )

    async def _capture(self, stream: rtc.AudioStream, channel: int) -> None:
        cursor = None
        try:
            async for event in stream:
                samples = np.frombuffer(event.frame.data, dtype=np.int16)
                arrival = max(0, int((time.monotonic() - self.origin) * SAMPLE_RATE) - len(samples))
                if cursor is None or arrival - cursor > SAMPLE_RATE // 4:
                    cursor = arrival
                end = min(cursor + len(samples), self.capacity)
                length = max(0, end - cursor)
                if length:
                    # Unbuffered PCM survives a process crash; sparse gaps retain timing.
                    pcm = self.pcm_files[channel]
                    pcm.seek(cursor * 2)
                    pcm.write(samples[:length].astype("<i2", copy=False).tobytes())
                    self.frames[channel] += length
                    if np.sqrt(np.mean(samples[:length].astype(np.float64) ** 2)) > 100:
                        self.active[channel] += length
                    self.end = max(self.end, end)
                cursor = end
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.errors.append(f"channel {channel}: {type(exc).__name__}: {exc}")
            logger.exception("Audio capture failed")

    async def close(self) -> dict:
        self.closed = True
        for stream in self.streams:
            await stream.aclose()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.room.disconnect()
        for pcm in self.pcm_files:
            pcm.close()
        if self.end:
            encoder = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "patient_probe.encode",
                str(self.path.resolve()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(encoder.communicate(), timeout=60)
            except BaseException:
                if encoder.returncode is None:
                    encoder.kill()
                await encoder.wait()
                raise
            if encoder.returncode:
                raise RuntimeError(
                    f"OGG encoder exited {encoder.returncode}; captured PCM preserved. "
                    + stderr.decode(errors="replace")[-1500:]
                )
        return {
            "channels": {"left": "patient", "right": "clinic"},
            "sample_rate": SAMPLE_RATE,
            "duration_seconds": self.end / SAMPLE_RATE,
            "captured_seconds": dict(
                zip(("patient", "clinic"), (n / SAMPLE_RATE for n in self.frames), strict=False)
            ),
            "active_seconds": dict(
                zip(("patient", "clinic"), (n / SAMPLE_RATE for n in self.active), strict=False)
            ),
            "errors": self.errors,
        }

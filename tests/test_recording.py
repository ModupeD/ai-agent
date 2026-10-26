import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
import soundfile as sf

from patient_probe.config import SAMPLE_RATE, Settings
from patient_probe.recording import StereoRecorder


class Frames:
    def __init__(self, samples):
        self.samples = samples

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.samples:
            raise StopAsyncIteration
        return SimpleNamespace(frame=SimpleNamespace(data=self.samples.pop(0).tobytes()))


async def test_real_ogg_encodes_two_actual_captured_tracks_and_preserves_gap(tmp_path):
    settings = Settings("wss://example.livekit.cloud", "key", "secret", "ST_1", "+12125550123")
    recorder = StereoRecorder(settings, "test", tmp_path, time.monotonic() - 0.2)
    # Different tones allow us to detect missing, duplicated or swapped channels.
    t = np.arange(2400) / SAMPLE_RATE
    left = (np.sin(2 * np.pi * 330 * t) * 8000).astype(np.int16)
    right = (np.sin(2 * np.pi * 770 * t) * 8000).astype(np.int16)
    await recorder._capture(Frames([left]), 0)
    await recorder._capture(Frames([right]), 1)
    recorder.room = SimpleNamespace(disconnect=AsyncMock())
    result = await recorder.close()
    audio, rate = sf.read(tmp_path / "recording.ogg")
    assert rate == SAMPLE_RATE
    assert audio.shape[1] == 2
    assert result["active_seconds"]["patient"] == pytest.approx(0.1)
    assert result["active_seconds"]["clinic"] == pytest.approx(0.1)
    assert np.max(np.abs(audio[:1000])) < 0.01  # initial gap remains silence
    peaks = []
    for channel in (0, 1):
        spectrum = np.abs(np.fft.rfft(audio[:, channel]))
        frequencies = np.fft.rfftfreq(len(audio), 1 / rate)
        peaks.append(frequencies[np.argmax(spectrum)])
    assert peaks[0] == pytest.approx(330, abs=10)
    assert peaks[1] == pytest.approx(770, abs=10)


async def test_encoder_handles_190_seconds_and_pads_shorter_channel(tmp_path):
    import asyncio
    import sys

    duration = 190
    chunk = (np.sin(2 * np.pi * 440 * np.arange(4096) / SAMPLE_RATE) * 6000).astype("<i2")
    for speaker, seconds in (("patient", duration), ("clinic", duration - 2)):
        remaining = seconds * SAMPLE_RATE
        with (tmp_path / f"audio-{speaker}.pcm").open("wb") as stream:
            while remaining:
                length = min(remaining, len(chunk))
                stream.write(chunk[:length].tobytes())
                remaining -= length
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "patient_probe.encode",
        str(tmp_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    assert process.returncode == 0, stderr.decode()
    info = sf.info(tmp_path / "recording.ogg")
    assert info.duration == pytest.approx(duration)
    assert info.channels == 2
    end, _ = sf.read(tmp_path / "recording.ogg", start=189 * SAMPLE_RATE)
    assert np.max(np.abs(end[:, 0])) > 0.1
    assert np.max(np.abs(end[:, 1])) < 0.01


async def test_capture_survives_failed_native_encoder(tmp_path, monkeypatch):
    settings = Settings("wss://example.livekit.cloud", "key", "secret", "ST_1", "+12125550123")
    recorder = StereoRecorder(settings, "test", tmp_path, time.monotonic() - 0.05)
    samples = np.full(2400, 7000, dtype=np.int16)
    await recorder._capture(Frames([samples]), 0)
    # Bytes are already persisted, before close or encoding.
    stored = np.fromfile(tmp_path / "audio-patient.pcm", dtype="<i2")
    assert np.array_equal(stored[-len(samples) :], samples)
    recorder.room = SimpleNamespace(disconnect=AsyncMock())
    failed = SimpleNamespace(
        returncode=-10, communicate=AsyncMock(return_value=(b"", b"codec failed"))
    )
    monkeypatch.setattr(
        "patient_probe.recording.asyncio.create_subprocess_exec", AsyncMock(return_value=failed)
    )
    with pytest.raises(RuntimeError, match="PCM preserved"):
        await recorder.close()
    assert np.array_equal(np.fromfile(tmp_path / "audio-patient.pcm", dtype="<i2"), stored)
    assert all(stream.closed for stream in recorder.pcm_files)

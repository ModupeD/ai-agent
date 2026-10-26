"""Encode bounded PCM blocks in a subprocess; preserve capture on codec failure."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import SAMPLE_RATE

BLOCK_FRAMES = 4096


def encode_recording(directory: Path) -> Path:
    paths = [directory / f"audio-{speaker}.pcm" for speaker in ("patient", "clinic")]
    if not all(path.exists() for path in paths):
        raise ValueError("Both captured PCM tracks are required")
    frames = max(path.stat().st_size // 2 for path in paths)
    if not frames:
        raise ValueError("No captured audio to encode")
    temporary = directory / "recording.ogg.tmp"
    output = directory / "recording.ogg"
    with paths[0].open("rb") as left, paths[1].open("rb") as right:
        with sf.SoundFile(
            temporary, mode="w", samplerate=SAMPLE_RATE, channels=2, format="OGG", subtype="VORBIS"
        ) as writer:
            for offset in range(0, frames, BLOCK_FRAMES):
                length = min(BLOCK_FRAMES, frames - offset)
                block = np.zeros((length, 2), dtype=np.int16)
                for channel, source in enumerate((left, right)):
                    samples = np.frombuffer(source.read(length * 2), dtype="<i2")
                    block[: len(samples), channel] = samples
                writer.write(block)
    info = sf.info(temporary)
    if info.frames != frames or info.channels != 2 or info.samplerate != SAMPLE_RATE:
        raise ValueError("Encoded audio does not match the captured tracks")
    temporary.replace(output)
    return output


if __name__ == "__main__":
    encode_recording(Path(sys.argv[1]))

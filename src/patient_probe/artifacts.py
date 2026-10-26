"""Durable per-call evidence, campaign identity, and submission checks."""

from __future__ import annotations

import fcntl
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import TEST_NUMBER


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


@contextmanager
def campaign_lock(root: Path, caller: str):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".campaign.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another campaign is running; calls must be sequential") from exc
        path = root / "campaign.json"
        if path.exists():
            if json.loads(path.read_text())["caller_number"] != caller:
                raise ValueError("This campaign already uses a different caller number")
        else:
            write_json(path, {"caller_number": caller, "destination": TEST_NUMBER})
        yield


def timestamp(seconds: float) -> str:
    minutes, secs = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02}:{secs:02}"


class CallArtifacts:
    def __init__(self, root: Path, scenario: dict, caller: str):
        self.started = time.monotonic()
        self.epoch = time.time()
        date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.path = root / f"{date}-{scenario['id']}"
        self.path.mkdir(parents=True)
        self.turns: list[dict] = []
        self.manifest = {
            "id": self.path.name,
            "scenario": scenario,
            "caller_number": caller,
            "destination": TEST_NUMBER,
            "started_at": self.epoch,
            "status": "starting",
            "recording": "recording.ogg",
            "transcript": "transcript.txt",
            "timestamp_note": "Offsets from capture start; transcript times are turn commits, "
            "not word-aligned speech times. Audio timing uses frame arrival.",
        }
        self.save()

    def elapsed(self) -> float:
        return round(time.monotonic() - self.started, 3)

    def event(self, kind: str, **data) -> None:
        with (self.path / "events.jsonl").open("a") as stream:
            stream.write(
                json.dumps(
                    {"offset": self.elapsed(), "type": kind, **data},
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )

    def turn(self, speaker: str, text: str, interrupted: bool = False) -> None:
        if not text.strip():
            return
        turn = {
            "id": len(self.turns) + 1,
            "offset": self.elapsed(),
            "speaker": speaker,
            "text": text,
            "interrupted": interrupted,
        }
        self.turns.append(turn)
        self.event("turn", **turn)
        self.save_transcript()

    def save_transcript(self) -> None:
        write_json(self.path / "transcript.json", self.turns)
        lines = [f"Call: {self.path.name}", self.manifest["timestamp_note"], ""]
        for turn in self.turns:
            marker = " [interrupted]" if turn["interrupted"] else ""
            lines.append(f"[{timestamp(turn['offset'])}] {turn['speaker']}{marker}: {turn['text']}")
        (self.path / "transcript.txt").write_text("\n".join(lines) + "\n")

    def save(self, **changes) -> None:
        self.manifest.update(changes)
        write_json(self.path / "manifest.json", self.manifest)


def audit(root: Path) -> dict:
    """Conservative mechanical checks; listening remains required."""
    import soundfile as sf

    calls = []
    callers = set()
    for path in sorted(root.glob("*/manifest.json")):
        problems = []
        try:
            manifest = json.loads(path.read_text())
            callers.add(manifest["caller_number"])
            if manifest.get("destination") != TEST_NUMBER:
                problems.append("wrong destination")
            if manifest.get("status") != "complete":
                problems.append(f"call status: {manifest.get('status')}")
            turns = json.loads((path.parent / "transcript.json").read_text())
            for speaker in ("patient", "clinic"):
                if sum(t["speaker"] == speaker for t in turns) < 3:
                    problems.append(f"fewer than 3 {speaker} turns")
            info = sf.info(path.parent / "recording.ogg")
            if info.format != "OGG" or info.channels != 2:
                problems.append("recording is not a stereo OGG")
            if info.duration < 60:
                problems.append("recording shorter than 60s; review or rerun")
            if manifest.get("connected_seconds", 0) < 60:
                problems.append("connected conversation shorter than 60s; review or rerun")
            for speaker in ("patient", "clinic"):
                if manifest.get("audio", {}).get("active_seconds", {}).get(speaker, 0) < 2:
                    problems.append(f"missing or nearly silent {speaker} audio")
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            problems.append(f"invalid/missing artifact: {exc}")
        calls.append({"call": path.parent.name, "passes": not problems, "problems": problems})
    passing = sum(c["passes"] for c in calls)
    return {
        "passing_calls": passing,
        "minimum": 10,
        "single_caller": len(callers) == 1,
        "mechanically_ready": passing >= 10 and len(callers) == 1,
        "calls": calls,
        "note": "Mechanical checks do not establish conversation quality. Listen to every "
        "recording and verify transcripts and findings before submission.",
    }

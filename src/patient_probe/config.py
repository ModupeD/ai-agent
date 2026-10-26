from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Intentionally no destination environment variable or CLI argument.
TEST_NUMBER = "+18054398008"
CLINIC_IDENTITY = "clinic-under-test"
PATIENT_IDENTITY = "patient-simulator"
SAMPLE_RATE = 24000


@dataclass(frozen=True)
class Settings:
    url: str
    api_key: str
    api_secret: str
    trunk_id: str
    caller_number: str
    stt_model: str = "deepgram/nova-3"
    llm_model: str = "openai/gpt-4.1-mini"
    tts_model: str = "cartesia/sonic-3"
    tts_voice: str = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"
    max_call_seconds: int = 180
    artifacts: Path = Path("artifacts")

    @classmethod
    def load(cls) -> Settings:
        load_dotenv()
        names = [
            "LIVEKIT_URL",
            "LIVEKIT_API_KEY",
            "LIVEKIT_API_SECRET",
            "SIP_OUTBOUND_TRUNK_ID",
            "CALLER_NUMBER",
        ]
        missing = [n for n in names if not os.getenv(n, "").strip()]
        if missing:
            raise ValueError("Set these values in .env: " + ", ".join(missing))
        caller = os.environ["CALLER_NUMBER"].strip()
        if not re.fullmatch(r"\+[1-9]\d{7,14}", caller):
            raise ValueError("CALLER_NUMBER must be a valid E.164 number, e.g. +12125550123")
        if caller == TEST_NUMBER:
            raise ValueError("CALLER_NUMBER must be your own number, not the test destination")
        seconds = int(os.getenv("MAX_CALL_SECONDS", "180"))
        if not 60 <= seconds <= 240:
            raise ValueError("MAX_CALL_SECONDS must be between 60 and 240")
        models = {
            "stt_model": os.getenv("STT_MODEL", "deepgram/nova-3"),
            "llm_model": os.getenv("LLM_MODEL", "openai/gpt-4.1-mini"),
            "tts_model": os.getenv("TTS_MODEL", "cartesia/sonic-3"),
        }
        if any(
            any(x in v.lower() for x in ("realtime", "gemini-live", "speech-to-speech"))
            for v in models.values()
        ):
            raise ValueError("This project requires separate STT, text LLM, and TTS models")
        return cls(
            url=os.environ["LIVEKIT_URL"].strip(),
            api_key=os.environ["LIVEKIT_API_KEY"],
            api_secret=os.environ["LIVEKIT_API_SECRET"],
            trunk_id=os.environ["SIP_OUTBOUND_TRUNK_ID"].strip(),
            caller_number=caller,
            tts_voice=os.getenv("TTS_VOICE", cls.tts_voice),
            max_call_seconds=seconds,
            artifacts=Path(os.getenv("ARTIFACTS_DIR", "artifacts")),
            **models,
        )

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import typer
from dotenv import load_dotenv

from .artifacts import audit, campaign_lock
from .config import TEST_NUMBER, Settings
from .scenarios import SCENARIOS, get_scenario

app = typer.Typer(no_args_is_help=True, help="Patient Probe: pipeline voice testing with evidence.")


@app.command()
def scenarios():
    """List patient scenarios. Does not connect to any service."""
    for scenario in SCENARIOS:
        typer.echo(f"{scenario.id:20} {scenario.title}")


@app.command()
def doctor():
    """Check environment, OGG encoding and outbound trunk. Does not dial."""
    import numpy as np
    import soundfile as sf
    from livekit import api
    from livekit.agents import inference, room_io

    from .caller import validate_trunk

    try:
        settings = Settings.load()
        # BytesIO ensures the recording codec is functional before spending on a call.
        from io import BytesIO

        sf.write(
            BytesIO(), np.zeros((2400, 2), dtype=np.int16), 24000, format="OGG", subtype="VORBIS"
        )
        assert hasattr(inference, "STT") and hasattr(room_io, "RoomOptions")

        async def check():
            async with api.LiveKitAPI(
                settings.url, settings.api_key, settings.api_secret
            ) as client:
                await validate_trunk(client, settings)

        asyncio.run(check())
        typer.echo(
            f"Configuration, OGG codec and trunk OK. {settings.caller_number} → {TEST_NUMBER}"
        )
        typer.echo("Inference availability and audio quality still require a pilot call.")
    except Exception as exc:
        typer.echo(f"Setup incomplete: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command("check-model")
def check_model():
    """Load the bundled local VAD model without making an API call."""
    from livekit.plugins import silero

    silero.VAD.load()
    typer.echo("Local VAD model ready. STT, LLM and TTS run through LiveKit Inference.")


@app.command()
def run(
    scenario: str = typer.Option("01-schedule", help="Scenario ID, or 'all' for all 12."),
    limit: int = typer.Option(10, min=1, max=12, help="Maximum calls when scenario=all."),
):
    """Place real calls sequentially. Starts with one pilot unless --scenario all is supplied."""
    from .caller import run_call

    logging.basicConfig(level=logging.INFO)
    try:
        settings = Settings.load()
        selected = SCENARIOS[:limit] if scenario == "all" else [get_scenario(scenario)]
        typer.echo(
            f"Calling ONLY {TEST_NUMBER} from {settings.caller_number}; {len(selected)} call(s)."
        )

        async def campaign():
            with campaign_lock(settings.artifacts, settings.caller_number):
                for item in selected:
                    typer.echo(f"Starting {item.id}: {item.title}")
                    manifest = await run_call(settings, item)
                    typer.echo(f"Saved {manifest['id']} ({manifest['status']})")
                    if manifest["status"] == "incomplete":
                        raise ValueError(
                            f"Conversation ended at {manifest['end_reason']}; "
                            "audio and transcript were saved. Review them before another call."
                        )
                    if manifest["status"] != "complete":
                        raise ValueError(
                            "Call capture failed. Inspect its events before continuing."
                        )
                    if item != selected[-1]:
                        await asyncio.sleep(5)

        asyncio.run(campaign())
    except Exception as exc:
        typer.echo(f"Call stopped: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command()
def analyze(call: Path = typer.Argument(..., exists=True, file_okay=False)):
    """Use paid text inference to propose evidence-linked findings for one call."""
    from .evaluation import analyze_call

    try:
        settings = Settings.load()
        review = asyncio.run(analyze_call(call, settings.llm_model))
        typer.echo(
            f"{len(review['findings'])} candidates saved to {call / 'review.json'}; "
            "listen to the audio before accepting any finding."
        )
    except Exception as exc:
        typer.echo(f"Analysis failed: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command()
def report(
    root: Path = typer.Option(Path("artifacts"), help="Campaign artifact directory."),
    output: Path = typer.Option(Path("docs/BUG_CANDIDATES.md")),
):
    """Build a Markdown report from reviewed call artifacts; no API calls."""
    from .evaluation import build_report

    output.parent.mkdir(parents=True, exist_ok=True)
    build_report(root, output)
    typer.echo(f"Saved {output}")


@app.command("audit")
def audit_command(root: Path = typer.Option(Path("artifacts"))):
    """Check the ten-call minimum, caller consistency and evidence files. No API calls."""
    load_dotenv()
    result = audit(root)
    typer.echo(json.dumps(result, indent=2))
    if not result["mechanically_ready"]:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

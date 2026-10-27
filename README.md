# Call Agent

A Python patient simulator that calls a fixed assessment line, holds a voice conversation, and saves both speakers' audio and transcripts. It uses **LiveKit Agents in pipeline mode: Deepgram Nova-3 STT → GPT-4.1 mini text LLM → Cartesia Sonic-3 TTS**, accessed through LiveKit Inference.

After setup, start one call with:

```sh
call-agent run
```

## Requirements

- **macOS or Linux**, Python **3.10–3.13**, and a terminal that stays open throughout the call.
- A **LiveKit Cloud project** with Inference access and API credentials.
- An **outbound SIP trunk** connected to a telephone provider, such as Twilio.
- **One voice-capable caller number** authorized on that trunk, reused for every assessment call.

The default models use your LiveKit credentials. Separate OpenAI, Deepgram and Cartesia API keys are unnecessary. Calls, model inference and LiveKit services can incur usage charges. A local server deployment, storage bucket and ffmpeg installation are unnecessary.

## Setup

Run these commands from the repository root using a supported Python version:

```sh
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

Copy `.env.example` only on first setup; keep an existing populated `.env`. If you move or rename the project directory, recreate its virtual environment.

Complete the [account and SIP trunk setup](docs/SETUP.md), then fill in these five values in `.env`:

| Variable | Where to get it |
| --- | --- |
| `LIVEKIT_URL` | Your LiveKit project's `wss://` server URL |
| `LIVEKIT_API_KEY` | LiveKit project API key |
| `LIVEKIT_API_SECRET` | Secret paired with that API key |
| `SIP_OUTBOUND_TRUNK_ID` | The **LiveKit outbound trunk ID**, usually starting with `ST_` |
| `CALLER_NUMBER` | Your purchased/authorized caller number in E.164 format, including `+` and country code |

Keep the model defaults in `.env.example` initially. The application loads `.env` itself. `.env` and `.venv/` are excluded from Git.

For a Twilio trunk with **Secure Trunking** enabled, configure its LiveKit outbound trunk with **Transport: TLS** and **Media encryption: Required**. Its address must match Twilio's full Termination hostname, and its authentication must match the username/password inside the attached Twilio Credential List.

Verify setup without dialing:

```sh
call-agent check-model
call-agent doctor
```

`check-model` loads local VAD. `doctor` checks configuration, OGG encoding and the outbound trunk. A pilot call is still needed to validate inference access, telephone connectivity and audio quality.

## Run a call

```sh
call-agent run
```

The default scenario is new-patient scheduling. Every call goes only to **+1-805-439-8008**; there is no destination override. The caller ID comes from `CALLER_NUMBER`.

To choose another scenario:

```sh
call-agent scenarios
call-agent run --scenario 05-hours
```

After listening to a pilot, run up to ten scenarios sequentially with:

```sh
call-agent run --scenario all --limit 10
```

The batch makes real calls with five seconds between calls and stops on a failed or incomplete attempt. Each run creates a new evidence folder. Calls normally end after the task is resolved or blocked, with a brief goodbye and time for the clinic to reply. `MAX_CALL_SECONDS` defaults to **180**; the duration limit stays in effect even during closing. These limits do not enforce a dollar spending cap.

The earlier command name, `patient-probe`, is also available as an alias.

## Find recordings and transcripts

Each call is saved under `artifacts/<timestamp>-<scenario>/`:

| File | Contents |
| --- | --- |
| `recording.ogg` | Actual two-sided stereo audio: **patient left, clinic right** |
| `transcript.txt` | Readable conversation with speaker labels and timestamps |
| `transcript.json` | Turn IDs, text, timestamps and interruption markers |
| `manifest.json` | Scenario, models, caller, outcome, duration and recording status |
| `events.jsonl` | Conversation events, usage, state changes and errors |
| `history.json` | SDK conversation and tool history, when available |

The recorder persists PCM during the call and creates the OGG when the call ends. Transcript timestamps are approximate turn-commit offsets from capture start and include dialing time. Listen slightly before a cited timestamp when reviewing an issue.

Check the evidence minimum without placing calls:

```sh
call-agent audit
```

The audit checks for at least ten complete calls with both speakers, usable stereo OGG files, and sufficient duration/audio activity. Failed, incomplete and quality-flagged attempts are excluded. **Listen to every selected recording:** passing mechanical checks does not prove coherent dialogue. A `blocked` outcome can be a complete conversation, but does not mean an appointment or refill succeeded. Replace disrupted or trivial calls rather than padding their duration.

## Review possible bugs

Use an actual call-folder path from `artifacts/` in place of `CALL_FOLDER`:

```sh
call-agent analyze artifacts/CALL_FOLDER
call-agent report
```

`analyze` uses paid text inference and saves candidate findings in that call's `review.json`. Exact transcript quotes and turn IDs are validated. `report` combines existing reviews into `docs/BUG_CANDIDATES.md` without making API calls. Verify candidates against the audio and document confirmed findings in [the bug report](docs/BUG_REPORT.md).

## Development checks

```sh
python -m pytest -q
ruff check src tests
```

Tests include call cleanup, caller/destination restrictions, natural-ending behavior, interrupted-goodbye handling, two-sided OGG encoding and evidence validation. Mocked calls do not establish real phone connectivity or audio quality.

## Project documents

- [Architecture and design choices](docs/ARCHITECTURE.md)
- [Account setup and troubleshooting](docs/SETUP.md)
- [Iteration evidence](docs/ITERATION.md)
- [Bug report](docs/BUG_REPORT.md)
- [Submission and video checklist](docs/SUBMISSION.md)

Recordings and transcripts are intentionally tracked for submission. Keep the repository **private**, and never commit API credentials or passwords.

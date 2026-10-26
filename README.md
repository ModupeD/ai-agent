# Patient Probe

A Python voice caller that behaves as a patient, captures both sides of each call, and proposes evidence-linked issues for human review. It uses **LiveKit Agents in pipeline mode: Deepgram Nova-3 STT → GPT-4.1 mini text LLM → Cartesia Sonic-3 TTS** through LiveKit Inference. No speech-to-speech model or hosted voice-agent platform is used.

**Status:** pilot testing is underway. The latest pilot saved valid two-sided OGG audio and a transcript, but reached the duration limit before a natural ending. An earlier pilot lost its audio during encoding. No clinic bugs are confirmed; ten complete reviewed calls and videos remain outstanding.

## Setup

Use Python 3.10–3.13. On this machine, a Python 3.10 `.venv` is already installed. Activate it:

```sh
source .venv/bin/activate
```

For a fresh checkout with a compatible Python:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

Complete the account setup in [docs/SETUP.md](docs/SETUP.md), then fill in `.env`. Keep secrets out of Git. You need a LiveKit Cloud project with Inference access and a stored outbound SIP trunk with one purchased telephone number. The default models use LiveKit credentials; separate speech/LLM provider keys are not needed. No server deployment, cloud storage bucket, or ffmpeg installation is required.

Verify the local VAD, credentials, recording codec, and trunk before calling:

```sh
call-agent check-model
call-agent doctor
```

`doctor` makes an authenticated trunk lookup but does not dial. It does not establish that inference access or voice quality works.

## Make and inspect a pilot call

```sh
call-agent run
```

This starts one scheduling call. The only destination is **+1-805-439-8008**, hard-coded in the application. Every call explicitly uses `CALLER_NUMBER`, which must belong to your trunk. Keep the terminal running throughout the call. The local call deadline defaults to 180 seconds; SIP also receives a separate maximum duration as a fallback if the local process fails.

The caller uses `finish_call` to speak a factual recap and goodbye after a resolved task or a blocked task with a clear next step. Before speaking its closing recap, it waits through clinic speech and 1.2 seconds of sustained quiet. The goodbye remains interruptible, and an interruption returns to listening. It then keeps both audio tracks and clinic transcription active for a reply, allowing up to eight seconds of quiet and waiting for ongoing clinic speech within the original call deadline. Closing does not generate extra questions. The manifest records `outcome`, `recap`, `farewell_played`, `ending_complete`, and `clinic_reply_captured`. A clinic that stays silent is not given an invented farewell. Unresolved or interrupted conversations remain incomplete. The closing controller is tested offline; real conversational quality still requires listening.

Open the newest folder under `artifacts/` and **listen to `recording.ogg`** before scaling up. Patient is the left channel and clinic is the right. Check that both voices are intelligible, turns do not collide, the caller follows the scenario, and the transcript matches what was actually said. A pilot that cannot hold a coherent conversation needs iteration before a campaign.

```sh
call-agent scenarios
call-agent run --scenario 07-correction
call-agent run --scenario all --limit 12
```

Calls run sequentially, with five seconds between calls. The campaign stops on an error or incomplete call. Each invocation creates fresh evidence folders; reruns do not overwrite earlier attempts. The campaign file prevents switching caller numbers within the artifact directory, and a process lock prevents overlapping runs. Continue using the same number across directories and the entire assessment.

Natural endings may be shorter than a minute, especially urgent escalation. Do not pad the conversation to satisfy a timer: use additional substantive scenarios or reruns to reach at least ten full conversations, typically 1–3 minutes each. The audit conservatively flags recordings and connected conversations under 60 seconds for review/rerun.

## Analyze and prepare evidence

```sh
call-agent analyze artifacts/ACTUAL-CALL-FOLDER
call-agent report
call-agent audit
```

Analysis uses paid text inference and produces `review.json`. Every candidate must quote an exact substring from a real transcript turn and cite the clinic; invalid evidence rejects the analysis. The report is a draft, **not a set of confirmed bugs**. Listen to audio, investigate context and STT errors, and write confirmed findings in [docs/BUG_REPORT.md](docs/BUG_REPORT.md). Office hours, insurance policies and backend booking state are not assumed facts.

Audio is saved incrementally to `audio-patient.pcm` and `audio-clinic.pcm`, then encoded in 4096-frame blocks in a separate process. A codec crash cannot discard the captured PCM. If conversion fails, retry locally with `python -m patient_probe.encode artifacts/ACTUAL-CALL-FOLDER`; this does not dial or use inference. Check the call status and listen before treating recovered audio as usable evidence. PCM files are ignored by Git; submit the validated OGG.

Each call folder contains:

| File | Purpose |
| --- | --- |
| `recording.ogg` | Actual subscribed patient and clinic audio, stereo Vorbis |
| `transcript.txt`, `transcript.json` | Both speakers, turn IDs, interruptions and commit offsets |
| `manifest.json` | Scenario, fixed destination, caller ID, model settings, timings, outcome and audio statistics |
| `events.jsonl` | Incremental turns, state changes, pipeline metrics and errors |
| `history.json` | SDK conversation/tool history, when session cleanup succeeds |
| `review.json`, `review-raw.txt` | Optional evaluator output and raw response |

Offsets start at capture setup and include dialing time. Transcript offsets are commit times, not word-aligned speech timestamps. Seek a little earlier in the audio. An interrupted patient turn may contain only the portion committed by the SDK; verify all quotes by listening. Stereo frame arrival timing approximates the common timeline and can drift under network jitter. Recordings are not made by re-synthesizing transcript text.

## Check the implementation

```sh
python -m pytest -q
ruff check src tests
```

Tests cover number and trunk restrictions, campaign caller consistency, failed-call cleanup, recording both actual audio channels into OGG, artifact completeness, and rejection of fabricated evaluator evidence. Mocked calls test lifecycle behavior; they do not prove PSTN connectivity or conversation quality.

Read [architecture](docs/ARCHITECTURE.md), [iteration notes](docs/ITERATION.md), and the [submission checklist and video outlines](docs/SUBMISSION.md). Recordings and transcripts are intentionally not ignored by Git because they are required submission artifacts. Review the staged files for secrets and unnecessary personal information before committing to a **private** repository.

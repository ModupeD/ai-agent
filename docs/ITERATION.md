# Iteration log

No pilot calls or listening results yet. The entries below describe local engineering changes only.

| Observation | Change | Evidence / next validation |
| --- | --- | --- |
| A compatible Python 3.10 installation already exists | Created project-local `.venv`, installed dependencies there | CLI and tests execute inside `.venv` |
| Installed SDK semantic turn detector expects a worker job context | Selected local Silero VAD turn detection for direct room sessions | SDK construction check; tune against pilot audio |
| Generated findings could cite invented text or blame the patient | Require exact transcript quotes, valid turn IDs and clinic evidence | Rejection tests cover invented and misattributed quotes |
| Disconnect or SIP failure can leave incomplete evidence | Preserve failure events, close session/recorder, delete room; provide SIP duration cap | Mocked SIP-failure cleanup test; verify live dashboard after pilot |

For each real pilot or rerun, add: call ID, audible problem with a seek time, proposed cause, the exact prompt/configuration change, the comparison call ID and observed result. Log changes that failed as well as improvements. Do not claim a measured improvement without listening to both recordings.

## First real pilot — 20261025T180022368394Z-01-schedule

The pilot failed before answer with SIP 403 Forbidden. Startup also exposed two simulator bugs: treating AgentHandoff as a chat message and starting speech plugins outside an SDK HTTP context. Added a scoped HTTP context covering startup through cleanup, filtered non-message history events, and stopped calls on fatal pipeline errors. Regression tests use real SDK message types and actual speech-plugin HTTP session initialization without a worker or network request. These checks do not establish PSTN connectivity; the provider-side 403 still requires separate diagnosis.

## Connected pilot — 20261025T184053189112Z-01-schedule

After fixing SIP hostname/authentication and TLS/SRTP configuration, the clinic answered and the transcript reached a scheduling confirmation. Overlapping turns and repeated requests appear around 01:16–01:45. This is transcript evidence only; the call is not submission-ready. The local deadline ended the conversation and the native OGG encoder then crashed. The macOS report identifies SIGBUS with stack exhaustion in libsndfile/Vorbis `_preextrapolate_helper` on the encoding thread. The resulting OGG contains zero frames.

Fix: persist raw PCM as frames arrive, encode 4096-frame blocks in a subprocess, and publish the OGG atomically only after validating its duration/channels. An offline 190-second stereo conversion succeeds; a failed-codec test confirms PCM survives. Disable unused remote-session/text streams to eliminate console spam and session-transport shutdown warnings. Use current SDK turn/usage APIs. Increase endpointing to 1.3s, interruptions to 0.8s/three words, and prompt the patient to wait during office processing. The pacing changes are hypotheses awaiting a live comparison call. No additional paid call was made for these checks.

## Recorded pilot — 20261025T185533354100Z-01-schedule

The recorder successfully produced 187.88 seconds of stereo OGG, with non-silent patient and clinic channels and no capture errors. The call reached the unchanged 180-second connected deadline and is correctly incomplete. Around 02:04 the office could not find the synthetic record and offered support; the patient kept asking optional questions until cut off. This is a simulator stopping problem, not evidence of a clinic bug. Tightened the scheduling scenario and shared instructions: after a blocked outcome and next step, recap and finish rather than asking location/modality/form questions. Added a final-turn reminder within 35 seconds of the existing deadline, injected only after clinic speech ends. The reminder uses connected time and respects shorter configured budgets. CLI messages now distinguish duration cutoff from failed audio capture. Timing regression checks are offline; a live natural ending has not yet been validated. No new call was placed for this change.

## Natural ending controller — offline validation

The old finish_call ignored its outcome argument and disconnected immediately after a fixed goodbye. Replaced this with structured resolved/blocked/unresolved outcomes and a spoken factual recap plus goodbye. The tool returns no follow-up speech. A closing state keeps STT and both recorded audio tracks active, saves a clinic reply before ending, and suppresses further generated questions. The caller waits through the clinic response or up to eight quiet seconds, without increasing MAX_CALL_SECONDS. The final budget window forces the finish tool instead of only reminding the model. The manifest records the observed closing state. Unresolved wrap-ups, early disconnects, incomplete farewell playout and hard cutoffs cannot become completed calls.

Thirty offline tests pass, including resolved and blocked playout ordering, clinic reply capture, silent clinic grace, continued clinic speech, state/transcript event ordering, duplicate tool suppression, forced tool selection, unresolved status and a cleanup-disconnect race after a hard deadline. The existing 190-second stereo OGG regression still passes. No paid calls were made for this change; a fresh live pilot remains necessary.

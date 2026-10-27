# Caller and recording debugging

These are defects in the patient simulator and its evidence capture, not findings against the clinic agent. They are retained to explain engineering iteration. See [BUG_REPORT.md](BUG_REPORT.md) for the assessment findings and [ITERATION.md](ITERATION.md) for the change history.

Transcript times below are commit offsets; seek several seconds earlier. Fix status distinguishes implemented changes from proposed work and offline checks from listening review.

### S1 — Closing speech overlaps the clinic's response

**Severity:** Medium. **Status:** Confirmed by user listening feedback and runtime events; controller fix implemented.

**Steps:** Run `11-multi-intent`; after the missing-record response, ask for the next step and refill process. The caller invokes its ending tool while the clinic is answering.

**Observed:** Clinic speaking events span 134.67–145.87 seconds. Caller closing speech begins at approximately 135.70 seconds. Transcript turns 12–14 capture the question, premature recap, and clinic response.

**Expected:** Wait for the clinic to finish before speaking the goodbye, retaining both audio tracks and the clinic transcript.

**Evidence:** [transcript](../artifacts/20261026T011328885498Z-11-multi-intent/transcript.txt), [audio](../artifacts/20261026T011328885498Z-11-multi-intent/recording.ogg), [events](../artifacts/20261026T011328885498Z-11-multi-intent/events.jsonl). Listen from 02:10.

**Cause and fix:** The ending tool waited for the caller's own playout, but did not gate speech on clinic activity. It now waits for clinic speech to end and 1.2 seconds of sustained quiet. Resumed speech resets the wait; the original call deadline still applies. Offline tests cover active and resumed clinic speech. The original attempt is rejected by the quality audit. A later comparison call exists (`20261026T012607504846Z-11-multi-intent`); there is no recorded listening verdict establishing universal resolution.

### S2 — Interrupted closing recap is spoken twice

**Severity:** Medium. **Status:** Confirmed by user feedback and transcript; replay-prevention fix implemented.

**Steps:** Run `12-unavailable` and reach the support-transfer ending. Interrupt the long closing recap.

**Observed:** Patient turns 14 (02:46) and 16 (02:56) repeat the appointment-request recap and goodbye around the clinic's test-line farewell.

**Expected:** An interrupted goodbye must not restart the full recap or be labeled a successfully completed ending.

**Evidence:** [transcript](../artifacts/20261027T012112267065Z-12-unavailable/transcript.txt), [audio](../artifacts/20261027T012112267065Z-12-unavailable/recording.ogg). Listen from 02:30.

**Cause and fix:** Resetting closing state after interruption allowed another ending-tool invocation. The tool now stores the recap in the manifest, speaks one brief goodbye, and preserves closing state after spoken interruption. Interrupted endings remain incomplete. Offline tests cover interruption, cancellation, replay prevention, and final status. This attempt is excluded from the audit. The replacement [transcript](../artifacts/20261027T100158265910Z-12-unavailable/transcript.txt) and [audio](../artifacts/20261027T100158265910Z-12-unavailable/recording.ogg) contain one short goodbye (turn 12); the user described that replacement as good. One successful replacement does not prove the issue can never recur.

### S3 — Patient generates an office-agent response

**Severity:** Medium. **Status:** Observed in generated patient text; prompt mitigation implemented, not a deterministic guarantee.

**Observed:** In `20261027T012112267065Z-12-unavailable`, patient turn 12 appends “I'll check that for you right now. Please hold for a moment.” to its appointment request. The patient cannot check clinic availability or put the receptionist on hold.

**Expected:** Remain in the patient role, ask the question, and wait for the office's response.

**Evidence and reproduction:** Same recording/transcript as S2; seek around 02:15. This role reversal appears in one saved turn; no controlled reproduction has been performed. The text is recorded as generated patient output, rather than a clinic STT quote. Audio review is still needed to establish how much of that output was audible.

**Mitigation:** Shared instructions now require brief patient answers and explicitly prohibit appending receptionist phrases. The replacement call does not contain this phrase. Prompt instructions reduce risk but do not enforce a hard role boundary.

### S4 — Native OGG encoding crashes and loses the deliverable recording

**Severity:** High. **Status:** Confirmed capture failure; encoding fix implemented and checked offline and in later calls.

**Steps:** Finish the original connected scheduling pilot and encode the accumulated stereo audio using the original encoder.

**Observed:** The native Vorbis encoding process crashed with SIGBUS; the output OGG had zero frames. The conversation transcript survived, but playable evidence did not.

**Expected:** Save a valid two-channel OGG recording; preserve raw capture if conversion fails.

**Evidence:** [failed-call manifest](../artifacts/20261025T184053189112Z-01-schedule/manifest.json), [transcript](../artifacts/20261025T184053189112Z-01-schedule/transcript.txt), and the diagnosis recorded in [the iteration log](ITERATION.md). The macOS crash report is described in that log but is not attached here. This call cannot support audio-confirmed clinic findings.

**Cause and fix:** The crash investigation identified stack exhaustion in libsndfile/Vorbis `_preextrapolate_helper` during the original large write. Recording now persists PCM incrementally and encodes 4096-frame blocks in an isolated subprocess, publishing OGG only after validation. Offline tests cover a 190-second recording and PCM retention after encoder failure. Later calls have valid stereo OGG files. No deliberate live crash reproduction was performed.

### S5 — Caller accepts a transfer and immediately says goodbye

**Severity:** Medium. **Status:** Open; observed in the latest scheduling transcript.

**Steps:** Run the default `call-agent run`, reach a missing-record support offer, and allow the caller to respond.

**Observed:** Patient turn 14 says “Yes, please connect me to the patient support team”; turn 15 immediately says “Okay, thanks for your help. Goodbye.” The clinic then announces the transfer (turn 16). Here the clinic has explicit transfer consent, so this is a caller inconsistency, distinct from C1.

**Expected:** Choose a coherent next action. For this caller's blocked-task ending policy, decline the transfer, acknowledge the support next step, and end politely. If accepting a transfer is permitted, wait for its outcome instead of immediately ending.

**Evidence:** [transcript](../artifacts/20261027T102535310991Z-01-schedule/transcript.txt), [audio](../artifacts/20261027T102535310991Z-01-schedule/recording.ogg). Listen from approximately 02:15. One observed occurrence; no controlled retest. Audio review pending.

**Proposed fix:** Make the transfer policy explicit in patient instructions and align it with the ending controller. This change has not been applied as part of writing this report.


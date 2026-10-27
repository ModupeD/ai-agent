# Clinic-agent bug report

This report evaluates the clinic agent on the assessment line. Caller and recording defects are documented separately in [CALLER_DEBUGGING.md](CALLER_DEBUGGING.md); they are evidence of engineering iteration, not bugs found in the system under test.

The saved evidence supports one clinic-agent finding requiring audio review. It does not yet establish an audio-confirmed clinic defect. No additional calls or paid model requests were made for this report.

Transcript timestamps are turn-commit offsets, not speech start times. Seek several seconds earlier in each recording. Audio channels: patient left, clinic right.

### C1 — Transfer announced after the caller ends the conversation

**Severity:** Medium. **Status:** Observed in two transcripts; audio review pending. Clinic implementation and transfer policy are unavailable.

**Steps:** Request appointment assistance, provide fictional identity details, reach the support-transfer offer, then end the conversation without accepting the offer.

**Expected:** Acknowledge the goodbye and end. If a transfer is still necessary, clarify the caller's preference before proceeding.

**Observed:** In the rescheduling call, the clinic asks “Would you like me to connect you to our patient support team?” (turn 9, 01:33). The caller ends with “Thank you for your help. Goodbye.” (turn 10, 01:45). The clinic responds “Please stay on the line. Transferring you now.” (turn 11, 01:55). In the cancellation call, the caller says “I will contact support to create my record before booking. Thank you for your help. Goodbye.” (turn 12, 02:17); the clinic responds “Transferring you now. Thank you.” (turn 13, 02:17).

**Evidence:**

- Reschedule: [transcript](../artifacts/20261026T002241950940Z-02-reschedule/transcript.txt), [audio](../artifacts/20261026T002241950940Z-02-reschedule/recording.ogg). Listen from approximately 01:20.
- Cancellation: [transcript](../artifacts/20261026T003010677360Z-03-cancel/transcript.txt), [audio](../artifacts/20261026T003010677360Z-03-cancel/recording.ogg). Listen from approximately 01:55.

**Impact:** The caller's closing intent is disregarded, creating confusion about whether they should remain on the line.

**Limits and reproduction:** The pattern appears in two scenarios, but neither is a controlled explicit-decline retest. The caller's report-style goodbye and turn overlap may affect interpretation. Transcripts prove the transfer announcement, not that a transfer successfully occurred. The test-line goodbye is not independently established as a broken transfer destination. Do not classify this as an audio-confirmed clinic defect until the linked sections have been reviewed.

## Coverage and remaining limits

Calls exercised scheduling, rescheduling/cancellation requests, a refill request, office questions, insurance questions, corrections, unclear requests, and an unavailable-time request. Several scenarios stopped at the same missing-record/support path. Scenario names alone do not establish that cancellation, refill processing, schedule validation, or every intended follow-up was tested. In particular, the Sunday request never reached an availability decision, so it does not demonstrate the example weekend-booking bug.

The local audit counts 11 calls as mechanically eligible at this revision. This is an artifact check, not a judgment that all 11 conversations meet the assessment's quality bar. Listen to the selected calls before submission. No bugs are inferred merely to increase the count of findings.

## Behaviors not established as clinic bugs

- The fictional patient's record not being found does not establish a database or lookup defect. No matching seeded record is known to exist.
- Closed Saturdays, appointment-only visits, and plan-specific insurance verification are stated policies, not proven failures.
- The insurance call's connection resets and partial answer do not establish a clinic reasoning defect; the caller/network/provider path is a confounding factor.
- The first pilot's unprovided birth date is a possible clinic finding, but its audio was lost and demo-profile defaults are unknown. It is not counted as confirmed.
- No urgent-symptom or privacy scenario recording is present in this evidence set; neither behavior is claimed to have been tested.

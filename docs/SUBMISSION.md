# Submission checklist

The application alone is not a completed submission. Pilot calls have been attempted; usable completed call evidence and videos remain outstanding.

- [ ] Create the test account and inspect the patient experience. Do not call its confirmation-screen number.
- [ ] Use one caller number for every assessment call; destination is always +18054398008.
- [ ] Make a pilot, listen to it, fix the largest conversation defect, and document the change in `ITERATION.md`.
- [ ] Obtain at least ten full conversations, generally 1–3 minutes each, with both sides in OGG audio and transcripts. Listen to every recording; replace failed or trivial attempts with substantive calls.
- [ ] Run `call-agent audit`; investigate failures. Passing the audit is not a substitute for listening.
- [ ] Review generated candidates and write actual findings in `BUG_REPORT.md`, including audio locations and impact.
- [ ] Keep working code, README, architecture, transcripts, OGG recordings and bug report in a **private** GitHub repository. Suggested repository name: `call-agent`. Follow the challenge's naming restrictions for the repository name, description, README title and walkthrough.
- [ ] Add `eng-challenge@prettygoodai.com` as a collaborator using GitHub Settings → Collaborators → Add people, as explicitly requested by the assessment. Do not send direct outreach outside the submission process.
- [ ] Record both videos yourself, with your own voice and webcam, and verify links are viewable by anyone with the link.
- [ ] Put the private repository link, both video links and your exact E.164 caller number on the official submission form.
- [ ] Keep receipts if requesting the stated reimbursement. Keep the repository private after submission.

## Walkthrough outline — maximum 3 minutes

Use your own words and keep your webcam on. Do not say either prohibited company name or acronym from the challenge.

- **0:00–0:25:** State the task: an adaptive patient caller testing an office voice agent. Explain why conversational coherence is the first acceptance test.
- **0:25–1:00:** Show the separate STT → text LLM → TTS pipeline, outbound SIP connection and fixed destination. Explain provider choice and turn-taking tradeoffs.
- **1:00–1:45:** Play one short segment from an actual call. Show the matching transcript and one high-value finding, or an honest limitation if no bug is established.
- **1:45–2:25:** Compare a pilot failure with a rerun after your change. Explain what you heard, the hypothesis and how you tested it.
- **2:25–3:00:** Show the ten-call audit and evidence folders. State what remains uncertain and one improvement you would prioritize.

## AI debugging screen recording

Record a real debugging session with your voice and webcam. Do not present a reconstructed chat as a live session. Show the symptom, your prompt, the suggested change, your reasoning, and a test or call that verifies the result. Useful prompts to adapt to an actual problem:

1. “Here is the failed call event and the matching audio segment. Identify likely causes and propose the smallest check that distinguishes them.”
2. “Inspect the installed SDK signature and trace this failure. Explain why the existing code fails before editing it.”
3. “Implement the smallest fix. Preserve the fixed destination and caller ID, and add a regression test for this failure path.”
4. “Compare the before/after evidence. What does the test establish, and what still requires a real call?”

The outline is preparation material, not a video deliverable. You must record and upload both videos yourself.

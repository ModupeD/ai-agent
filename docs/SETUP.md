# Account and telephone setup

1. Create the assessment test account at https://pgai.us/athena and inspect the patient flow. **Do not call the number on its confirmation screen.** Record any observed practice details separately; do not guess policies from the scenario descriptions.
2. Create a [LiveKit Cloud](https://cloud.livekit.io/) project, enable the relevant Inference and SIP services, and copy the project WebSocket URL, API key and API secret into `.env`. Defaults use distinct STT, text LLM and TTS services through [LiveKit Inference](https://docs.livekit.io/agents/models/inference/). Check project balances and model availability in the dashboard.
3. Obtain **one** voice-capable number from a SIP provider. Twilio Elastic SIP Trunking is one documented option. Follow LiveKit's [Twilio trunk guide](https://docs.livekit.io/telephony/start/providers/twilio/) to attach the number to a trunk, configure a Termination SIP URI and attach a credential list. Provider trial restrictions may prevent dialing the assessment line; verify restrictions in your account before buying credits.
4. In LiveKit, create a **stored outbound trunk** using your provider's termination hostname and credential-list username/password, following the [outbound trunk guide](https://docs.livekit.io/telephony/making-calls/outbound-trunk/). Set its numbers list to your one purchased E.164 caller number. Credentials belong in the provider/LiveKit console, not in repository files. For Twilio the address is generally `<your-trunk>.pstn.twilio.com`; use the actual hostname from your console. An inbound trunk or inbound dispatch rule is unnecessary for this local outbound caller.
5. Put the LiveKit trunk ID in `SIP_OUTBOUND_TRUNK_ID` and your purchased number in `CALLER_NUMBER`. Always use the same number throughout testing and report that exact number on the submission form. You do not need your telephone provider's REST API keys in this application.
6. Activate `.venv`, run `call-agent check-model`, then `call-agent doctor`. Resolve missing credentials or trunk membership failures before calling.
7. Run `call-agent run`, listen to the pilot recording, and iterate before starting a full campaign.

All assessment calls must go only to **+18054398008**. The application has no destination override. Do not use the account confirmation-screen number. Do not configure automatic telephone transfers in the simulator.

Track actual telephony, Inference and LiveKit transport usage in provider dashboards. Duration and sequential-call limits constrain usage but do not enforce a dollar budget; model prices, provider fees and rounding vary. Keep receipts for the assessment's stated reimbursement allowance. Use one pilot before committing to a batch.

Troubleshooting:

- **Missing `.env` settings:** fill the five required variables from `.env.example`. Leave defaults for model settings initially.
- **SIP 403 / forbidden:** verify termination hostname, attached credential list, number association, permissions and account restrictions. The failed call's `events.jsonl` preserves the exception.
- **Inference authorization/model error:** check LiveKit project access and balance. `doctor` validates the trunk, not inference billing. Keep STT, text LLM and TTS separate when changing models.
- **Only one voice / silence:** inspect `manifest.json` audio counters and recording errors; listen to both stereo channels. An empty or one-sided recording fails the audit.
- **Frequent interruptions:** listen to overlapping segments before increasing endpointing or interruption thresholds in `caller.py`; measure whether the change reduces collisions without adding excessive delay.
- **Process exits during a call:** local cleanup deletes the room and falls back to removing the SIP participant on an API error. A server-side SIP duration cap also limits call lifetime. Verify in the LiveKit dashboard that the participant disconnected if network cleanup failed.

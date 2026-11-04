# Architecture

## Motion path

1. Grok calls `propose_robot_skill` with an enabled `skill_id`. The tool schema has no coordinate or speed field.
2. `Session` checks the skill and robot state, then opens one proposal with a 30 s lifetime.
3. Grok asks for confirmation.
4. Grok calls `confirm_and_execute`. `ConfirmationFSM` requires the matching proposal id and a clear yes spoken after the proposal. Negation beats yes.
5. The proposal is consumed and the adapter starts one skill.
6. Grok stays silent. The result comes from the adapter and is spoken with `force_message`.

## Stop paths

Each path calls `Session.request_stop`, and none waits for a model reply.

| Path | Signal |
| --- | --- |
| Speech detected during motion | `input_audio_buffer.speech_started`, set by `STOP_ON_ANY_SPEECH` |
| Stop word in a partial transcript | `conversation.item.input_audio_transcription.updated` |
| Stop word in a final transcript | `...transcription.completed` or `conversation.item.added` |
| Button or space bar | WebSocket and `POST /api/stop` |
| Grok tool | `stop_robot` |
| Lost link | Grok, browser or mic stream gone during motion |

## Files

| File | Job |
| --- | --- |
| `backend/session.py` | Safety core: proposals, execution, stop |
| `backend/confirmation_fsm.py` | One proposal, one yes, one motion |
| `backend/speech_rules.py` | Stop and confirmation word rules |
| `backend/skill_registry.py` | Skill allowlist and approved pose loading |
| `backend/tools.py` | Grok prompt, tool schema, tool dispatch |
| `backend/voice_gateway.py` | Grok link, plus an offline typed mode |
| `backend/mock_adapter.py`, `ur3e_adapter.py` | Same contract for simulation and hardware |
| `backend/keyword_baseline.py` | Baseline for evaluation |
| `frontend/index.html` | Operator page, no build step |

## To verify on the live API

The gateway was tested against a scripted stream built from xAI's documentation. Run `scripts/check_grok.py` first, then confirm: transcript timing against tool calls, the `completed` event name, `force_message` behaviour, and whether `reasoning.effort: none` is accepted.

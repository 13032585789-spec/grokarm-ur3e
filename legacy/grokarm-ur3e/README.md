# GrokArm

Control a Universal Robots UR3e in natural Italian. Grok picks one of 3-5 approved skills, asks for spoken confirmation, the arm moves, and the system reports the result read from the controller. A spoken stop works at any point.

Built for Track 04 (Voice Control) of the Grok Hackathon at the Museum, Pavia, 4-5 November 2026.

## Run it

Needs Windows with Python 3.12. `ur_rtde` 1.6.5 has no Windows wheel for 3.13.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# add XAI_API_KEY to .env
powershell -ExecutionPolicy Bypass -File scripts\run.ps1
```

Open http://localhost:8000 in Chrome or Edge and press Microfono. With no key the page runs offline: typed commands, keyword rules, simulated arm.

| Setting in `.env` | Values |
| --- | --- |
| `ROBOT_MODE` | `mock`, `ursim`, `real` |
| `VOICE_MODE` | `grok`, `offline` |
| `ALLOW_REAL_MOTION` | `STAFF_APPROVED`, only with staff present |

URSim: run `scripts\ursim.ps1`, power on the robot at http://localhost:6080/vnc.html, then set `ROBOT_MODE=ursim` and `ROBOT_HOST=127.0.0.1`.

Real arm: copy `config/poses.example.yaml` to `config/poses.local.yaml`, fill it in with staff, and follow `docs/SAFETY_AND_LIMITATIONS.md`.

## How it works

```text
Browser mic and STOP button
        | WebSocket, POST /api/stop
Python server --- WebSocket --- Grok Voice
        |
Session: skill allowlist, confirmation check, stop handling
        |
Robot adapter: Mock | URSim | UR3e (ur_rtde)
```

Grok understands the request and runs the conversation. It cannot approve motion alone: `confirm_and_execute` also needs a clear yes in the user's transcribed words after the proposal, and each yes allows one motion. See `docs/ARCHITECTURE.md`.

## Results

`data/test_commands.csv` holds 24 synthetic Italian commands written for this project.

```powershell
.venv\Scripts\python.exe -m eval.run_eval baseline
.venv\Scripts\python.exe -m eval.run_eval grok
```

| System | Clear commands correct | Ambiguous or refused, no motion | Wrong skill proposed |
| --- | --- | --- | --- |
| Keyword baseline | 7/12 | 9/12 | 4 |
| Grok | not measured yet | not measured yet | not measured yet |

This compares typed text only. Speech recognition, latency and stop timing come from `runs/*.jsonl` during hardware tests. Replace "not measured yet" with real results only.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest -q
```

The tests use a mock arm, a fake controller and a scripted Grok event stream. They do not prove behaviour on URSim, the arm or the live API.

## Known limitations

- Three taught skills at first. Tray and push skills stay off until tested.
- The voice stop is not a safety function. See `docs/SAFETY_AND_LIMITATIONS.md`.
- Speech-triggered stop can fire on noise or a bystander.
- Confirmation and stop word lists are simple Italian and English rules.
- The arm has no camera, so "out of reach" means outside the approved skills.
- Latency depends on the network and the Grok service.

## Credits

`ur_rtde` by SDU Robotics (MIT). Grok Voice by xAI. Event handling was informed by xAI's `voice-agent-web` example. No code from that example is copied here.

# HANDOFF — GrokArm UR3e (Grok Hackathon Pavia, Track 04 Voice Control)

Written 2026-11-04 14:55 (Europe/Berlin). Minimum demo due **Thu 2026-11-05 16:00**.
Read this whole file before changing anything. Section 7 (boundaries) is binding.

## 1. Goal
Italian (and English) voice -> Grok Voice function calling -> a small set of predefined robot skills on a real UR3e.
Required: 3-5 predefined skills, confirmation before every motion, spoken result report, a stop that is always available.
Judged on: correct executions, latency, ambiguity handling, reliable stop.
Official stretch goals: sequences of skills, voice-recorded skills (human review required), more languages.
Out of scope: free trajectories from voice, bypassing confirmation. The robot has no camera of its own.

## 2. Addresses and environment
- Robot `n1-UR3e`: UR3e e-Series, serial 20195300651, PolyScope 5.11.1.108318, IP **192.168.7.21** (static).
- Laptop (Windows, Ethernet "以太网"): static **192.168.7.50/24**, no gateway. Pendant "Not connected to network" is cosmetic.
- Project: `C:\Users\13032\projects\grokarm-ur3e` (Windows, Python 3.12, venv `.venv`). Sandbox copy used by the previous agent: `/home/claude/grokarm-ur3e` (not shared; the laptop is the source of truth).
- App: `http://localhost:8000` (start with `scripts\run.ps1`).
- Teammate repo (separate app, NOT integrated): https://github.com/strinconegianluca/voice-arm . Its "deployed" URL is unknown; the user is asking the teammate. Camera page URL from teammate: unknown.
- Phone camera (planned): Android app "IP Webcam", `CAMERA_URL=http://<phone-ip>:8080`. Not set up yet.
- `.env` (do NOT paste secrets anywhere): `ROBOT_MODE=real`, `ROBOT_HOST=192.168.7.21`, `POSES_FILE=config/poses.local.yaml`, `ALLOW_REAL_MOTION=STAFF_APPROVED`, `VOICE_MODE=offline`, `XAI_API_KEY=` (empty: **no xAI key yet**; the user's Cursor key cannot be used for xAI).
- Pendant must be in **Remote Control** mode, robot powered on with brakes released, or the server fails to start ("Please enable remote control").
- Language of the user: Chinese. Reply in Chinese unless asked otherwise.

## 3. How to run
```powershell
cd C:\Users\13032\projects\grokarm-ur3e
.\.venv\Scripts\Activate.ps1
python -m pytest -q        # last result on the laptop: 161 passed, 1 skipped
.\scripts\run.ps1          # then open http://localhost:8000
python -m backend.robot_probe 192.168.7.21   # read-only diagnosis of the connection
python -m backend.report                      # safety/performance table from runs\*.jsonl
python -m backend.pose_offset ...             # set/adjust left/right poses numerically (no robot connection)
python -m backend.pose_teach ...              # record poses from the real arm (see README)
```
Only ONE program may control the robot at a time (the ur_rtde control interface runs a script on the controller). Never run the server together with raw URScript tools or the teammate's `ur_arm.py`/`dashboard.py`.

## 4. Implemented (verified by tests; hardware status noted)
| Area | What | State |
|---|---|---|
| Safety core | Confirmation FSM IDLE/PROPOSED/EXECUTING/STOPPING; a "yes" must appear in the user's OWN transcript after the proposal; proposal consumed on use; TTL 30 s; `time.perf_counter`; six stop paths; stop-on-any-speech during motion | tested; stop on real arm tried by user earlier |
| Unsafe backstop | `speech_rules.is_unsafe` blocks "ignore the stop / max speed / toward a person" independent of the model | tested |
| Skills | `go_to_safe_pose`, `point_left`, `point_right` (+ disabled lift/put_down/push in config) | real arm works |
| Sequences | 2-4 skills, one confirmation, stop between steps prevents next step | tested |
| Languages | Italian + English (`detect_language`, `phrases.py`, `label_en/done_en`) | tested; other languages not done |
| Motion timing | stall watchdog (`stall_s` 3 s) + hard cap (`skill_timeout_s` 120 s) instead of fixed 20 s; effective speed = `speed_rad_s` x pendant slider | user set 120 s; works |
| Path checks | joint-space path sampled with forward kinematics against `path:` limits in `config/skills.yaml`; controller `isJointsWithinSafetyLimits` when available; via points; recovery rule: after stop/failure only `go_to_safe_pose` may start | tested on fakes; limits may over-refuse, see Risks |
| Voice teaching + review | "ricorda questa posizione come X" -> pending item; only the local web page (`/api/taught/...`, 127.0.0.1 only) can approve; approved item becomes a skill `go_to_X`; stored in `config/taught.local.json` | tested; not exercised on the real arm |
| Metrics | `backend/report.py`: unconfirmed motions (must be 0), stop latency, speech-to-motion, success rate | works on real logs |
| Stop phrases | stop, basta, fermati, fermi, fermo, alt, "non muoverti", "don't move", ... | tested |
| Camera alignment (two steps) | `table_vision.py`, `vision_service.py`, `vision_cli.py`, session tools `propose_object_approach` / `propose_object_lower`; step 1 = 100 mm above object, step 2 = 20 mm, each its own proposal + yes; re-locate before step 2, refuse if object moved > 15 mm; ambiguity (two same-colour objects) refused; modes `OBJECT_MODE=off|dry|on` | **tested only with synthetic images and fake arm. Never run on a real arm or real camera.** Default off. |
| Eval | `eval/run_eval.py`, `data/test_commands.csv` (39 rows), baseline keyword parser | baseline only; `eval grok` needs key |

## 5. Code map (all in use)
`backend/`: `main.py` (Starlette app, Settings from .env, wiring), `session.py` (**safety core**, all motion/stop paths), `confirmation_fsm.py`, `speech_rules.py`, `phrases.py`, `tools.py` (Grok tool schemas, instructions, dispatch), `voice_gateway.py` (GrokLink + OfflineLink), `keyword_baseline.py`, `skill_registry.py` (config loading, Limits, PathLimits, ObjectLimits, Skill), `robot_adapter.py` (abstract), `ur3e_adapter.py` (ur_rtde moveJ, stall watchdog, checks), `mock_adapter.py`, `kinematics.py`, `pose_check.py`, `pose_teach.py`, `pose_offset.py`, `robot_probe.py`, `taught.py`, `event_log.py` (JSONL in `runs/`), `report.py`, `workspace.py`, `table_vision.py`, `vision_service.py`, `vision_cli.py`, `asgi.py`.
`config/`: `skills.yaml` (limits, `path:`, `object:`, skills; contains NO coordinates), `poses.local.yaml` (real poses, user-owned, do not overwrite), `poses.example.yaml`, `poses.ursim.yaml`, `taught.local.json` (user-owned), `vision/` (calibration.json, background.jpg after setup).
`frontend/index.html` (single page UI, to be redesigned), `eval/`, `data/`, `docs/` (ARCHITECTURE, DEMO_SCRIPT, HACKATHON_BRIEF, SAFETY_AND_LIMITATIONS), `scripts/` (run.ps1, setup.ps1, ursim.ps1, check_grok.py), `tests/` (16 files), `requirements.txt`, `requirements-vision.txt`, `.env.example`, `README.md`.

## 6. To do / to iterate (priority order)
1. **Verify on the real arm**: left, right, safe pose, stop mid-motion, a sequence, a voice-taught pose + web approval. Record failures with the `detail` text from the log.
2. **Get an xAI API key** (blocks Grok voice, `python -m eval.run_eval grok`, `scripts/check_grok.py`). Put it in `.env` only. Then set `VOICE_MODE=grok`, measure latency with `XAI_REASONING=none` vs `high`, try `XAI_LANGUAGE_HINT=auto` for English.
3. **Frontend redesign** (last, user asked for it after functions): big state banner (proposed/executing/stopped), always-visible red STOP, large proposal text, IT/EN toggle, collapsible log, taught-pose review panel. Use the UI/UX skills. Do not change safety logic when restyling; keep endpoint contracts (`/ws`, `/api/status`, `/api/taught`).
4. **Camera alignment bring-up** (only after 1): `pip install -r requirements-vision.txt`; phone on tripod; `vision_cli calibrate` (server stopped); `vision_cli background` (empty table); `vision_cli locate red` (no motion; check `runs/last_locate.jpg`); `OBJECT_MODE=dry`; then `on`. Set `object.object_height_mm` to the tallest object.
5. Teammate stack: user wants teammate items used where useful. Decided so far: adopt IDEAS only (homography + colour, FK fence, metrics, test phrases). Unresolved: the teammate's deployed web app. If it must be used, define precisely whether it is voice-only front end calling OUR `/ws`/tools, and keep OUR confirmation/stop as the only path to the robot.
6. Recovery after a stop: arm is at an unknown pose; only `go_to_safe_pose` is allowed (implemented). Consider UI hint.
7. More languages (German/Spanish/Chinese) via `phrases.py`, `speech_rules.py` word lists, `keyword_baseline.py`.
8. Voice-recorded multi-point skills ("record a path") are NOT implemented; only single taught poses.
9. Evaluate latency numbers for the judges; extend `data/test_commands.csv` (convert useful rows from teammate `test_commands_it.csv`; most of its skills do not exist here).
10. Optional: checkpoint confirmation before the reach limit (user idea) — not built; via points exist.

## 7. Boundaries (binding)
- Never remove or weaken: confirmation before every motion, the stop paths, TTL, "yes must come from the user's transcript", proposal consumed on use, unsafe backstop, `ALLOW_REAL_MOTION=STAFF_APPROVED` gate.
- The model must not receive coordinates, speeds or free trajectories as parameters. Camera steps are not proposable as plain skills (`camera_step_only`) and not usable in sequences.
- Do not run any second controller of the robot (teammate `ur_arm.py`, raw URScript on port 30001, pendant programs) while the server is connected.
- Never edit/overwrite user-owned files: `.env`, `config/poses.local.yaml`, `config/taught.local.json`, `runs/`. Before overwriting `config/skills.yaml`, diff it with the user's copy (user changed limits; `skill_timeout_s: 120`).
- Never put the API key in chat, code or git. `.env` is git-ignored.
- Approving taught poses is human-only, from the local page. No voice or model tool may approve.
- Do not start real motion tests yourself; the user runs them with a hand near the E-stop. The venue staff said no extra approval is needed for poses, but our confirmation and stop stay.
- Do not copy music/lyrics/copyrighted material; irrelevant here but note when scraping docs.

## 8. Known limits and risks
- Everything about camera alignment is unverified on hardware: calibration accuracy, lighting, phone shake, IK solution choice (`getInverseKinematics` near current q), `movej` path between waypoints (joint interpolation, not straight line), TCP configured on the pendant must be the same at calibration and at run time.
- `path:` limits (`min_radius_mm: 70`, `min_z_mm: -10`) were chosen conservatively; they can refuse a good pose. The refusal text names the leg and reason; `path.enabled: false` disables it.
- Reach near 180 deg base rotation (left to right) failed earlier; the user says time (timeout) was the cause and 120 s fixed it. Not independently confirmed with the controller log.
- Left/right/safe poses had been recorded identical at one point (0 motion); verify `config/poses.local.yaml` has three different poses.
- Effective speed depends on the pendant speed slider. A slow slider + far poses = long moves; keep poses close or use via points.
- Stop is a software `stopJ` (ur_rtde) plus controller behavior; the E-stop on the pendant is the real safety stop.
- Stop-on-any-speech may false-trigger on motor/room noise: `STOP_ON_ANY_SPEECH=false` to disable.
- Speech recognition is Grok-side (needs key); offline mode is typed text with keyword rules.
- Eval numbers so far are typed text only; no audio, latency or arm included.
- Single robot, single user, local only (127.0.0.1 for review endpoints). No auth.
- A Windows-only harmless `ConnectionResetError` warning appears in one test (fake dashboard thread).

## 9. Tests / software still to run or install
- On the laptop: `python -m pytest -q` (161 passed, 1 skipped = vision tests, need numpy/opencv).
- To install later: `pip install -r requirements-vision.txt` (opencv-python, numpy) — then re-run pytest (expect +7 vision tests).
- Android: "IP Webcam" app (or any app that serves `http://ip:8080/shot.jpg`); tripod/tape for the phone.
- xAI: API key; `python scripts/check_grok.py` once the key exists; `python -m eval.run_eval grok`.
- Optional: URSim (`scripts\ursim.ps1`, needs Docker) for offline arm tests; `URSim_polyscopex` folder exists on the laptop.
- Real-arm checklist to run in order: probe -> status ready:true -> left -> right -> safe -> stop mid-move -> sequence -> taught pose + approval -> report.

## 10. Teammate material reviewed (read-only, not integrated)
- `ur3e_vision_align.zip` / `VISION_PLAN.md`: homography calibration, background difference, colour naming, two-step approach, staged rollout. Ideas adopted in `table_vision.py`; their `ur_arm.py` not used.
- `ur3e_voice_addons.zip`: `metrics.py` (adapted to `report.py`), `dashboard.py`/`ur_arm.py` (conflict with our single controller; not used), `test_commands_it.csv` (mostly different skill names; a few stop phrases merged).
- `voice-arm` repo: separate Italian Grok Voice app. Weak confirmation (regex, no proposal id/TTL), URScript on 30001, its own phone page (HTTPS :8765) and Grok-vision pointing, STL forklift tool. Not used as safety path.

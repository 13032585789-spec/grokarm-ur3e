# GrokArm vision

This is the camera service for GrokArm UR3e. A phone looks down at the table. You say "point at the red cup", and the service works out which object you mean and returns its table position (X, Y in mm) in the robot base frame.

**The service never moves the robot and never connects to it.** The robot server (`backend/session.py` in the main GrokArm project) calls this service, builds its own proposal from the result (hover height, inverse kinematics, path checks) and still needs the user's spoken "yes" before any motion. Since the vision service is not a second controller, it can run at the same time as the robot server.

## How it works

1. **Frame.** The phone sends pictures, either from a browser page served by this service or from the Android "IP Webcam" app.
2. **Camera check.** The current picture is compared with the reference picture taken at calibration time. If the camera has moved more than 6 px, the service refuses.
3. **Detect.** The picture is compared with a photo of the empty table, and the differences become candidates. Each candidate gets a colour name, a pixel position and a robot XY from the calibration (a homography). Blobs that touch the image edge are dropped, which is how the arm is kept out.
4. **Understand.** The resolver decides which candidate you mean:
   - With an `XAI_API_KEY`, Grok vision gets the picture with numbered boxes plus your sentence. It may only answer with candidate ids: one match, ambiguous (with a clarifying question in your language), or none. It never supplies coordinates. Invalid ids, bad JSON or a network error fall back to the offline rules.
   - Without a key, offline rules use colour and position words (left, right, near, far, middle) in seven languages: Chinese, English, Italian, Spanish, French, German and Japanese.
5. **Checks.** The target must lie at least 10 mm inside the calibrated area. If the robot server passes `expect_mm` (to re-check right before moving), the result is refused when the object has moved more than `tolerance_mm`.

Possible results: `found`, `ambiguous`, `not_found`, `empty_table`, `outside_workspace`, `target_moved`, `camera_moved`, `camera_check_failed`, `no_frame`, `not_ready`. Every result includes a short spoken `message` in the requested language.

## Run

Python 3.12.

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env            # optional
python -m grokarm_vision
```

This starts two servers:

- **Operator page:** `http://127.0.0.1:8710/`. It only accepts requests from the laptop itself and is used for calibration, the background photo and test locates.
- **Phone page:** `https://<laptop-ip>:8711/`, printed at start-up. On the LAN it can only *receive* frames. Phone browsers only allow live video over HTTPS, so the service creates a self-signed certificate in `.certs/`. Accept the warning on the phone. If live video stays blocked, use the "send one photo" button.

The phone and the laptop must be on the same Wi-Fi. The robot stays on the wired network (192.168.7.x). If there is no shared Wi-Fi, turn on the phone's hotspot and connect the laptop's Wi-Fi to it.

To use IP Webcam instead of the browser page: `CAMERA_SOURCE=url` and `CAMERA_URL=http://<phone-ip>:8080`.

### Rehearse without a phone

```bash
python -m grokarm_vision                     # terminal 1
python -m grokarm_vision.sim --setup         # terminal 2: fake camera, auto-calibrated
```

Then open `http://127.0.0.1:8710/` and try "指向红色的", "the red one on the left" or "青い物を指して". Use `--objects red:350:120,blue:240:0` to change the scene (colour:x_mm:y_mm in the robot base frame).

## Setup at the table

1. Put the phone on a tripod above the table, in landscape, with the far edge of the table at the top of the picture. **Do not touch it after calibration.**
2. Tape 5–6 small cross marks across the workspace: corners plus the middle.
3. For each mark, freedrive the tool tip onto it and read X and Y in the **Base** frame on the pendant (mm). On the operator page, press "Add point", click the mark in the picture, and type in X and Y. With 5 or more points the page shows the leave-one-out error. A calibration with an error above 8 mm is refused, which usually means a point was mistyped. Exactly 4 points work, but the error cannot be measured.
4. Move the arm out of the picture, then press "Save calibration". This also stores the reference picture used to detect camera movement.
5. Clear the table and press "Capture background". Capture it again whenever the lighting changes.
6. Put objects on the table and use "Test locate" to check them. Nothing moves.

The TCP configured on the pendant must be the same during calibration and during the demo.

## Use from the robot server

```python
from grokarm_vision.client import VisionClient

vision = VisionClient()                                   # http://127.0.0.1:8710
r = await vision.locate("指向红色的杯子", lang="zh")
if r["ok"]:
    target_xy = r["target_mm"]       # the robot server adds its own hover height,
    say(r["message"])                # runs IK + path checks, proposes, waits for "yes"
elif r["status"] == "ambiguous":
    say(r["message"])                # ask; the next user sentence goes to locate() again
else:
    say(r["message"])                # refused; no proposal

# right before moving, re-check the object did not move:
again = await vision.locate(query, lang="zh", expect_mm=tuple(target_xy), tolerance_mm=15)
```

## Tests

```bash
python -m pytest -q
```

The tests use synthetic table images with a known mapping. They cover calibration accuracy and rejection, camera-shift detection, colour detection, all seven languages, ambiguity and position tie-breaks, the workspace fence, target-moved re-checks, the Grok resolver (mocked HTTP, invalid replies, fallback) and the HTTP endpoints, including the local-only operator API.

## Known limits

- Nothing has been tested yet with a real phone, real lighting or the real arm.
- Tall objects: the centre seen from an angle sits slightly off the base of the object (parallax). This is fine for hovering above it at 100+ mm. For lower moves, keep the camera as straight overhead as possible.
- Shadows and strong light changes can create false blobs. Capture the background again in the demo lighting.
- A plain table with no texture can make the camera-movement check fail (`camera_check_failed`). The tape marks help. `VISION_DRIFT_CHECK=false` disables the check, at your own risk.
- `XAI_VISION_MODEL` defaults to `grok-4.7`. Check the model name on your xAI account.

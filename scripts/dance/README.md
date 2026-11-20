# xArm 5 dance

Dancer video -> keypoints -> xArm 5 joint trajectory -> preview -> real arm. Videos, keypoints and trajectories go in
`data/dance/` (git-ignored: the source video is someone else's, keep it private).

| Step | Command (Windows, from the dev-pulse folder) |
|---|---|
| 1. Keypoints (MediaPipe, best for hand dances) | `.venv\Scripts\python.exe -m pip install mediapipe` then `.venv\Scripts\python.exe scripts\dance\extract_mediapipe.py data\dance\src.mp4 data\dance\kp_raw.json` |
| 2. Clean | `.venv\Scripts\python.exe scripts\dance\clean.py data\dance\kp_raw.json data\dance\kp_clean.json` |
| 3. Retarget | `.venv\Scripts\python.exe scripts\dance\retarget.py data\dance\kp_clean.json data\dance\traj.json --amp 1.0` |
| 4. Preview (needs ffmpeg for audio) | `.venv\Scripts\python.exe scripts\dance\preview.py data\dance\src.mp4 data\dance\kp_clean.json data\dance\traj.json data\dance\preview.mp4` |
| 5. Rehearsal, 3x slower | `.venv\Scripts\python.exe scripts\dance\play_xarm.py data\dance\traj.json --slow 3` |
| 6. With music | `.venv\Scripts\python.exe scripts\dance\play_xarm.py data\dance\traj.json --music data\dance\music.wav` |

`retarget.py` limits joint speeds (1.0-2.5 rad/s, the xArm allows 3.14) and checks every frame with the motion guard;
`play_xarm.py` checks again, goes slowly to the start pose, waits for Enter, then streams joints at 100 Hz in servo
mode and stops on Ctrl+C, a controller error or a lag > 0.25 rad. Nothing may be mounted on the flange (or set
`gripper` in robot_xarm5.yaml so the guard knows about it).

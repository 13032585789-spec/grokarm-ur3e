# UFactory xArm 5

The project runs on the UR3e (`config/robot.yaml`) or on the xArm 5 (`config/robot_xarm5.yaml`). One line in `.env` picks the arm:

```
ROBOT_CONFIG=robot_xarm5.yaml
ROBOT_HOST=192.168.1.xxx        # xArm control box IP
```

Remove the `ROBOT_CONFIG` line to go back to the UR3e. `ROBOT_MODE=sim` runs without a robot. URSim only simulates UR arms.

## What changed for the xArm

| Part | File |
|---|---|
| Kinematics, 5 joints (UFactory DH: zero pose at 207, 0, 112 mm, tool down) | `backend/app/robot/kinematics.py` |
| Analytic IK, up to 4 branches, ~0.3 ms | `backend/app/robot/xarm_ik.py` |
| Driver over the xArm Python SDK | `backend/app/robot/xarm.py` |
| Joint limits J1 ±360, J2 −118…120, J3 −225…11, J4 −97…180, J5 ±360 deg | `config/robot_xarm5.yaml` |
| Placeholder poses, generated with the IK (record them on the arm) | `config/poses_xarm5.yaml` |

Every motion is still planned with our own kinematics and checked by the motion guard, then sent as joint moves.
Straight-line moves are cut into 5 mm joint steps: the controller's own linear move only accepts a tool pointing straight down on an xArm 5.
Controller errors are never cleared by the app.

## 5 joints: what it means for grabbing

The arm is planar after the base: the tool axis always lies in the vertical plane through the base axis. With the
current semicircle gripper (beam perpendicular to the flange, flange held level) the ring can only approach a cup
radially, toward or away from the base.

Simulated reach of the cup grasp from `home` (grasp planner, 55 mm cup, estimated xArm link radii, 3 cm table clearance, UR mesh model off):

| Arm | Cup distance from the base axis |
|---|---|
| UR3e | 125–500 mm (500 = the configured reach cap) |
| xArm 5, current gripper | 125–425 mm |
| xArm 5, tool pointing down (gripper on the flange axis) | 175–675 mm flange positions are valid |

The current gripper does not use the xArm's reach: holding the flange level puts the wrist pitch (J4) at its −97° limit
or the wrist into the table beyond ~425 mm. A gripper whose ring sits on the flange axis (tool pointing down, ring mouth sideways) would.

## First start on the xArm

1. `.venv\Scripts\python.exe -m pip install xarm-python-sdk`
2. Set `ROBOT_CONFIG` and `ROBOT_HOST` in `.env`.
3. Gripper direction: pose the arm with the flange level and the ring hanging down, run `scripts\beam_axis.py --write`.
4. Record `home` and `attesa`: `scripts\record_pose.py home --mode real` (the generated poses are placeholders).
5. `scripts\reach_map.py`, then `start_real.bat`, hand on the E-stop.

## Camera plane

`data/plane.json` maps the four orange tapes to the UR3e base frame. If the xArm base stands somewhere else, the tape
positions in the robot frame change: measure the four tapes again from the xArm base before grabbing.

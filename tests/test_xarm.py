"""xArm 5 support: kinematics, IK, guard limits, config, straight-line steps, grasp planning (no hardware)."""
import math
import os

import numpy as np
import pytest

from app.robot.kinematics import Kinematics, model_of
from app.robot.ur_ik import ik_all


def test_zero_pose_matches_factory():
    k = Kinematics("xArm5")
    T = k.frames([0] * 5)[-1]
    assert np.allclose(T[:3, 3], [0.207, 0, 0.112], atol=1e-4)
    assert np.allclose(T[:3, 2], [0, 0, -1], atol=1e-6)     # tool straight down
    assert model_of("xArm 5") == "xArm5" and model_of("UR3 (e-Series)") == "UR3e"


def test_ik_roundtrip():
    k = Kinematics("xArm5")
    rng = np.random.default_rng(0)
    for _ in range(200):
        q = rng.uniform([-3, -2, -3.8, -1.6, -3], [3, 2, 0.1, 3, 3])
        sols = ik_all(k, k.fk(q), q)
        assert any(np.max(np.abs(np.arctan2(np.sin(s - q), np.cos(s - q)))) < 1e-3 for s in sols)


def test_ik_refuses_tool_axis_out_of_plane():
    k = Kinematics("xArm5")
    T = np.eye(4)
    T[:3, :3] = [[0, 0, 1], [1, 0, 0], [0, 1, 0]]   # tool axis along +x while the target lies on +y
    T[:3, 3] = [0.0, 0.3, 0.2]
    assert ik_all(k, T) == []


def _settings():
    os.environ["ROBOT_CONFIG"] = "robot_xarm5.yaml"
    try:
        from app.config import load_settings
        return load_settings("sim", env_file=None)
    finally:
        os.environ.pop("ROBOT_CONFIG", None)


def test_config_and_asymmetric_limits():
    s = _settings()
    assert len(s.poses["home"]["joints"]) == 5
    from app.skills.motion_guard import guard_from_settings
    g = guard_from_settings(s)
    assert g.mesh is None
    q = np.array(s.poses["home"]["joints"], float)
    assert g.margins(q)["limite_giunto"] > 0
    q[2] = 0.5                                       # elbow past +11 deg
    assert g.margins(q)["limite_giunto"] < 0


def test_movel_steps_stay_on_the_line():
    from app.robot.xarm import movel_steps
    k = Kinematics("xArm5")
    qa = np.array([0.0, -0.6, -0.5, 1.1, 0.0])
    Ta = k.frames(qa)[-1]
    Tb = Ta.copy()
    Tb[:3, 3] += [0.06, 0.0, -0.04]
    qb = min(ik_all(k, Tb, qa), key=lambda s: float(np.max(np.abs(s - qa))))
    pts = movel_steps(k, qa, qb, 0.005)
    d = Tb[:3, 3] - Ta[:3, 3]
    for p in pts:
        x = k.frames(p)[-1][:3, 3] - Ta[:3, 3]
        assert np.linalg.norm(x - d * (x @ d) / (d @ d)) < 5e-4


@pytest.mark.parametrize("az", [0, 60, 135, -90])
def test_grasp_plans_all_around(az):
    s = _settings()
    s.robot["gripper"]["offset_axis_flange"] = [0, 1, 0]
    from app.skills.grasp import plan_grasp
    from app.skills.motion_guard import guard_from_settings
    xy = (0.3 * math.cos(math.radians(az)), 0.3 * math.sin(math.radians(az)))
    p = plan_grasp(guard_from_settings(s), s, s.poses["home"]["joints"], xy)
    assert all(len(m.joints) == 5 for m in p.motion if m.joints)

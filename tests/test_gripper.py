"""Printed semicircle gripper: body collision model and the pick-and-lift planner."""
import numpy as np
import pytest

from app.config import load_settings
from app.robot.ur import urscript
from app.skills.cartesian import Planner
from app.skills.registry import SkillError

Q0 = [0.0, -1.57, 1.2, -1.2, -1.57, 0.0]


@pytest.fixture
def planner():
    p = Planner(load_settings("sim", env_file=None))
    p.grip["offset_axis_flange"] = [0, -1, 0]
    return p


def _ring(p, q):
    F = p.kin.frames(q)[-1]
    R = F[:3, :3]
    return F[:3, 3] + R @ np.array([0, 0, p.grip["ring_axial_m"]]) + R @ np.array([0, -1, 0]) * p.grip["ring_offset_m"]


@pytest.mark.parametrize("xy", [(0.3, 0.0), (0.0, -0.3), (0.38, -0.1)])
def test_grasp_puts_the_ring_around_the_cup_and_lifts(planner, xy):
    plan = planner.grasp(Q0, xy, others=[(xy[0] + 0.12, xy[1])])
    seat, lift = plan.motion[2].joints, plan.motion[-1].joints
    assert np.allclose(_ring(planner, seat)[:2], xy, atol=0.002)
    assert 0.003 < _ring(planner, seat)[2] < 0.02
    assert _ring(planner, lift)[2] - _ring(planner, seat)[2] == pytest.approx(0.08, abs=0.002)
    assert len(planner.place(lift, plan.place).motion) == 4


def test_ring_into_the_table_is_refused(planner):
    plan = planner.grasp(Q0, (0.3, 0.0))
    with pytest.raises(SkillError):
        planner._check_tool(plan.motion[2].joints, 0.02)


def test_too_wide_cup_is_refused(planner):
    planner.gsp["cup_bottom_diameter_m"] = 0.06
    with pytest.raises(SkillError, match="anello_troppo_stretto"):
        planner.grasp(Q0, (0.3, 0.0))


def test_program_sets_the_gripper_payload(planner):
    plan = planner.grasp(Q0, (0.3, 0.0))
    script = urscript(plan.motion, "voce_prendi", planner.s.robot["gripper"])
    assert "set_payload(0.08000" in script.splitlines()[1]

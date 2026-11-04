"""Allowlist of skills, and loading of approved poses."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Skill:
    skill_id: str
    label_it: str
    done_it: str
    description: str
    mock_duration_s: float


@dataclass(frozen=True)
class Limits:
    speed_rad_s: float
    accel_rad_s2: float
    stop_decel_rad_s2: float
    skill_timeout_s: float
    joint_tolerance_rad: float
    start_pose_tolerance_rad: float


class SkillRegistry:
    def __init__(self, skills: dict[str, Skill], limits: Limits):
        self._skills = skills
        self.limits = limits

    @classmethod
    def load(cls, path: str | Path) -> "SkillRegistry":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        limits = Limits(**data["limits"])
        skills = {
            sid: Skill(
                skill_id=sid,
                label_it=s["label_it"],
                done_it=s["done_it"],
                description=s["description"],
                mock_duration_s=float(s["mock_duration_s"]),
            )
            for sid, s in data["skills"].items()
            if s.get("enabled")
        }
        if not 3 <= len(skills) <= 5:
            raise ConfigError(f"Track 04 expects 3-5 skills, found {len(skills)}")
        return cls(skills, limits)

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def ids(self) -> list[str]:
        return list(self._skills)

    def all(self) -> list[Skill]:
        return list(self._skills.values())


def _check_joints(q, where: str) -> list[float]:
    if not isinstance(q, list) or len(q) != 6 or not all(isinstance(v, (int, float)) for v in q):
        raise ConfigError(f"{where}: expected 6 joint values in radians")
    return [float(v) for v in q]


@dataclass(frozen=True)
class PoseBook:
    target: str
    approved_by: str
    known_poses: dict[str, list[float]]
    waypoints: dict[str, list[list[float]]]

    @classmethod
    def load(cls, path: str | Path, skill_ids: list[str], expected_target: str) -> "PoseBook":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        target = data.get("target")
        if target != expected_target:
            raise ConfigError(f"{path}: target is {target!r}, this mode needs {expected_target!r}")
        approved_by = (data.get("approved_by") or "").strip()
        if not approved_by:
            raise ConfigError(f"{path}: approved_by is empty, poses are not approved")
        known = {
            name: _check_joints(q, f"known_poses.{name}")
            for name, q in (data.get("known_poses") or {}).items()
        }
        if not known:
            raise ConfigError(f"{path}: no known_poses")
        waypoints = {}
        for sid in skill_ids:
            points = ((data.get("skills") or {}).get(sid) or {}).get("waypoints") or []
            if not points:
                raise ConfigError(f"{path}: enabled skill {sid} has no waypoints")
            waypoints[sid] = [_check_joints(q, f"skills.{sid}") for q in points]
        return cls(target, approved_by, known, waypoints)

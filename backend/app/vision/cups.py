"""Coloured paper cups seen by the camera -> which workspace zone each one is in.

Pure colour segmentation (HSV), no background photo needed. The image is split
into the configured zones by vertical lines, so the arm can point at a cup with
the existing taught `indica` poses: no new motion, no coordinates from the model.
Read-only: never moves the robot.
"""

from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

# OpenCV hue is 0..179
COLOURS: dict[str, list[tuple[int, int]]] = {
    "red": [(0, 7), (170, 179)],
    "orange": [(8, 19)],
    "yellow": [(20, 34)],
    "green": [(35, 85)],
    "blue": [(90, 128)],
    "purple": [(129, 169)],
}
BGR = {"red": (40, 40, 230), "orange": (0, 140, 255), "yellow": (0, 220, 240), "green": (60, 200, 60),
       "blue": (230, 120, 30), "purple": (200, 60, 170)}

COLOUR_WORDS: dict[str, list[str]] = {
    "red": ["red", "rosso", "rossa", "rossi", "rojo", "roja", "rouge", "rot", "rote", "roten", "红", "紅", "赤"],
    "orange": ["orange", "arancione", "arancio", "naranja", "orangen", "橙", "橘", "オレンジ"],
    "yellow": ["yellow", "giallo", "gialla", "amarillo", "amarilla", "jaune", "gelb", "gelbe", "gelben", "黄", "黃"],
    "green": ["green", "verde", "vert", "verte", "grun", "grune", "grunen", "绿", "綠", "緑"],
    "blue": ["blue", "blu", "azzurro", "azzurra", "azul", "bleu", "bleue", "blau", "blaue", "blauen", "蓝", "藍", "青"],
    "purple": ["purple", "viola", "morado", "morada", "violet", "violette", "lila", "紫"],
}
_CJK = "\u3040-\u30ff\u3400-\u9fff"


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", str(text)).lower()
    return "".join("".join(x for x in unicodedata.normalize("NFKD", c) if not unicodedata.combining(x))
                   if c < "\u0250" else c for c in t)


def colour_of(text: str | None) -> str | None:
    """'il bicchiere rosso' -> 'red'; '蓝色的纸杯' -> 'blue'. None if no (or more than one) colour is named."""
    if not text:
        return None
    t = _norm(text)
    words = set("".join(c if c.isalnum() else " " for c in t).split())
    found = set()
    for canon, names in COLOUR_WORDS.items():
        for n in names:
            if (n in t) if any("\u3040" <= ch <= "\u9fff" or "\u30a0" <= ch <= "\u30ff" for ch in n) else (n in words):
                found.add(canon)
    return found.pop() if len(found) == 1 else None


@dataclass
class Cup:
    colour: str
    px: tuple[float, float]
    bbox: tuple[int, int, int, int]
    area_frac: float
    zone: str | None

    def public(self) -> dict[str, Any]:
        return {"colore": self.colour, "zona": self.zone, "px": [round(self.px[0]), round(self.px[1])],
                "bbox": list(self.bbox), "area_frac": round(self.area_frac, 4)}


def zone_bounds(zones: list[str], cfg: dict[str, Any]) -> list[tuple[str, float, float]]:
    """Zones left-to-right *as seen in the image*, as (zone, x0, x1) fractions of the width."""
    order = list(cfg.get("image_zone_order") or zones)
    cuts = list(cfg.get("zone_cuts") or [i / len(order) for i in range(1, len(order))])
    edges = [0.0] + [float(c) for c in cuts] + [1.0]
    return [(z, edges[i], edges[i + 1]) for i, z in enumerate(order)]


def find_cups(image: np.ndarray, zones: list[str], cfg: dict[str, Any]) -> list[Cup]:
    h, w = image.shape[:2]
    x0, y0, x1, y1 = cfg.get("roi") or [0.0, 0.0, 1.0, 1.0]
    rx0, ry0, rx1, ry1 = int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)
    roi = image[ry0:ry1, rx0:rx1]
    hsv = cv2.cvtColor(cv2.GaussianBlur(roi, (7, 7), 0), cv2.COLOR_BGR2HSV)
    s_min, v_min = int(cfg.get("min_saturation", 90)), int(cfg.get("min_value", 60))
    min_area = float(cfg.get("min_area_frac", 0.002)) * w * h
    max_area = float(cfg.get("max_area_frac", 0.25)) * w * h
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    bounds = zone_bounds(zones, cfg)
    cups: list[Cup] = []
    for colour, ranges in COLOURS.items():
        mask = np.zeros(hsv.shape[:2], np.uint8)
        for lo, hi in ranges:
            mask |= cv2.inRange(hsv, (lo, s_min, v_min), (hi, 255, 255))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        n, _, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for i in range(1, n):
            bx, by, bw, bh, area = (int(v) for v in stats[i])
            if not (min_area <= area <= max_area):
                continue
            if bw / max(bh, 1) > 4 or bh / max(bw, 1) > 4:      # stripes, cables, table edges
                continue
            cx, cy = float(cents[i][0]) + rx0, float(cents[i][1]) + ry0
            fx = cx / w
            zone = next((z for z, a, b in bounds if a <= fx < b), bounds[-1][0])
            cups.append(Cup(colour, (cx, cy), (bx + rx0, by + ry0, bw, bh), area / (w * h), zone))
    cups.sort(key=lambda c: c.px[0])
    return cups


def annotate(image: np.ndarray, cups: list[Cup], zones: list[str], cfg: dict[str, Any],
             labels: dict[str, str] | None = None) -> np.ndarray:
    out = image.copy()
    h, w = out.shape[:2]
    for z, a, b in zone_bounds(zones, cfg):
        if a > 0:
            cv2.line(out, (int(a * w), 0), (int(a * w), h), (200, 200, 200), 1, cv2.LINE_AA)
        name = (labels or {}).get(z, z)
        cv2.putText(out, name, (int(a * w) + 8, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (230, 230, 230), 2, cv2.LINE_AA)
    x0, y0, x1, y1 = cfg.get("roi") or [0.0, 0.0, 1.0, 1.0]
    if (x0, y0, x1, y1) != (0.0, 0.0, 1.0, 1.0):
        cv2.rectangle(out, (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h)), (120, 120, 120), 1)
    for c in cups:
        x, y, bw, bh = c.bbox
        col = BGR.get(c.colour, (255, 255, 255))
        cv2.rectangle(out, (x, y), (x + bw, y + bh), col, 3)
        cv2.putText(out, c.colour, (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2, cv2.LINE_AA)
    return out


class CupFinder:
    def __init__(self, zones: list[str], cfg: dict[str, Any], labels: dict[str, str] | None = None) -> None:
        self.zones, self.cfg, self.labels = zones, cfg, labels or {}
        self.last: dict[str, Any] | None = None
        self.last_jpeg: bytes | None = None

    def scan(self, frame: Any) -> dict[str, Any]:
        t0 = time.perf_counter()
        cups = find_cups(frame.image, self.zones, self.cfg)
        ok, buf = cv2.imencode(".jpg", annotate(frame.image, cups, self.zones, self.cfg, self.labels),
                               [cv2.IMWRITE_JPEG_QUALITY, 80])
        self.last_jpeg = buf.tobytes() if ok else None
        self.last = {"cups": [c.public() for c in cups], "frame_id": frame.frame_id, "at": time.time(),
                     "ms": round((time.perf_counter() - t0) * 1000, 1)}
        return self.last

"""Bounded rolling net cue with warmup, player and whole-image motion checks."""
from collections import deque

import numpy as np
from PIL import Image

from core.vision import MotionEvidence
from .geometry import box_overlap, inside_polygon


class NetMotion:
    def __init__(self, polygon, source_size, history=20, warmup=5, threshold=18):
        if not 2 <= warmup <= history <= 100 or not 0 < threshold <= 255:
            raise ValueError("Invalid rolling baseline settings")
        self.polygon, self.source_size = polygon, source_size
        self.baseline = deque(maxlen=history)
        self.warmup, self.threshold = warmup, threshold
        width, height = source_size
        self.mask = np.array([[inside_polygon(((x+.5)*width/96, (y+.5)*height/64), polygon)
                               for x in range(96)] for y in range(64)], dtype=bool)

    def update(self, image, detections=()):
        if image.size != self.source_size:
            raise ValueError("Motion baseline resolution changed; construct a new baseline")
        gray = np.asarray(image.convert("L").resize((96, 64), Image.Resampling.BILINEAR), dtype=np.float32)
        flags = []
        if not self.mask.any():
            return MotionEvidence(flags=["roi_unavailable"])
        if any(d.kind == "player" and box_overlap(d.bbox, self.polygon) for d in detections):
            flags.append("player_overlap")
        count = len(self.baseline)
        net = global_fraction = None
        if count:
            reference = np.median(np.stack(self.baseline), axis=0)
            changed = np.abs(gray-reference) >= self.threshold
            net, global_fraction = float(changed[self.mask].mean()), float(changed.mean())
            if global_fraction >= .4:
                flags.append("camera_shake_or_global_motion")
        if count < self.warmup:
            flags.append("baseline_warming")
        # Do not train motion/occluding players into a clean reference; reset at each stream epoch.
        if "player_overlap" not in flags and "camera_shake_or_global_motion" not in flags and (net is None or net < .15):
            self.baseline.append(gray)
        return MotionEvidence(net_changed_fraction=net, global_changed_fraction=global_fraction,
                              flags=flags, baseline_frames=count)

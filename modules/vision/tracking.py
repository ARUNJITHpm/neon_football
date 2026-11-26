"""One bounded ball track per view, explicit short-gap predictions and ambiguity."""
import hashlib
import math

from core.vision import TrackPoint


class BallTracker:
    def __init__(self, settings):
        self.settings = settings
        self.last = self.previous_observation = self.observation = None
        self.start = None
        self.track_id = None

    def clear(self):
        self.last = self.previous_observation = self.observation = None
        self.start = self.track_id = None

    def _velocity(self):
        if not self.observation or not self.previous_observation:
            return (0.0, 0.0)
        dt = self.observation.occurred_seconds-self.previous_observation.occurred_seconds
        return tuple((b-a)/dt for a, b in zip(self.previous_observation.center_px, self.observation.center_px))

    def update(self, frame):
        if self.observation and frame.occurred_seconds-self.observation.occurred_seconds > self.settings.max_prediction_seconds:
            self.clear()
        balls = [d for d in frame.detections if d.kind == "ball" and d.score >= self.settings.min_ball_score]
        if self.observation:
            dt = frame.occurred_seconds-self.observation.occurred_seconds
            vx, vy = self._velocity()
            target = (self.observation.center_px[0]+vx*dt, self.observation.center_px[1]+vy*dt)
            gate = self.settings.association_slack_px + self.settings.association_speed_px_per_second*dt
            choices = sorted(((math.hypot((d.bbox[0]+d.bbox[2])/2-target[0], (d.bbox[1]+d.bbox[3])/2-target[1]), i, d)
                              for i, d in enumerate(balls)), key=lambda row: (row[0], -row[2].score, row[1]))
            choices = [row for row in choices if row[0] <= gate]
        else:
            choices = [(0, i, d) for i, d in sorted(enumerate(balls), key=lambda row: (-row[1].score, row[0]))]
        if choices:
            detection = choices[0][2]
            if self.start is None:
                self.start = frame.occurred_seconds
                key = f"{frame.session_id}:{frame.match_id}:{frame.camera_id}:{frame.boot_id}:{frame.sequence}"
                self.track_id = hashlib.sha256(key.encode()).hexdigest()[:24]
            flags = ["association_ambiguous"] if len(choices) > 1 else []
            point = TrackPoint(track_id=self.track_id, occurred_seconds=frame.occurred_seconds,
                age_seconds=frame.occurred_seconds-self.start, last_observed_seconds=frame.occurred_seconds,
                observed=True, center_px=((detection.bbox[0]+detection.bbox[2])/2, (detection.bbox[1]+detection.bbox[3])/2),
                bbox=detection.bbox, uncertainty_px=detection.uncertainty_px, score=detection.score,
                depth=detection.depth, flags=flags)
            self.previous_observation, self.observation, self.last = self.observation, point, point
            return point
        if not self.observation:
            return None
        dt = frame.occurred_seconds-self.observation.occurred_seconds
        vx, vy = self._velocity()
        dx, dy = vx*dt, vy*dt
        box = self.observation.bbox
        depth = None
        a, b = self.previous_observation, self.observation
        if (a and a.depth and b.depth and a.depth.observed and b.depth.observed and a.depth.synchronized and b.depth.synchronized
                and (a.depth.calibration_id, a.depth.clock_domain, a.depth.method) == (b.depth.calibration_id, b.depth.clock_domain, b.depth.method)):
            elapsed = b.occurred_seconds-a.occurred_seconds
            coordinates = {name: getattr(b.depth, name)+(getattr(b.depth, name)-getattr(a.depth, name))*dt/elapsed
                           for name in ("x_m", "y_m", "z_m")}
            depth = b.depth.model_copy(update={**coordinates, "observed": False,
                "uncertainty_m": tuple(u+self.settings.prediction_uncertainty_m_per_second*dt for u in b.depth.uncertainty_m)})
        self.last = TrackPoint(track_id=self.track_id, occurred_seconds=frame.occurred_seconds,
            age_seconds=frame.occurred_seconds-self.start, last_observed_seconds=b.occurred_seconds, observed=False,
            center_px=(b.center_px[0]+dx, b.center_px[1]+dy), bbox=(box[0]+dx, box[1]+dy, box[2]+dx, box[3]+dy),
            uncertainty_px=b.uncertainty_px+self.settings.prediction_uncertainty_px_per_second*dt,
            score=b.score, depth=depth, flags=["prediction_only"])
        return self.last

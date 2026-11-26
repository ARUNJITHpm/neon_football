"""Conservative evidence candidates, isolated from match scoring and confirmation."""
import hashlib
import math

from core.vision import VisionCandidate, VisionFrame, VisionSettings
from .geometry import box_overlap, inside_polygon, opening_contains, opening_possible, valid_calibration
from .tracking import BallTracker


class ViewState:
    def __init__(self, settings):
        self.tracker = BallTracker(settings)
        self.identity = None
        self.sequence = self.time = None
        self.previous = self.front = None
        self.front_sequence = None
        self.front_flags = []
        self.front_timing_uncertainty = None
        self.emitted_track = None
        self.region_inside = False
        self.net_active = False


class VisionEngine:
    def __init__(self, settings: VisionSettings, model_version):
        self.settings = VisionSettings.model_validate(settings.model_dump())
        self.model_version = model_version
        self.views = {v.camera_id: v for v in self.settings.views}
        self.states = {v.camera_id: ViewState(self.settings) for v in self.settings.views}

    def process(self, frame: VisionFrame):
        frame = VisionFrame.model_validate(frame.model_dump())
        view = self.views.get(frame.camera_id)
        if view is None:
            raise ValueError("Frame camera has no configured goal view")
        state = self.states[frame.camera_id]
        identity = (frame.session_id, frame.match_id, frame.boot_id, frame.clock_domain, frame.width, frame.height, frame.evidence)
        flags = list(frame.motion.flags)
        if any(d.kind == "player" and box_overlap(d.bbox, view.calibration.goal_roi) for d in frame.detections):
            flags.append("player_overlap")
        if state.identity != identity:
            if state.identity is not None:
                flags.append("stream_epoch_reset")
            state = self.states[frame.camera_id] = ViewState(self.settings)
            state.identity = identity
        if state.sequence is not None and (frame.sequence <= state.sequence or frame.occurred_seconds <= state.time):
            raise ValueError("Vision sequence/time regressed within one stream epoch")
        state.sequence, state.time = frame.sequence, frame.occurred_seconds
        calibration_errors = valid_calibration(view, frame.width, frame.height)
        if frame.evidence == "venue" and view.calibration_evidence != "venue":
            calibration_errors.append("calibration_evidence_not_venue")
        flags += calibration_errors
        if frame.received_seconds-frame.occurred_seconds > self.settings.max_queue_age_seconds:
            flags.append("stale_frame")
        if frame.timing_uncertainty_seconds is None or frame.timing_uncertainty_seconds > self.settings.max_timing_uncertainty_seconds:
            flags.append("timing_unverified")
        if calibration_errors or "stale_frame" in flags:
            state.tracker.clear()
            state.previous = state.front = None
            state.emitted_track = None
            state.region_inside = False
            state.net_active = False
            return dict(track=None, candidates=[], flags=sorted(set(flags)), calibration_valid=not calibration_errors)
        point = state.tracker.update(frame)
        candidates = []

        def emit(quality, reason, when, support, extra_flags=(), interval=None):
            track_id = point.track_id if point else None
            key = f"{frame.session_id}:{frame.match_id}:{frame.camera_id}:{frame.boot_id}:{frame.sequence}:{quality}"
            candidates.append(VisionCandidate(event_id=hashlib.sha256(key.encode()).hexdigest(),
                session_id=frame.session_id, match_id=frame.match_id, camera_id=frame.camera_id, goal_end=view.goal_end,
                track_id=track_id, occurred_seconds=max(0, when), emitted_seconds=frame.received_seconds,
                timing_uncertainty_seconds=(frame.timing_uncertainty_seconds if interval is None else
                    None if frame.timing_uncertainty_seconds is None or state.front_timing_uncertainty is None else
                    max(frame.timing_uncertainty_seconds, state.front_timing_uncertainty)+interval[1]-interval[0]),
                calibration_version=view.calibration.version, model_version=self.model_version,
                configuration_version=self.settings.version, quality=quality, evidence=frame.evidence,
                reasons=[reason], flags=sorted(set(flags+list(extra_flags)+(point.flags if point else []))),
                clip_path=frame.clip_path, supporting_sequences=support, crossing_interval_seconds=interval))

        if point:
            previous = state.previous if state.previous and state.previous.track_id == point.track_id else None
            if state.front and state.front.track_id != point.track_id:
                state.front = None
                state.emitted_track = None
            depth = point.depth
            depth_valid = (depth is not None and depth.calibration_id == view.depth_calibration_id and
                           depth.clock_domain == frame.clock_domain and depth.synchronized)
            if depth is not None and not depth_valid:
                flags.append("depth_calibration_or_clock_unverified")
            radius = view.ball_radius_m+view.plane_margin_m
            if depth_valid:
                # A new fully pitch-side observed sample rearms this track after a rebound.
                if point.observed and depth.observed and depth.z_m+depth.uncertainty_m[2] <= -radius:
                    state.front = point
                    state.front_sequence = frame.sequence
                    state.front_flags = list(flags)
                    state.front_timing_uncertainty = frame.timing_uncertainty_seconds
                    state.emitted_track = None
                front = state.front
                if front and front.depth.method == depth.method and frame.occurred_seconds-front.occurred_seconds <= self.settings.max_crossing_gap_seconds:
                    dt = point.occurred_seconds-front.occurred_seconds
                    dz = depth.z_m-front.depth.z_m
                    inward = dt > 0 and dz/dt >= self.settings.min_inward_speed_m_per_second
                    if (inward and depth.z_m+depth.uncertainty_m[2] >= radius and state.emitted_track != point.track_id
                            and opening_possible(front.depth, view) and opening_possible(depth, view)):
                        clear = depth.z_m-depth.uncertainty_m[2] >= radius
                        opening = opening_contains(front.depth, view) and opening_contains(depth, view)
                        ratio = min(1, max(0, (radius-front.depth.z_m)/dz))
                        when = front.occurred_seconds + ratio*dt
                        observed = front.observed and front.depth.observed and point.observed and depth.observed
                        reliable = observed and not any(f in ("association_ambiguous", "timing_unverified", "camera_shake_or_global_motion", "player_overlap")
                                                        for f in flags+state.front_flags+front.flags+point.flags)
                        quality = "observed_crossing" if clear and opening and reliable else "predicted_crossing" if not observed else "boundary_uncertain"
                        emit(quality, "inward sphere crosses the goal plane" if quality == "observed_crossing" else "crossing needs additional observed/geometry/quality evidence",
                             when, [state.front_sequence, frame.sequence], state.front_flags+front.flags,
                             (front.occurred_seconds, point.occurred_seconds))
                        state.emitted_track = point.track_id
            # Image-only opening entry is useful review evidence, never airborne depth truth.
            inside = inside_polygon(point.center_px, view.calibration.goal_roi)
            if not depth_valid and previous and inside and not state.region_inside:
                direction = view.image_inward_direction
                dt = point.occurred_seconds-previous.occurred_seconds
                speed = None if direction is None else sum((b-a)*d for a, b, d in zip(previous.center_px, point.center_px, direction))/math.hypot(*direction)/dt
                if speed is None or speed >= self.settings.min_image_inward_speed_px_per_second:
                    emit("depth_ambiguous", "image-space goal-opening entry has no verified airborne depth", point.occurred_seconds,
                         [frame.sequence], ["no_depth_evidence"])
            state.region_inside = inside
            state.previous = point
        else:
            state.previous = state.front = None
            state.emitted_track = None
            state.region_inside = False
        # Net motion is a corroboration cue; player/global motion and baseline warmup suppress it.
        motion = frame.motion.net_changed_fraction
        active = motion is not None and motion >= self.settings.net_motion_fraction
        blocked = any(f in flags for f in ("baseline_warming", "roi_unavailable", "camera_shake_or_global_motion", "player_overlap"))
        if active and not blocked and not state.net_active and not candidates:
            emit("net_motion_only", "net movement without sufficient crossing evidence", frame.occurred_seconds, [frame.sequence])
        state.net_active = active and not blocked
        return dict(track=point.model_dump(mode="json") if point else None,
                    candidates=[c.model_dump(mode="json") for c in candidates], flags=sorted(set(flags)), calibration_valid=True)

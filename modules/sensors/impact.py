"""Inspectable causal impact baseline. Net/frame motion cannot establish a valid goal."""
from collections import Counter, deque
import hashlib
import math
from statistics import fmean
from core.sensors import SensorImpact, SensorSettings


def norm(xyz):
    return math.sqrt(sum(v*v for v in xyz))


class Unit:
    def __init__(self, settings, sample):
        self.identity = (sample.device_id, sample.boot_id, sample.transport_epoch)
        self.end = sample.goal_end
        self.history = {r: deque(maxlen=settings.max_history_samples) for r in ("net", "frame")}
        self.baseline, self.baseline_health = {}, {}
        self.pending = None
        self.last_trigger = -math.inf


class ImpactEngine:
    def __init__(self, settings):
        self.settings = SensorSettings.model_validate(settings.model_dump())
        self.units = {}
        self.counters = Counter()

    def invalidate(self, device_id):
        old = self.units.pop(device_id, None)
        if old and old.pending:
            self.counters["cancelled_windows"] += 1

    def _baseline(self, unit, role):
        s = self.settings
        if role in unit.baseline or len(unit.history[role]) < s.baseline_samples:
            return
        if len(unit.history[role]) > s.baseline_samples and unit.history[role][-1].sequence % 32:
            return
        window = list(unit.history[role])[-s.baseline_samples:]
        mean = tuple(fmean(p.xyz_g[i] for p in window) for i in range(3))
        rms = math.sqrt(fmean(norm(tuple(v-m for v, m in zip(p.xyz_g, mean)))**2 for p in window))
        flags = []
        if not .5 <= norm(mean) <= 1.5:
            flags.append("baseline_gravity_unexpected")
        if rms > s.baseline_max_rms_g:
            flags.append("baseline_unstable_or_loose")
        if any(set(p.flags)-{"timestamp_estimated", "boot_reset", "alignment_unavailable_or_expired", "timing_uncertainty_exceeds_budget"} for p in window):
            flags.append("baseline_input_quality")
        unit.baseline_health[role] = dict(rms_g=rms, gravity_g=norm(mean), flags=flags,
                                        field_self_test_passed=False)
        if not flags:
            unit.baseline[role] = mean

    def _magnitude(self, unit, sample):
        return norm(tuple(v-m for v, m in zip(sample.xyz_g, unit.baseline[sample.role])))

    def _finish(self, unit, received, forced=False):
        s, origin = self.settings, unit.pending
        if origin is None:
            return None
        time = origin.device_seconds
        end = time+s.post_seconds
        ready = all(unit.history[r] and unit.history[r][-1].device_seconds >= end-1e-8 for r in ("net", "frame"))
        latest = max((h[-1].device_seconds for h in unit.history.values() if h), default=time)
        if not ready and not forced and latest < end+.25:
            return None
        features, flags, retained = {}, [], []
        for role in ("net", "frame"):
            window = [p for p in unit.history[role] if time-s.pre_seconds-1e-8 <= p.device_seconds <= end+1e-8]
            retained += window
            expected = round((s.pre_seconds+s.post_seconds)*800)
            if len(window) < expected or not window or window[0].device_seconds > time-s.pre_seconds+.0015 or window[-1].device_seconds < end-.0015:
                flags.append("window_incomplete")
            if any(b.sequence != a.sequence+1 or abs(b.device_seconds-a.device_seconds-.00125) > .0002 for a, b in zip(window, window[1:])):
                flags.append("window_sample_gap")
            flags += unit.baseline_health.get(role, dict(flags=["baseline_unavailable"]))["flags"]
            magnitudes = [self._magnitude(unit, p) for p in window] if role in unit.baseline else []
            peak = max(magnitudes, default=0)
            rms = math.sqrt(fmean(v*v for v in magnitudes)) if magnitudes else 0
            roughness = math.sqrt(fmean((b-a)**2 for a, b in zip(magnitudes, magnitudes[1:]))) if len(magnitudes) > 1 else 0
            features.update({f"{role}_peak_g": peak, f"{role}_rms_g": rms,
                             f"{role}_roughness_ratio": roughness/max(rms, 1e-9), f"{role}_samples": float(len(window))})
        flags += [f for p in retained for f in p.flags if f not in ("timestamp_estimated", "boot_reset")]
        if not ready:
            flags.append("followup_incomplete")
        net, frame = features["net_peak_g"], features["frame_peak_g"]
        if flags:
            classification = "unknown"
        elif max(net, frame) < s.minimum_peak_g:
            classification = "unknown"
            flags.append("weak_trigger")
        elif features["net_roughness_ratio" if net >= frame else "frame_roughness_ratio"] < s.slow_roughness_ratio:
            classification = "slow_impact"
        elif net >= s.dominance_ratio*frame:
            classification = "net_impact"
        elif frame >= s.dominance_ratio*net:
            classification = "frame_impact"
        else:
            classification = "mixed_impact"
        aligned = origin.aligned_seconds
        uncertainty = max((p.timing_uncertainty_seconds for p in retained if p.timing_uncertainty_seconds is not None), default=None)
        if any(p.timing_uncertainty_seconds is None for p in retained):
            uncertainty = None
        identity = f"{origin.device_id}:{origin.boot_id}:{origin.transport_epoch}:{origin.role}:{origin.sequence}:{s.version}"
        event = SensorImpact(event_id=hashlib.sha256(identity.encode()).hexdigest(), goal_end=unit.end,
            device_id=origin.device_id, boot_id=origin.boot_id, occurred_device_seconds=time, occurred_seconds=aligned,
            emitted_seconds=received, timing_uncertainty_seconds=uncertainty, host_clock_domain=origin.host_clock_domain,
            evidence=origin.evidence, classification=classification, features=features, flags=sorted(set(flags)),
            configuration_version=s.version, possible_goal=True)
        unit.pending = None
        self.counters["impacts"] += 1
        return event

    def ingest(self, samples):
        events = []
        for sample in samples:
            identity = (sample.device_id, sample.boot_id, sample.transport_epoch)
            unit = self.units.get(sample.device_id)
            if unit is not None and "sensor_restart" in sample.flags:
                prior = unit.history[sample.role]
                if not prior or "sensor_restart" not in prior[-1].flags:
                    self.invalidate(sample.device_id)
                    unit = None
            if unit is None or unit.identity != identity:
                self.invalidate(sample.device_id)
                unit = self.units[sample.device_id] = Unit(self.settings, sample)
                self.counters["baseline_epochs"] += 1
            history = unit.history[sample.role]
            if history and (sample.sequence <= history[-1].sequence or sample.device_seconds <= history[-1].device_seconds):
                raise ValueError("Impact source sample order regressed")
            history.append(sample)
            self._baseline(unit, sample.role)
            if (unit.pending is None and all(r in unit.baseline for r in ("net", "frame")) and
                sample.device_seconds-unit.last_trigger >= self.settings.cooldown_seconds and
                self._magnitude(unit, sample) >= self.settings.trigger_g):
                unit.pending, unit.last_trigger = sample, sample.device_seconds
                self.counters["triggers"] += 1
            event = self._finish(unit, sample.received_seconds)
            if event:
                events.append(event)
        return events

    def flush(self, received_seconds):
        return [event for unit in self.units.values() if (event := self._finish(unit, received_seconds, forced=True))]

    def baseline_report(self):
        return [dict(device_id=device, boot_id=unit.identity[1], goal_end=unit.end,
                     sensors=unit.baseline_health, ready=len(unit.baseline)==2)
                for device, unit in sorted(self.units.items())]

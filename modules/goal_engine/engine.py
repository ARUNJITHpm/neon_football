"""Single-owner shadow engine; application persistence/integration belongs to Part 07."""
from copy import deepcopy
import hashlib
import json
import math

from core.fusion import FusedCandidate, FusionCommand, FusionEvent, FusionEvidence, FusionSettings
from core.ports import DomainError
from core.sensors import SensorImpact
from core.vision import VisionCandidate


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class GoalEngine:
    def __init__(self, settings: FusionSettings, *, session_id: str, match_id: str,
                 clock_domain: str, evidence="synthetic", goal_a_defending="orange"):
        # Validate context using the same contracts as incoming records.
        from core.schemas import MatchSetup, Identifier
        from pydantic import TypeAdapter
        for value in (session_id, match_id, clock_domain):
            TypeAdapter(Identifier).validate_python(value)
        MatchSetup(goal_a_defending=goal_a_defending)
        if evidence not in ("synthetic", "venue"):
            raise ValueError("Register synthetic or venue provenance")
        self.settings = settings.model_copy(deep=True)
        self.session_id, self.match_id, self.clock_domain = session_id, match_id, clock_domain
        self.evidence = evidence
        self.mapping = {"goal_a": goal_a_defending, "goal_b": self.other(goal_a_defending)}
        self.status, self.play_epoch, self.boundary_seconds = "ready", 0, 0.
        self.restart_required = False
        self.now, self.revision = 0., 0
        self.candidates, self.inputs, self.commands, self.events = {}, {}, {}, []

    @staticmethod
    def other(team):
        return "green" if team == "orange" else "orange"

    def _reserve(self, now):
        if not math.isfinite(now) or now < self.now:
            raise ValueError("Engine time must be finite, nonnegative and monotonic")
        # A boundary may transition every open candidate. Reject before any mutation.
        if len(self.events)+2*len(self.candidates)+5 > self.settings.max_events:
            raise ValueError("Journal capacity reached; export and partition replay")

    def _log(self, kind, candidate=None, actor="fusion", **details):
        self.revision += 1
        namespace = hashlib.sha256(self.match_id.encode()).hexdigest()[:16]
        event = FusionEvent(event_id=f"fusion:{namespace}:{self.revision}", revision=self.revision,
            recorded_seconds=self.now, match_id=self.match_id, type=kind,
            candidate_id=candidate.candidate_id if candidate else None, actor=actor, details=details)
        self.events.append(event.model_dump(mode="json"))

    def _transition(self, c, status, reasons, *, confirmation=None, actor="fusion"):
        legal = {"COLLECTING": {"PENDING_REVIEW", "CONFIRMED", "UNRESOLVED"},
                 "PENDING_REVIEW": {"CONFIRMED", "REJECTED", "UNRESOLVED"}}
        if status not in legal.get(c.status, set()):
            raise DomainError("Illegal candidate transition")
        previous = c.status
        c.status, c.reasons = status, list(reasons)
        if status == "CONFIRMED":
            c.confirmation, c.confirmed_seconds = confirmation, self.now
            c.rule_label = "observed_and_corroborated" if confirmation == "shadow_rule" else "operator_decision"
            self.restart_required = True
        elif status == "PENDING_REVIEW":
            c.review_until_seconds = self.now+self.settings.review_seconds
            c.rule_label = "review_required"
        else:
            c.rule_label = "operator_decision" if status == "REJECTED" else "unresolved"
        self._log("candidate_transition", c, actor, previous=previous, status=status,
                  reasons=c.reasons, confirmation=c.confirmation, rule_label=c.rule_label)

    def _quality(self, evidence):
        o = evidence.observation
        return (o.occurred_seconds is not None and o.timing_uncertainty_seconds is not None
                and o.timing_uncertainty_seconds <= self.settings.maximum_uncertainty_seconds
                and self.now-o.occurred_seconds <= self.settings.maximum_evidence_age_seconds
                and not o.flags and o.evidence == self.evidence)

    def _interval(self, e):
        o = e.observation
        if not self._quality_timing(o):
            return None
        if isinstance(o, VisionCandidate) and o.crossing_interval_seconds is not None:
            lo, hi = o.crossing_interval_seconds
        else:
            lo = hi = o.occurred_seconds
        return lo-o.timing_uncertainty_seconds, hi+o.timing_uncertainty_seconds

    def _quality_timing(self, o):
        return (o.occurred_seconds is not None and o.timing_uncertainty_seconds is not None and
                o.timing_uncertainty_seconds <= self.settings.maximum_uncertainty_seconds)

    def _close(self, first, second):
        a, b = self._interval(first), self._interval(second)
        if a is None or b is None:
            return False
        return max(a[0]-b[1], b[0]-a[1], 0) <= self.settings.correlation_seconds

    def _decide(self, c):
        records = [self.inputs[i]["evidence"] for i in c.evidence_ids]
        visual = [e for e in records if isinstance(e.observation, VisionCandidate)]
        sensors = [e for e in records if isinstance(e.observation, SensorImpact)]
        observed = [e for e in visual if e.observation.quality == "observed_crossing" and
                    self._quality(e) and e.observation.crossing_interval_seconds is not None and
                    e.observation.crossing_interval_seconds[1]-e.observation.crossing_interval_seconds[0]
                    <= 2*self.settings.maximum_uncertainty_seconds]
        corroborating = [e for e in sensors if self._quality(e) and
                         e.observation.classification in ("net_impact", "frame_impact", "mixed_impact")]
        # A later nearby track can make a previously attached impact ambiguous.
        ambiguous = []
        for s in corroborating:
            possible = [other for other in self.candidates.values()
                if other.goal_end == c.goal_end and other.play_epoch == c.play_epoch and
                any(isinstance(self.inputs[i]["evidence"].observation, VisionCandidate) and
                    self.inputs[i]["evidence"].observation.quality != "net_motion_only" and
                    self._close(s, self.inputs[i]["evidence"]) for i in other.evidence_ids)]
            if len(possible) > 1:
                ambiguous.append(s)
        corroborating = [s for s in corroborating if s not in ambiguous]
        reasons = []
        if not observed:
            reasons.append("reliable_observed_whole_ball_crossing_missing")
        if not corroborating:
            reasons.append("quality_sensor_corroboration_missing")
        if ambiguous:
            reasons.append("impact_could_support_multiple_incidents")
        if observed and corroborating and not any(self._close(v, s) for v in observed for s in corroborating):
            reasons.append("crossing_and_impact_outside_timing_window")
        if self.status != "live" or c.play_epoch != self.play_epoch:
            reasons.append("inactive_play_epoch")
        if self.restart_required:
            reasons.append("operator_restart_required")
        if not reasons:
            self._transition(c, "CONFIRMED", ["observed_crossing_with_time_aligned_quality_impact", "shadow_only"],
                             confirmation="shadow_rule")
        else:
            self._transition(c, "PENDING_REVIEW", reasons)

    def advance(self, now, *, snapshot=True):
        self._reserve(now)
        # Timers fire at their deadlines even when replay advances over many seconds.
        while True:
            due = [(c.collect_until_seconds if c.status == "COLLECTING" else c.review_until_seconds, c)
                   for c in self.candidates.values() if c.status in ("COLLECTING", "PENDING_REVIEW")]
            due = [(t, c) for t, c in due if t <= now]
            if not due:
                break
            deadline, c = min(due, key=lambda item: (item[0], item[1].candidate_id))
            self.now = deadline
            if c.status == "COLLECTING":
                self._decide(c)
            else:
                self._transition(c, "UNRESOLVED", ["review_expired_without_operator_decision"])
        self.now = now
        return self.snapshot() if snapshot else None

    def _registration_error(self, e):
        o = e.observation
        if (e.session_id, e.match_id, e.clock_domain) != (self.session_id, self.match_id, self.clock_domain):
            return "wrong_session_match_or_clock"
        if e.play_epoch != self.play_epoch:
            return "stale_play_epoch"
        if o.evidence != self.evidence:
            return "evidence_provenance_mismatch"
        if isinstance(o, VisionCandidate):
            camera = self.settings.cameras.get(o.camera_id)
            if (o.session_id, o.match_id) != (self.session_id, self.match_id) or camera is None:
                return "unregistered_camera_or_identity"
            if (o.goal_end, o.calibration_version, o.model_version, o.configuration_version) != (
                camera.goal_end, camera.calibration_version, camera.model_version, camera.configuration_version):
                return "camera_end_or_version_mismatch"
        elif (self.settings.devices.get(o.device_id) != o.goal_end or o.host_clock_domain != self.clock_domain or
              o.configuration_version != self.settings.sensor_configuration_version):
            return "sensor_end_clock_or_version_mismatch"
        if o.emitted_seconds > self.now or (o.occurred_seconds is not None and o.occurred_seconds > o.emitted_seconds):
            return "future_evidence"
        if o.occurred_seconds is not None and o.occurred_seconds < self.boundary_seconds:
            return "occurrence_before_play_boundary"
        if o.occurred_seconds is not None and self.now-o.occurred_seconds > self.settings.maximum_evidence_age_seconds:
            return "stale_evidence"
        return None

    def ingest(self, evidence: FusionEvidence, now):
        evidence = FusionEvidence.model_validate(evidence).model_copy(deep=True)
        o = evidence.observation
        fingerprint = encode(evidence.model_dump(mode="json"))
        self._reserve(now)
        old = self.inputs.get(o.event_id)
        if old:
            if old["fingerprint"] != fingerprint:
                raise DomainError("Evidence ID reused for different content")
            self.advance(now, snapshot=False)
            return deepcopy(old["result"])
        if len(self.inputs) >= self.settings.max_inputs or len(self.candidates) >= self.settings.max_candidates:
            raise ValueError("Evidence/candidate capacity reached; partition replay")
        self.advance(now, snapshot=False)
        record = {"evidence": evidence, "fingerprint": fingerprint}
        self.inputs[o.event_id] = record
        error = self._registration_error(evidence)
        if error:
            self._log("evidence_ignored", evidence_id=o.event_id, reason=error)
            record["result"] = dict(accepted=False, reason=error, candidate_id=None)
            return deepcopy(record["result"])
        candidates = []
        for c in self.candidates.values():
            if c.goal_end != o.goal_end or c.play_epoch != self.play_epoch:
                continue
            same_track = isinstance(o, VisionCandidate) and o.track_id is not None and o.track_id in c.track_ids
            # Distinct observed tracks must never collapse simply because they occur nearby.
            different_track = isinstance(o, VisionCandidate) and o.track_id and c.track_ids and not same_track
            age = self.now-c.created_seconds
            if different_track or age > self.settings.repeat_seconds:
                continue
            records = [self.inputs[i]["evidence"] for i in c.evidence_ids]
            if (same_track and o.occurred_seconds is not None and c.occurred_seconds is not None and
                abs(o.occurred_seconds-c.occurred_seconds) <= self.settings.repeat_seconds) or any(
                    self._close(evidence, existing) for existing in records):
                candidates.append(c)
        ambiguous = len(candidates) > 1
        c = candidates[0] if len(candidates) == 1 else None
        if c is None:
            candidate_id = "candidate:"+hashlib.sha256(f"{self.session_id}:{self.match_id}:{self.play_epoch}:{o.event_id}".encode()).hexdigest()[:32]
            c = FusedCandidate(candidate_id=candidate_id, session_id=self.session_id, match_id=self.match_id,
                play_epoch=self.play_epoch, goal_end=o.goal_end, team=self.other(self.mapping[o.goal_end]),
                occurred_seconds=o.occurred_seconds, created_seconds=self.now,
                collect_until_seconds=self.now+self.settings.collection_seconds, configuration_version=self.settings.version)
            self.candidates[candidate_id] = c
            self._log("candidate_created", c, goal_end=c.goal_end, team=c.team, play_epoch=c.play_epoch)
        c.evidence_ids.append(o.event_id)
        if isinstance(o, VisionCandidate) and o.track_id and o.track_id not in c.track_ids:
            c.track_ids.append(o.track_id)
        if (c.status == "COLLECTING" and isinstance(o, VisionCandidate) and o.quality == "observed_crossing"
            and not any(isinstance(self.inputs[i]["evidence"].observation, VisionCandidate) and
                        self.inputs[i]["evidence"].observation.quality == "observed_crossing"
                        for i in c.evidence_ids[:-1])):
            c.occurred_seconds = o.occurred_seconds
        self._log("evidence_attached", c, evidence_id=o.event_id, late=c.status != "COLLECTING",
                  ambiguous_association=ambiguous)
        if c.status == "COLLECTING":
            if self.status != "live" or self.restart_required or ambiguous:
                self._transition(c, "UNRESOLVED", ["ambiguous_incident_association" if ambiguous else
                    "operator_restart_required" if self.restart_required else "match_not_live"])
        record["result"] = dict(accepted=True, candidate_id=c.candidate_id, reason="evidence_logged")
        return deepcopy(record["result"])

    def _boundary(self, reason):
        for c in list(self.candidates.values()):
            if c.status in ("COLLECTING", "PENDING_REVIEW"):
                self._transition(c, "UNRESOLVED", [reason])
        self.play_epoch += 1
        self.boundary_seconds = self.now

    def command(self, command: FusionCommand, now):
        cmd = FusionCommand.model_validate(command)
        fingerprint = encode(cmd.model_dump(mode="json"))
        self._reserve(now)
        if cmd.command_id in self.commands:
            old = self.commands[cmd.command_id]
            if old[0] != fingerprint:
                raise DomainError("Command ID reused for different request")
            self.advance(now, snapshot=False)
            return deepcopy(old[1])
        if len(self.commands) >= self.settings.max_inputs:
            raise ValueError("Command capacity reached; partition replay")
        self.advance(now, snapshot=False)
        if cmd.match_id != self.match_id or cmd.expected_revision != self.revision:
            raise DomainError("Stale command: refresh match/revision before retrying")
        c = self.candidates.get(cmd.candidate_id) if cmd.candidate_id else None
        if cmd.candidate_id and c is None:
            raise DomainError("Candidate not found", 404)
        action = cmd.action
        lifecycle = {"start": ("ready", "live"), "pause": ("live", "paused"), "resume": ("paused", "live")}
        if action in lifecycle:
            previous, following = lifecycle[action]
            if self.status != previous:
                raise DomainError("Illegal match transition")
            self._boundary(f"match_{action}_boundary")
            self.status = following
        elif action == "end":
            if self.status == "ended":
                raise DomainError("Match already ended")
            self._boundary("match_ended")
            self.status = "ended"
        elif action == "swap_ends":
            if self.status not in ("ready", "paused"):
                raise DomainError("Pause before changing ends")
            self._boundary("ends_changed")
            self.mapping = {end: self.other(team) for end, team in self.mapping.items()}
        elif action == "restart":
            if self.status != "live":
                raise DomainError("Restart requires live match")
            self._boundary("operator_restart_boundary")
            self.restart_required = False
        elif action in ("confirm", "reject"):
            if self.status not in (("live",) if action == "confirm" else ("live", "paused")):
                raise DomainError("Candidate action unavailable in current match state")
            if c.status != "PENDING_REVIEW" or c.play_epoch != self.play_epoch:
                raise DomainError("Candidate resolved or outside current play epoch")
            if action == "confirm" and self.restart_required:
                raise DomainError("Operator restart required before another confirmation")
            self._transition(c, "CONFIRMED" if action == "confirm" else "REJECTED", ["explicit_operator_decision"],
                             confirmation="operator" if action == "confirm" else None, actor=cmd.actor)
        elif action == "undo":
            if c.status != "CONFIRMED" or c.corrected:
                raise DomainError("Only an active confirmation can be undone")
            c.corrected = True
            self._log("confirmation_corrected", c, cmd.actor, correction="goal_undone")
        self._log("command_applied", c, cmd.actor, command_id=cmd.command_id, action=action,
                  status=self.status, play_epoch=self.play_epoch, restart_required=self.restart_required,
                  goal_mapping=self.mapping.copy())
        result = dict(revision=self.revision, action=action, candidate_id=cmd.candidate_id)
        self.commands[cmd.command_id] = (fingerprint, result)
        return deepcopy(result)

    def snapshot(self):
        score = {"orange": 0, "green": 0}
        for c in self.candidates.values():
            if c.status == "CONFIRMED" and not c.corrected:
                score[c.team] += 1
        return deepcopy(dict(schema_version=1, session_id=self.session_id, match_id=self.match_id,
            configuration_version=self.settings.version, mode="shadow", status=self.status,
            revision=self.revision, play_epoch=self.play_epoch, now_seconds=self.now,
            restart_required=self.restart_required, goal_mapping=self.mapping,
            shadow_score=score, official_score_mutated=False,
            candidates=[c.model_dump(mode="json") for c in self.candidates.values()],
            evidence=[dict(receipt_result=r["result"], **r["evidence"].model_dump(mode="json")) for r in self.inputs.values()],
            events=self.events))

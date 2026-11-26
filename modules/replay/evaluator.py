"""Score injected automatic decisions separately from human rescues and uncertainty."""
import hashlib
import json
from pathlib import Path

from core.dataset import AnnotationSet, DatasetManifest, ReplayOutput
from .dataset import select, validate_annotations
from .matching import match
from .statistics import distribution, poisson_rate, proportion

VERSION = "event-evaluator-v1"


def evaluate(manifest: DatasetManifest, annotations: AnnotationSet, replay: ReplayOutput,
             tolerance_seconds=0.5, allow_blind_test=False):
    manifest = DatasetManifest.model_validate(manifest.model_dump())
    annotations = AnnotationSet.model_validate(annotations.model_dump())
    replay = ReplayOutput.model_validate(replay.model_dump())
    if not 0 < tolerance_seconds <= 5:
        raise ValueError("Matching tolerance must be positive and at most five seconds")
    if replay.dataset_id != manifest.dataset_id:
        raise ValueError("Replay dataset mismatch")
    sessions = select(manifest, replay.split, allow_blind_test)
    if replay.sessions != [s.session_id for s in sessions]:
        raise ValueError("Replay session inventory/order does not match selected split")
    if (replay.configuration_versions != {s.session_id: s.configuration_version for s in sessions} or
            replay.model_versions != {s.session_id: s.model_version for s in sessions}):
        raise ValueError("Replay configuration/model provenance differs from manifest")
    labels = validate_annotations(manifest, annotations, sessions)
    decision_keys = set()
    for decision in replay.decisions:
        session = next((s for s in sessions if s.session_id == decision.session_id), None)
        window = next((m for m in session.matches if m.match_id == decision.match_id), None) if session else None
        identity = (decision.session_id, decision.event_id)
        if (window is None or decision.kind != "decision" or identity in decision_keys or
                not window.start_seconds <= decision.occurred_seconds < window.end_seconds or
                decision.delivered_seconds > session.duration_seconds):
            raise ValueError("Invalid/duplicate replay decision or session/match boundary")
        decision_keys.add(identity)

    def active(prediction):
        session = next(s for s in sessions if s.session_id == prediction.session_id)
        window = next(m for m in session.matches if m.match_id == prediction.match_id)
        return any(w.start_seconds <= prediction.occurred_seconds < w.end_seconds and
                   w.start_seconds <= prediction.delivered_seconds < w.end_seconds for w in window.active_auto_windows)

    per_session, errors, matches_output = [], [], []
    totals = dict(valid_goals=0, true_positives=0, false_positives=0, false_negatives=0, automatic_decisions=0,
                  uncertain_labels=0, unadjudicated_automatic=0, invalid_labels=0, manual_goals=0,
                  operator_confirmed=0, human_rescued_goals=0, review_prompts=0, confirmed_goals=0,
                  corrected_goals=0, automatic_outside_active_window=0, shadow_automatic_decisions=0)
    latencies, latency_bounds, timing_uncertainty = [], [], []
    healthy_valid_goals = 0
    scheduled_seconds = active_seconds = 0
    audited = {a.session_id: a.continuous_footage_reviewed for a in annotations.audits}
    for session in sessions:
        local = [l for l in labels if l.session_id == session.session_id]
        valid = [l for l in local if l.validity == "valid"]
        healthy_valid_goals += sum(any(w.start_seconds <= label.crossing_seconds < w.end_seconds
            for m in session.matches if m.match_id == label.match_id for w in m.active_auto_windows) for label in valid)
        uncertain = [l for l in local if l.validity == "uncertain"]
        decisions = [p for p in replay.decisions if p.session_id == session.session_id]
        auto = [p for p in decisions if p.outcome == "automatic"]
        pairs = match(valid, auto, tolerance_seconds, active)
        matched_labels = {l.label_id for l, p in pairs}
        matched_predictions = {p.event_id for l, p in pairs}
        unknown = [p for p in auto if p.event_id not in matched_predictions and active(p) and any(
                   l.match_id == p.match_id and l.goal_end == p.goal_end and
                   abs(l.crossing_seconds - p.occurred_seconds) <= tolerance_seconds for l in uncertain)]
        unknown_ids = {p.event_id for p in unknown}
        false = [p for p in auto if p.event_id not in matched_predictions and p.event_id not in unknown_ids]
        missed = [l for l in valid if l.label_id not in matched_labels]
        human = [p for p in decisions if p.outcome in ("manual", "operator_confirmed")]
        rescues = match(missed, human, tolerance_seconds)
        confirmed = [p for p in decisions if p.outcome in ("automatic", "manual", "operator_confirmed") and not p.shadow]
        counts = dict(valid_goals=len(valid), true_positives=len(pairs), false_positives=len(false), false_negatives=len(missed),
                      automatic_decisions=len(auto), uncertain_labels=len(uncertain), unadjudicated_automatic=len(unknown),
                      invalid_labels=sum(l.validity == "invalid" for l in local), manual_goals=sum(p.outcome == "manual" for p in decisions),
                      operator_confirmed=sum(p.outcome == "operator_confirmed" for p in decisions), human_rescued_goals=len(rescues),
                      review_prompts=sum(p.review_required for p in decisions), confirmed_goals=len(confirmed),
                      corrected_goals=sum(p.corrected for p in confirmed), automatic_outside_active_window=sum(not active(p) for p in auto),
                      shadow_automatic_decisions=sum(p.shadow for p in auto))
        seconds = sum(m.end_seconds-m.start_seconds for m in session.matches)
        healthy = sum(w.end_seconds-w.start_seconds for m in session.matches for w in m.active_auto_windows)
        scheduled_seconds += seconds
        active_seconds += healthy
        for key, value in counts.items():
            totals[key] += value
        per_session.append(dict(session_id=session.session_id, conditions=session.conditions,
                                scheduled_seconds=seconds, active_auto_seconds=healthy, counts=counts,
                                recall=proportion(len(pairs), len(valid)), false_automatic_per_hour=poisson_rate(len(false), seconds/3600)))
        for label, prediction in pairs:
            uncertainty = label.timing_uncertainty + prediction.timing_uncertainty_seconds
            timing_uncertainty.append(uncertainty)
            row = dict(session_id=session.session_id, match_id=label.match_id, label_id=label.label_id,
                       event_id=prediction.event_id, crossing_error_seconds=prediction.occurred_seconds-label.crossing_seconds,
                       crossing_uncertainty_seconds=uncertainty, clip_path=prediction.clip_path or label.clip_path,
                       shadow=prediction.shadow, latency_seconds=None)
            if prediction.displayed_seconds is not None and prediction.display_uncertainty_seconds is not None:
                latency = prediction.displayed_seconds-label.crossing_seconds
                latencies.append(latency)
                latency_bounds.append(latency + label.timing_uncertainty + prediction.display_uncertainty_seconds)
                row["latency_seconds"] = latency
            matches_output.append(row)
        for prediction in false:
            reason = "automatic_while_inactive" if not active(prediction) else "duplicate" if any(
                l.match_id == prediction.match_id and l.goal_end == prediction.goal_end and l.team == prediction.team and
                abs(l.crossing_seconds-prediction.occurred_seconds) <= tolerance_seconds for l, _ in pairs) else "unmatched_automatic"
            nearby = [l for l in valid if l.match_id == prediction.match_id and abs(l.crossing_seconds-prediction.occurred_seconds) <= tolerance_seconds]
            if reason == "unmatched_automatic" and any(l.team == prediction.team and l.goal_end != prediction.goal_end for l in nearby):
                reason = "wrong_goal_end"
            elif reason == "unmatched_automatic" and any(l.goal_end == prediction.goal_end and l.team != prediction.team for l in nearby):
                reason = "wrong_team"
            errors.append(dict(type=reason, session_id=session.session_id, match_id=prediction.match_id,
                               event_id=prediction.event_id, goal_end=prediction.goal_end, clip_path=prediction.clip_path,
                               occurred_seconds=prediction.occurred_seconds, delivered_seconds=prediction.delivered_seconds))
        for label in missed:
            errors.append(dict(type="missed_valid_goal", session_id=session.session_id, match_id=label.match_id,
                               label_id=label.label_id, goal_end=label.goal_end, clip_path=label.clip_path,
                               crossing_seconds=label.crossing_seconds, crossing_uncertainty_seconds=label.timing_uncertainty,
                               human_rescued=any(l.label_id == label.label_id for l, _ in rescues)))
        for prediction in unknown:
            errors.append(dict(type="unadjudicated_automatic", session_id=session.session_id,
                               event_id=prediction.event_id, clip_path=prediction.clip_path))
    tp, fp, goals = totals["true_positives"], totals["false_positives"], totals["valid_goals"]
    hours, active_hours = scheduled_seconds/3600, active_seconds/3600
    metrics = dict(automatic_recall=proportion(tp, goals), automatic_precision=proportion(tp, tp+fp),
                   healthy_only_recall=proportion(tp, healthy_valid_goals),
                   false_automatic_per_scheduled_hour=poisson_rate(fp, hours),
                   false_automatic_per_active_hour=poisson_rate(fp, active_hours),
                   availability=dict(value=active_seconds/scheduled_seconds, scheduled_seconds=scheduled_seconds, active_auto_seconds=active_seconds),
                   review_prompts_per_goal=dict(value=totals["review_prompts"]/goals if goals else None,
                                               prompts=totals["review_prompts"], valid_goals=goals),
                   review_prompts_per_hour=poisson_rate(totals["review_prompts"], hours),
                   correction_rate=proportion(totals["corrected_goals"], totals["confirmed_goals"]),
                   visible_latency_seconds=distribution(latencies), visible_latency_upper_bound_seconds=distribution(latency_bounds),
                   crossing_uncertainty_seconds=distribution(timing_uncertainty),
                   display_measurement_coverage=proportion(len(latencies), tp))
    limitations = ["Injected recorded decisions; no detector or goal-engine performance is established.",
                  "Wilson/Poisson intervals assume independent events; match clustering is not adjusted."]
    if any(s.evidence == "synthetic" for s in sessions):
        limitations.append("Synthetic evidence cannot qualify a venue release.")
    if any(not audited.get(s.session_id, False) for s in sessions):
        limitations.append("Continuous-footage audit is missing; goal recall and false-goal counts are provisional.")
    if totals["uncertain_labels"]:
        limitations.append("Uncertain labels are reported separately; unadjudicated automatic decisions are excluded from precision/rates.")
    if len(latencies) < tp:
        limitations.append("Some matched goals have no measured display timestamp/uncertainty; visible latency coverage is incomplete.")
    if any(not s.physical_alignment_verified for s in sessions):
        limitations.append("Physical crossing/display alignment has not been verified for every session.")
    if any(value < 0 for value in latencies):
        limitations.append("Negative matched display latency indicates invalid clock alignment/label timing; values are retained for diagnosis.")
    conditions = {}
    for result in per_session:
        for condition in sorted(set(result["conditions"])):
            group = conditions.setdefault(condition, dict(session_ids=[], scheduled_seconds=0, active_auto_seconds=0,
                                                         true_positives=0, false_positives=0, valid_goals=0))
            group["session_ids"].append(result["session_id"])
            group["scheduled_seconds"] += result["scheduled_seconds"]
            group["active_auto_seconds"] += result["active_auto_seconds"]
            for key in ("true_positives", "false_positives", "valid_goals"):
                group[key] += result["counts"][key]
    for group in conditions.values():
        group["recall"] = proportion(group["true_positives"], group["valid_goals"])
        group["false_automatic_per_hour"] = poisson_rate(group["false_positives"], group["scheduled_seconds"]/3600)
    configuration = dict(evaluator=VERSION, matching_tolerance_seconds=tolerance_seconds,
                         matching="maximum-cardinality-minimum-time", annotation_policy=manifest.annotation_policy_version)
    sources = [Path(__file__), Path(__file__).with_name("matching.py"), Path(__file__).with_name("statistics.py"),
               Path(__file__).with_name("dataset.py"), Path(__file__).resolve().parents[2] / "core/dataset.py"]
    implementation = hashlib.sha256()
    for path in sources:
        implementation.update(path.name.encode()+b"\0"+path.read_bytes()+b"\0")
    configuration["implementation_sha256"] = implementation.hexdigest()
    return dict(schema_version=1, evaluator=VERSION, configuration=configuration,
                configuration_sha256=hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest(),
                dataset_id=manifest.dataset_id, annotation_version=annotations.version, split=replay.split,
                input_fingerprint=replay.input_fingerprint, manifest_sha256=replay.manifest_sha256,
                counts=totals, metrics=metrics, sessions=per_session, conditions=conditions, matches=matches_output, errors=errors,
                limitations=limitations, release_qualified=False)

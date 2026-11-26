"""Deterministic operator report reconstructed from committed events and corrections."""
from core.ports import DomainError
from copy import deepcopy


def match_report(export):
    state,events=export["snapshot"],export["events"]
    goals,corrections,suggestions={},[],{}
    analytics={}
    roster_revision=0
    active_player_ids=[p["id"] for p in state["players"]]
    def retire(goal_id,reason):
        for item in suggestions.values():
            if item["goal_id"]==goal_id and item["status"]=="pending":
                item.update(status="superseded",resolution_reason=reason)
    for event in events:
        payload=event["payload"]
        if event["type"]=="match_created":
            active_player_ids=list(payload.get("active_player_ids",[p["id"] for p in payload["players"]]))
        elif event["type"]=="player_substituted":
            if payload["outgoing_id"] not in active_player_ids or payload["incoming_id"] in active_player_ids or payload["roster_revision"]!=roster_revision+1:
                raise DomainError("Report roster substitution chain differs",500)
            active_player_ids.remove(payload["outgoing_id"]);active_player_ids.append(payload["incoming_id"])
            roster_revision=payload["roster_revision"]
            if active_player_ids!=payload["active_player_ids"]:
                raise DomainError("Report active roster differs from substitution event",500)
        elif event["type"]=="attribution_suggested":
            if payload["goal_id"] not in goals:
                raise DomainError("Suggestion references no committed goal",500)
            retire(payload["goal_id"],"Replaced by a newer suggestion")
            suggestions[payload["suggestion_id"]]=deepcopy(payload)
        elif event["type"]=="attribution_rejected":
            suggestions[payload["suggestion_id"]]["status"]="rejected"
        elif event["type"]=="analytics_session_added":
            sid=payload["session"]["session_id"]
            if sid in analytics or payload["revision"]!=0 or payload["corrections"]:
                raise DomainError("Analytics initial session differs",500)
            analytics[sid]=deepcopy(payload)
        elif event["type"]=="analytics_touch_corrected":
            sid=payload["change"]["session_id"]
            if sid not in analytics or payload["revision"]!=analytics[sid]["revision"]+1:
                raise DomainError("Analytics correction chain differs",500)
            analytics[sid]["revision"]=payload["revision"]
            analytics[sid]["corrections"].append(deepcopy(payload))
        elif event["type"]=="goal_confirmed":
            goals[payload["goal_id"]]={**payload,"active":True,"recorded_at":event["recorded_at"],"actor":event["actor"]}
        elif event["type"]=="correction_applied" and payload.get("correction")=="goal_undone":
            if payload["goal_id"] not in goals:
                raise DomainError("Report correction references no committed goal",500)
            goals[payload["goal_id"]]["active"]=False
            retire(payload["goal_id"],"Goal was undone")
            corrections.append({"goal_id":payload["goal_id"],"event_id":event["event_id"],"recorded_at":event["recorded_at"]})
        elif event["type"]=="attribution_changed":
            if payload["goal_id"] not in goals:
                raise DomainError("Report attribution references no committed goal",500)
            goals[payload["goal_id"]].update({k:payload[k] for k in ("scorer_id","assist_id","own_goal")})
            if "attribution_revision" in payload:
                goals[payload["goal_id"]]["attribution_revision"]=payload["attribution_revision"]
            goals[payload["goal_id"]]["attribution_source"]="dummy_suggestion" if payload.get("suggestion_id") else "operator"
            if payload.get("suggestion_id"):
                suggestions[payload["suggestion_id"]]["status"]="accepted"
            retire(payload["goal_id"],"Operator attribution changed")
    score={"orange":0,"green":0}
    players={p["id"]:p for p in state["players"]}
    for goal in goals.values():
        if goal["active"]:
            score[goal["team"]]+=1
        goal["scorer_name"]=players.get(goal.get("scorer_id"),{}).get("name","Unknown")
        goal["assist_name"]=players.get(goal.get("assist_id"),{}).get("name")
    if score!=state["score"]:
        raise DomainError("Report score does not reconcile with committed projection",500)
    return dict(schema_version=1,match_id=state["match_id"],revision=state["revision"],status=state["status"],
        mode="manual",review_mode=state.get("review_mode","manual"),teams=state["teams"],score=score,
        duration_seconds=state["duration_seconds"],last_committed_elapsed_seconds=state["elapsed_seconds"],
        clock_reconciliation_required=state["clock_reconciliation_required"],goals=list(goals.values()),corrections=corrections,
        roster_revision=roster_revision,active_player_ids=active_player_ids,
        attribution_suggestion_statuses={key:item["status"] for key,item in suggestions.items()},
        analytics_sessions=list(analytics.values()),
        review_counts={status:sum(c["status"]==status for c in state["candidates"]) for status in ("pending_review","confirmed","rejected","unresolved")},
        event_count=len(events),contains_dummy_attribution=bool(suggestions),
        contains_dummy_review=any(c.get("review",{}).get("origin")=="dummy_fusion" for c in state["candidates"]))


def report_text(report):
    teams,score=report["teams"],report["score"]
    lines=["Neon Score — match report",f"Match: {report['match_id']} | revision {report['revision']}",
        f"Status: {report['status']} | operator-controlled scoring",f"{teams['orange']} {score['orange']} — {score['green']} {teams['green']}",
        f"Last committed elapsed time: {report['last_committed_elapsed_seconds']:.3f} seconds",""]
    if report["contains_dummy_review"]:
        lines.extend(["This match contains explicitly generated dummy review evidence.",""])
    if report["contains_dummy_attribution"]:
        lines.extend(["This match contains generated attribution suggestions; applied names were operator approved.",""])
    for i,goal in enumerate(report["goals"],1):
        attribution=f"scorer: {goal['scorer_name']}"+(" (own goal)" if goal["own_goal"] else "")
        if goal["assist_name"]:
            attribution+=f"; assist: {goal['assist_name']}"
        lines.append(f"{i}. {teams[goal['team']]} | {goal['elapsed_seconds']:.3f}s | {attribution} | {'active' if goal['active'] else 'undone'}")
    if not report["goals"]:
        lines.append("No goals committed.")
    lines.extend(["",f"Corrections: {len(report['corrections'])}",
        "Review outcomes: "+", ".join(f"{key.replace('_',' ')} {value}" for key,value in report["review_counts"].items())])
    return "\n".join(lines)+"\n"

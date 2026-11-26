"""Compose corrected official score statistics with separately scoped dummy analytics."""
from modules.storage.report import match_report, report_text
from modules.stats.analytics import analyze, corrected_session


def enriched_report(export):
    report = match_report(export)
    roster = export["snapshot"]["players"]
    teams = {team: dict(goals=report["score"][team], attributed_goals=0, unknown_scorer_goals=0) for team in ("orange","green")}
    players = {p["id"]: dict(**p,goals=0,assists=0,own_goals=0) for p in roster}
    for goal in report["goals"]:
        if not goal["active"]: continue
        if goal["scorer_id"] is None:
            teams[goal["team"]]["unknown_scorer_goals"]+=1
        else:
            teams[goal["team"]]["attributed_goals"]+=1
            players[goal["scorer_id"]]["own_goals" if goal["own_goal"] else "goals"]+=1
        if goal["assist_id"] is not None: players[goal["assist_id"]]["assists"]+=1
    sessions=[]
    for item in report.pop("analytics_sessions"):
        result=analyze(corrected_session(item["session"],item["corrections"]))
        identities={p["id"]:p for p in item["session"]["rosters"][0]["roster"]["players"]}
        result["players"]={pid:{**identities[pid],**stats} for pid,stats in result["players"].items()}
        result.update(analytics_revision=item["revision"],correction_count=len(item["corrections"]))
        sessions.append(result)
    report["official_statistics"]=dict(scope="active_goals_and_operator_approved_attribution",teams=teams,players=list(players.values()))
    report["contact_analytics"]=dict(scope="separate_generated_example_windows_not_official_match_timeline",sessions=sessions,
        status="available_generated_examples" if sessions else "unavailable",field_qualified=False,
        unavailable_metrics=["distance","heatmaps","shots","shots_on_target"],
        note="Generated contact windows are not footage or measured match possession; sessions are never summed as match totals.")
    return report


def enriched_text(report):
    lines=[report_text(report).rstrip(),"","Official player statistics (active approved goals only):"]
    for p in report["official_statistics"]["players"]:
        lines.append(f"{report['teams'][p['team']]} | {p['bib']} {p['name']} | goals {p['goals']} | assists {p['assists']} | own goals {p['own_goals']}")
    if not report["official_statistics"]["players"]: lines.append("No registered players.")
    contact=report["contact_analytics"]
    lines.extend(["", "Contact analytics: "+contact["status"], contact["note"]])
    for session in contact["sessions"]:
        time=session["time_accounting"]
        lines.append(f"Generated window {session['session_id']} | revision {session['analytics_revision']} | metrics {session['metric_status']}")
        for team,stats in session["teams"].items():
            lines.append(f"  {report['teams'][team]}: observed passes {stats['passes']}, interceptions {stats['interceptions']}, possession {stats['possession_seconds']:.3f}s")
        for p in session["players"].values():
            lines.append(f"  Generated player {report['teams'][p['team']]} | {p['bib']} {p['name']}: passes {p['passes']}, received {p['received_passes']}, interceptions {p['interceptions']}, possession {p['possession_seconds']:.3f}s")
        lines.append(f"  In play {time['in_play_seconds']:.3f}s; unknown possession {time['unknown_possession_seconds']:.3f}s; paused {time['paused_seconds']:.3f}s; dead ball {time['dead_ball_seconds']:.3f}s; unknown state {time['unknown_state_seconds']:.3f}s")
    lines.extend(["Distance, heatmaps, shots and shots on target: unavailable.","Field metric qualification: pending."])
    return "\n".join(lines)+"\n"

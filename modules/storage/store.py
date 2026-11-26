import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta
from threading import RLock
from uuid import uuid4

from core.clock import Clock, SystemClock
from core.ports import DomainError
from core.schemas import Action, Command, EmptyPayload, Event, PAYLOADS
from core.review import ReviewSubmission
from core.attribution import AttributionSubmission
from core.analytics import AnalyticsSubmission, AnalyticsSession, apply_corrections
from .maintenance import inspect_connection


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class SQLiteStore:
    """One host process owns the clock and serializes all score transactions."""

    def __init__(self, path: Path, clock: Clock | None = None):
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or SystemClock()
        self._lock = RLock()
        self._anchors: dict[str, float] = {}
        self._integrity_failed = False
        self._file = path.with_suffix(path.suffix + ".lock").open("a+b")
        try:
            if path.with_suffix(path.suffix + ".lock").stat().st_size == 0:
                self._file.write(b"0")
                self._file.flush()
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._file.close()
            raise RuntimeError("This database already has an owner. Run one server worker.") from None
        try:
            self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
            self.db.row_factory = sqlite3.Row
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError(f"Unsupported database schema {version}; do not downgrade this database")
            if version == 1:
                # Fail closed before changing journal settings, migrations or recovery.
                self.db.execute("BEGIN")
                try:
                    inspect_connection(self.db)
                finally:
                    self.db.execute("ROLLBACK")
            elif self.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone():
                raise RuntimeError("Unversioned nonempty database needs an explicit migration")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")
            self._schema()
            self._recover()
        except Exception:
            self.close()
            raise

    def _schema(self):
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            raise RuntimeError(f"Unsupported database schema {version}; do not downgrade this database")
        self.db.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY, state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                match_id TEXT NOT NULL REFERENCES matches(id),
                revision INTEGER NOT NULL,
                body TEXT NOT NULL,
                UNIQUE(match_id, revision)
            );
            CREATE TABLE IF NOT EXISTS commands (
                command_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                result TEXT NOT NULL
            );
            CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'Events are immutable'); END;
            CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'Events are immutable'); END;
            PRAGMA user_version=1;
            COMMIT;
        """)

    def _load(self, match_id):
        row = self.db.execute("SELECT state FROM matches WHERE id=?", (match_id,)).fetchone()
        if row is None:
            raise DomainError("Match not found", 404)
        state=self._defaults(json.loads(row["state"]))
        if state["last_event"] is None:
            latest=self.db.execute("SELECT body FROM events WHERE match_id=? ORDER BY revision DESC LIMIT 1",(match_id,)).fetchone()
            if latest:
                event=json.loads(latest["body"])
                state["last_event"]={k:event[k] for k in ("event_id","revision","type","recorded_at")}
        return state

    @staticmethod
    def _defaults(state):
        state.setdefault("review_mode", "manual")
        state.setdefault("play_epoch", 0)
        state.setdefault("restart_required", False)
        state.setdefault("last_event", None)
        state.setdefault("roster_revision", 0)
        state.setdefault("active_player_ids", [p["id"] for p in state["players"]])
        state.setdefault("attribution_suggestions", [])
        state.setdefault("analytics_sessions", [])
        return state

    def _expire_reviews(self):
        """Persist timeout transitions before snapshots/commands; silence never scores."""
        if self._integrity_failed:
            raise DomainError("Score integrity is quarantined; use verified recovery", 503)
        if self.db.in_transaction:
            return
        now=self.clock.utcnow()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for row in self.db.execute("SELECT state FROM matches").fetchall():
                state=self._defaults(json.loads(row["state"]))
                expired=[c for c in state["candidates"] if c["status"]=="pending_review" and
                    c.get("review_until") and datetime.fromisoformat(c["review_until"])<=now]
                if not expired:
                    continue
                for c in expired:
                    c.update(status="unresolved",resolution_reason="Review expired without an operator decision",resolved_at=now.isoformat())
                state["revision"]+=1
                event=self._event(state,f"expiry:{state['match_id']}:{state['revision']}","candidate_expired",
                    {"candidate_ids":[c["candidate_id"] for c in expired]},"review-timer","system")
                self._save(state,event)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def _retire_reviews(self,state,reason,*,all_pending=False):
        retired=[]
        for c in state["candidates"]:
            if c["status"]=="pending_review" and (c.get("review") or all_pending):
                c.update(status="unresolved",resolution_reason=reason,resolved_at=self.clock.utcnow().isoformat())
                retired.append(c["candidate_id"])
        state["play_epoch"]+=1
        return retired

    def _elapsed(self, state, now=None):
        elapsed = state["elapsed_seconds"]
        if state["status"] == "live":
            elapsed += max(0.0, (self.clock.monotonic() if now is None else now) - self._anchors[state["match_id"]])
        return elapsed

    def _view(self, state):
        state = json.loads(encode(state))
        state["elapsed_seconds"] = round(self._elapsed(state), 3)
        state["server_time"] = self.clock.utcnow().isoformat()
        state["duration_reached"] = state["elapsed_seconds"] >= state["duration_seconds"]
        return state

    def current(self):
        with self._lock:
            self._expire_reviews()
            row = self.db.execute("SELECT state FROM matches ORDER BY rowid DESC LIMIT 1").fetchone()
            return self._view(self._load(json.loads(row["state"])["match_id"])) if row else None

    def snapshot(self, match_id):
        with self._lock:
            self._expire_reviews()
            return self._view(self._load(match_id))

    def _event(self, state, command_id, kind, payload, actor, source="operator", occurred_at=None):
        now = self.clock.utcnow()
        return Event(
            event_id=str(uuid4()), command_id=command_id,
            match_id=state["match_id"], revision=state["revision"], type=kind,
            occurred_at=occurred_at or now, recorded_at=now, actor=actor, source=source,
            correlation_id=payload.get("candidate_id", payload.get("goal_id", command_id)),
            payload=payload,
        ).model_dump(mode="json")

    def _save(self, state, event):
        state["last_event"]={k:event[k] for k in ("event_id","revision","type","recorded_at")}
        self.db.execute("INSERT INTO matches(id,state) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
                        (state["match_id"], encode(state)))
        self.db.execute("INSERT INTO events(event_id,match_id,revision,body) VALUES (?,?,?,?)",
                        (event["event_id"], state["match_id"], state["revision"], encode(event)))

    def _recover(self):
        """Never infer active play across a restart or continue a lost monotonic clock."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for row in self.db.execute("SELECT state FROM matches").fetchall():
                state = self._defaults(json.loads(row["state"]))
                # A host restart retires every uncommitted review, including paused matches.
                retired=self._retire_reviews(state,"Host restarted; review this incident manually",all_pending=True)
                if state["status"] != "live" and retired:
                    state["revision"]+=1
                    event=self._event(state,str(uuid4()),"candidate_expired",{"candidate_ids":retired,"reason":"host_restart"},"host","system")
                    self._save(state,event)
                if state["status"] != "live":
                    continue
                state["status"] = "interrupted"
                state["revision"] += 1
                state["clock_reconciliation_required"] = True
                event = self._event(state, str(uuid4()), "clock_interrupted",
                                    {"last_known_elapsed_seconds": state["elapsed_seconds"],
                                     "last_boundary_at": state["clock_boundary_at"],"retired_candidate_ids":retired}, "host", "system")
                self._save(state, event)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def execute(self, match_id, command: Command, actor="operator", *, prepared_review: ReviewSubmission | None = None,
                prepared_attribution: AttributionSubmission | None = None, prepared_analytics: AnalyticsSubmission | None = None):
        payload = PAYLOADS.get(command.action, EmptyPayload).model_validate(command.payload).model_dump(mode="json")
        # Preserve existing idempotency fingerprints for unlinked manual goals.
        if command.action == Action.MANUAL_GOAL and payload.get("candidate_id") is None:
            payload.pop("candidate_id", None)
        if command.action == Action.CREATE and payload.get("active_player_ids") is None:
            payload.pop("active_player_ids", None)  # Keep existing create retry fingerprints.
        envelope = command.model_dump(mode="json")
        envelope["payload"] = payload
        fingerprint = hashlib.sha256(encode({"match_id": match_id, "actor": actor, **envelope}).encode()).hexdigest()
        with self._lock:
            if self._integrity_failed:
                raise DomainError("Score integrity failed; stop scoring and restore/reconcile with the runbook", 503)
            self._expire_reviews()
            self.db.execute("BEGIN IMMEDIATE")
            try:
                old = self.db.execute("SELECT * FROM commands WHERE command_id=?", (command.command_id,)).fetchone()
                if old:
                    if old["fingerprint"] != fingerprint:
                        raise DomainError("This command ID was already used for a different request")
                    result = json.loads(old["result"])
                    result["duplicate"] = True
                    self.db.execute("COMMIT")
                    return result
                command_time = self.clock.monotonic()
                if command.action == Action.CREATE:
                    if match_id is not None or command.expected_revision != 0:
                        raise DomainError("Create a new match with expected_revision 0", 422)
                    current = self.current()
                    if current and current["status"] != "ended":
                        raise DomainError("End the current match before creating another")
                    state = {"schema_version": 1, "match_id": str(uuid4()), "revision": 0,
                             "status": "ready", "mode": "manual", "score": {"orange": 0, "green": 0},
                             "teams": {"orange": payload["orange_name"], "green": payload["green_name"]},
                             "players": payload["players"], "duration_seconds": payload["duration_seconds"],
                             "elapsed_seconds": 0.0, "clock_reconciliation_required": False,
                             "clock_boundary_at": self.clock.utcnow().isoformat(),
                             "goal_mapping": {"goal_a": payload["goal_a_defending"],
                                              "goal_b": self._other(payload["goal_a_defending"])},
                             "goals": [], "candidates": [],
                             "active_player_ids":payload.get("active_player_ids", [p["id"] for p in payload["players"]])}
                    self._defaults(state)
                    kind = "match_created"
                else:
                    state = self._load(match_id)
                    if state["revision"] != command.expected_revision:
                        raise DomainError("The match changed. Refresh and review before trying again.")
                    state["elapsed_seconds"] = self._elapsed(state, command_time)
                    kind, payload = self._apply(state, command.action, payload, prepared_review=prepared_review,
                                                prepared_attribution=prepared_attribution,prepared_analytics=prepared_analytics)
                state["revision"] += 1
                state["clock_boundary_at"] = self.clock.utcnow().isoformat()
                event = self._event(state, command.command_id, kind, payload, actor, occurred_at=command.occurred_at)
                self._save(state, event)
                # The returned snapshot is the exact committed boundary, not a later live tick.
                snapshot = json.loads(encode(state))
                snapshot["server_time"] = self.clock.utcnow().isoformat()
                snapshot["duration_reached"] = state["elapsed_seconds"] >= state["duration_seconds"]
                result = {"event": event, "snapshot": snapshot, "duplicate": False}
                self.db.execute("INSERT INTO commands(command_id,fingerprint,result) VALUES (?,?,?)",
                                (command.command_id, fingerprint, encode(result)))
                self.db.execute("COMMIT")
                if state["status"] == "live":
                    self._anchors[state["match_id"]] = command_time
                else:
                    self._anchors.pop(state["match_id"], None)
                return result
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    @staticmethod
    def _other(team):
        return "green" if team == "orange" else "orange"

    @staticmethod
    def _require(state, *statuses):
        if state["status"] not in statuses:
            raise DomainError(f"This action is unavailable while the match is {state['status']}")

    def _goal(self, state, goal_id):
        goal = next((g for g in state["goals"] if g["goal_id"] == goal_id), None)
        if goal is None:
            raise DomainError("Goal not found", 404)
        if not goal["active"]:
            raise DomainError("This goal has already been undone")
        return goal

    def _attribution(self, state, goal, payload):
        roster = {p["id"]: p for p in state["players"]}
        for field in ("scorer_id", "assist_id"):
            player_id = payload[field]
            if player_id is not None and player_id not in roster:
                raise DomainError("Player is not in this match roster", 422)
        scorer = payload["scorer_id"]
        assist = payload["assist_id"]
        if scorer and roster[scorer]["team"] != (self._other(goal["team"]) if payload["own_goal"] else goal["team"]):
            raise DomainError("Scorer team does not match the goal / own-goal flag", 422)
        if assist and (payload["own_goal"] or roster[assist]["team"] != goal["team"] or assist == scorer):
            raise DomainError("Assist must be a different player on the scoring team; own goals have no assist", 422)
        goal.update({key: payload[key] for key in ("scorer_id", "assist_id", "own_goal")})

    @staticmethod
    def _retire_attribution(state,goal_id,reason):
        for item in state["attribution_suggestions"]:
            if item["goal_id"]==goal_id and item["status"]=="pending":
                item.update(status="superseded",resolution_reason=reason)

    def _apply(self, state, action, payload, *, prepared_review=None, prepared_attribution=None, prepared_analytics=None):
        if action == Action.DEMO_ANALYTICS:
            if prepared_analytics is None:
                raise DomainError("Dummy analytics is unavailable",422)
            submission = AnalyticsSubmission.model_validate(prepared_analytics.model_dump())
            session = submission.session
            if len(encode(submission.model_dump(mode="json")).encode()) > 131072 or len(state["analytics_sessions"]) >= 100:
                raise DomainError("Analytics session capacity reached",422)
            roster = session.rosters[0].roster
            if len(session.rosters)!=1 or (session.match_id,roster.revision)!=(state["match_id"],state["roster_revision"]) or roster.model_dump(mode="json")["players"]!=state["players"] or roster.active_player_ids!=state["active_player_ids"]:
                raise DomainError("Dummy analytics captured roster differs",422)
            if any(s["session"]["session_id"]==session.session_id for s in state["analytics_sessions"]):
                raise DomainError("Analytics session already exists")
            item=dict(session=session.model_dump(mode="json"),revision=0,corrections=[])
            state["analytics_sessions"].append(item)
            return "analytics_session_added",item
        if action == Action.CORRECT_ANALYTICS_TOUCH:
            item=next((s for s in state["analytics_sessions"] if s["session"]["session_id"]==payload["session_id"]),None)
            if item is None: raise DomainError("Analytics session not found",404)
            session=AnalyticsSession.model_validate(item["session"])
            touch=next((c for c in session.contacts if c.touch_id==payload["touch_id"]),None)
            if touch is None: raise DomainError("Analytics contact not found",404)
            roster=next(e.roster for e in reversed(session.rosters) if e.start_seconds<=touch.occurred_seconds)
            if payload["player_id"] is not None and payload["player_id"] not in roster.active_player_ids:
                raise DomainError("Corrected contact player must be active in captured roster",422)
            if len(item["corrections"])>=1000: raise DomainError("Analytics correction capacity reached",422)
            correction=dict(change=payload,revision=item["revision"]+1)
            apply_corrections(item["session"],[*item["corrections"],correction])
            item["revision"]+=1;item["corrections"].append(correction)
            return "analytics_touch_corrected",correction
        if action==Action.SUBSTITUTE_PLAYER:
            self._require(state,"ready","live","paused")
            roster={p["id"]:p for p in state["players"]}
            outgoing,incoming=payload["outgoing_id"],payload["incoming_id"]
            if outgoing not in roster or incoming not in roster or outgoing==incoming or roster[outgoing]["team"]!=roster[incoming]["team"]:
                raise DomainError("Substitution needs two distinct registered players on the same team",422)
            if outgoing not in state["active_player_ids"] or incoming in state["active_player_ids"]:
                raise DomainError("Outgoing player must be active and incoming player must be on the bench",422)
            state["active_player_ids"].remove(outgoing);state["active_player_ids"].append(incoming)
            state["roster_revision"]+=1
            return "player_substituted",{**payload,"roster_revision":state["roster_revision"],"active_player_ids":list(state["active_player_ids"])}
        if action==Action.DEMO_ATTRIBUTION:
            goal=self._goal(state,payload["goal_id"])
            if prepared_attribution is None:
                raise DomainError("Dummy attribution is unavailable",422)
            prepared_attribution=AttributionSubmission.model_validate(prepared_attribution.model_dump())
            if len(encode(prepared_attribution.model_dump(mode="json")).encode())>65536 or len(state["attribution_suggestions"])>=1000:
                raise DomainError("Attribution evidence capacity reached",422)
            suggestion=prepared_attribution.suggestion
            roster=prepared_attribution.sequence.roster
            expected_revision=goal.get("roster_revision",0)
            expected_active=goal.get("active_player_ids",[p["id"] for p in state["players"]])
            if (suggestion.match_id,suggestion.goal_id,suggestion.scoring_team,roster.revision)!=(state["match_id"],goal["goal_id"],goal["team"],expected_revision) or roster.model_dump(mode="json")["players"]!=state["players"] or set(roster.active_player_ids)!=set(expected_active):
                raise DomainError("Attribution identity/goal roster snapshot differs",422)
            if any(s["suggestion_id"]==suggestion.suggestion_id for s in state["attribution_suggestions"]):
                raise DomainError("Suggestion already exists")
            self._retire_attribution(state,goal["goal_id"],"Replaced by a newer suggestion")
            item=dict(suggestion_id=suggestion.suggestion_id,goal_id=goal["goal_id"],status="pending",
                base_attribution_revision=goal.get("attribution_revision",0),created_at=self.clock.utcnow().isoformat(),
                submission=prepared_attribution.model_dump(mode="json"))
            state["attribution_suggestions"].append(item)
            return "attribution_suggested",item
        if action in (Action.ACCEPT_ATTRIBUTION,Action.REJECT_ATTRIBUTION):
            goal=self._goal(state,payload["goal_id"])
            item=next((s for s in state["attribution_suggestions"] if s["suggestion_id"]==payload["suggestion_id"] and s["goal_id"]==goal["goal_id"]),None)
            if item is None:
                raise DomainError("Attribution suggestion not found",404)
            if item["status"]!="pending" or item["base_attribution_revision"]!=goal.get("attribution_revision",0):
                raise DomainError("Suggestion is resolved or attribution has changed")
            if action==Action.REJECT_ATTRIBUTION:
                item.update(status="rejected",resolved_at=self.clock.utcnow().isoformat())
                return "attribution_rejected",payload
            suggestion=item["submission"]["suggestion"]
            if suggestion["own_goal"] is None:
                raise DomainError("Own-goal outcome is uncertain; use manual player editing",422)
            attribution={key:suggestion[key] for key in ("scorer_id","assist_id","own_goal")}
            self._attribution(state,goal,attribution)
            goal["attribution_revision"]=goal.get("attribution_revision",0)+1
            goal["attribution_source"]="dummy_suggestion"
            item.update(status="accepted",resolved_at=self.clock.utcnow().isoformat())
            self._retire_attribution(state,goal["goal_id"],"Another suggestion was accepted")
            return "attribution_changed",{**payload,**attribution,"attribution_revision":goal["attribution_revision"],"evidence":"synthetic","assist_status":suggestion["assist_status"]}
        lifecycle = {Action.START: (("ready",), "live", "match_started"),
                     Action.PAUSE: (("live",), "paused", "match_paused"),
                     Action.RESUME: (("paused",), "live", "match_resumed"),
                     Action.END: (("ready", "live", "paused", "interrupted"), "ended", "match_ended")}
        if action in lifecycle:
            statuses, next_status, event = lifecycle[action]
            self._require(state, *statuses)
            retired=self._retire_reviews(state,f"Match {next_status}",all_pending=action==Action.END)
            state["status"] = next_status
            if action == Action.END:
                for candidate in state["candidates"]:
                    if candidate["status"] == "pending_review":
                        candidate["status"] = "unresolved"
            return event, {"elapsed_seconds": state["elapsed_seconds"],"retired_candidate_ids":retired,"play_epoch":state["play_epoch"]}
        if action == Action.RECONCILE_CLOCK:
            self._require(state, "interrupted")
            state["elapsed_seconds"] = payload["elapsed_seconds"]
            state["clock_reconciliation_required"] = False
            state["status"] = "paused"
            return "clock_reconciled", payload
        if action == Action.SWAP_ENDS:
            self._require(state, "ready", "paused")
            if any(c["status"] == "pending_review" for c in state["candidates"]):
                raise DomainError("Resolve pending candidates before changing ends")
            state["goal_mapping"] = {end: self._other(team) for end, team in state["goal_mapping"].items()}
            self._retire_reviews(state,"Goal ends changed")
            return "ends_changed", {"goal_mapping": state["goal_mapping"],"play_epoch":state["play_epoch"]}
        if action == Action.SET_REVIEW_MODE:
            self._require(state,"ready","paused")
            if any(c["status"]=="pending_review" for c in state["candidates"]):
                raise DomainError("Resolve pending incidents before changing review mode")
            if state["review_mode"]==payload["mode"]:
                raise DomainError("This review mode is already selected")
            state["review_mode"]=payload["mode"]
            state["restart_required"]=False
            self._retire_reviews(state,"Review mode changed")
            return "review_mode_changed",{"mode":payload["mode"],"play_epoch":state["play_epoch"]}
        if action == Action.RESTART_PLAY:
            self._require(state,"live")
            if state["review_mode"]!="demo_review":
                raise DomainError("Restart gate is only active in dummy review mode")
            retired=self._retire_reviews(state,"Operator started a new play",all_pending=True)
            state["restart_required"]=False
            return "play_restarted",{"play_epoch":state["play_epoch"],"retired_candidate_ids":retired}
        if action == Action.DEMO_INCIDENT:
            self._require(state,"live")
            if state["review_mode"]!="demo_review" or state["restart_required"]:
                raise DomainError("Select dummy review mode and restart play before adding an incident")
            if prepared_review is None:
                raise DomainError("Dummy evidence must come from application composition",422)
            prepared_review=ReviewSubmission.model_validate(prepared_review)
            fused=prepared_review.candidate
            if fused.match_id!=state["match_id"] or fused.goal_end!=payload["goal_end"] or fused.team!=self._other(state["goal_mapping"][fused.goal_end]):
                raise DomainError("Review provenance/end/team does not match current match",422)
            if len(state["candidates"])>=1000:
                raise DomainError("Review capacity reached; end/export this prototype match",422)
            action=Action.CREATE_CANDIDATE
            payload={"candidate_id":fused.candidate_id,"goal_end":fused.goal_end,
                "reason":"Dummy crossing supported by impact; operator confirmation required" if fused.confirmation=="shadow_rule" else
                         "Dummy evidence is uncertain; operator review required",
                "review":prepared_review.model_dump(mode="json"),"play_epoch":state["play_epoch"],
                "created_at":self.clock.utcnow().isoformat(),
                "review_until":(self.clock.utcnow()+timedelta(seconds=prepared_review.review_seconds)).isoformat()}
        if action == Action.CREATE_CANDIDATE:
            self._require(state, "live")
            if any(c["candidate_id"] == payload["candidate_id"] for c in state["candidates"]):
                raise DomainError("This candidate already exists")
            payload.update(team=self._other(state["goal_mapping"][payload["goal_end"]]), status="pending_review")
            payload.update(roster_revision=state["roster_revision"],active_player_ids=list(state["active_player_ids"]))
            state["candidates"].append(dict(payload))
            return "candidate_created", payload
        if action in (Action.CONFIRM_CANDIDATE, Action.REJECT_CANDIDATE):
            if action == Action.CONFIRM_CANDIDATE:
                self._require(state, "live")
            else:
                self._require(state, "live", "paused")
            candidate = next((c for c in state["candidates"] if c["candidate_id"] == payload["candidate_id"]), None)
            if candidate is None:
                raise DomainError("Candidate not found", 404)
            if candidate["status"] != "pending_review":
                raise DomainError("This candidate has already been resolved")
            if candidate.get("review") and candidate["play_epoch"]!=state["play_epoch"]:
                raise DomainError("This incident belongs to a previous play")
            if action==Action.CONFIRM_CANDIDATE and state["review_mode"]=="demo_review" and state["restart_required"]:
                raise DomainError("Restart play before confirming another incident")
            if action == Action.REJECT_CANDIDATE:
                candidate["status"] = "rejected"
                return "goal_rejected", payload
            candidate["status"] = "confirmed"
            payload.update(team=candidate["team"], scorer_id=None, assist_id=None, own_goal=False)
        if action in (Action.MANUAL_GOAL, Action.CONFIRM_CANDIDATE):
            self._require(state, "live")
            if state["review_mode"]=="demo_review" and state["restart_required"]:
                raise DomainError("Restart play before recording another goal")
            if action == Action.MANUAL_GOAL and payload.get("candidate_id"):
                candidate = next((c for c in state["candidates"] if c["candidate_id"] == payload["candidate_id"]), None)
                if candidate is None:
                    raise DomainError("Candidate not found", 404)
                if candidate["status"] != "pending_review":
                    raise DomainError("This candidate has already been resolved")
                if candidate["team"] != payload["team"]:
                    raise DomainError("Manual goal team disagrees with candidate end mapping", 422)
                candidate["status"] = "confirmed"
            goal = {**payload, "goal_id": str(uuid4()), "active": True,
                    "elapsed_seconds": state["elapsed_seconds"], "confirmation": "operator", "attribution_revision":0,"attribution_source":"operator"}
            source_roster=next((c for c in state["candidates"] if c["candidate_id"]==payload.get("candidate_id")),state)
            goal.update(roster_revision=source_roster.get("roster_revision",0),active_player_ids=list(source_roster.get("active_player_ids",[p["id"] for p in state["players"]])))
            self._attribution(state, goal, payload)
            state["goals"].append(goal)
            state["score"][goal["team"]] += 1
            if state["review_mode"]=="demo_review":
                state["restart_required"]=True
            return "goal_confirmed", goal
        if action == Action.UNDO_GOAL:
            goal = self._goal(state, payload["goal_id"])
            goal["active"] = False
            state["score"][goal["team"]] -= 1
            self._retire_attribution(state,goal["goal_id"],"Goal was undone")
            return "correction_applied", {**payload, "correction": "goal_undone", "team": goal["team"]}
        if action == Action.ATTRIBUTE_GOAL:
            goal = self._goal(state, payload["goal_id"])
            self._attribution(state, goal, payload)
            goal["attribution_revision"]=goal.get("attribution_revision",0)+1
            goal["attribution_source"]="operator"
            self._retire_attribution(state,goal["goal_id"],"Operator edited player attribution")
            return "attribution_changed", {**payload,"attribution_revision":goal["attribution_revision"]}
        raise DomainError("Unsupported command", 422)

    def export(self, match_id):
        with self._lock:
            self._expire_reviews()
            # Freeze at the last committed boundary so exports are deterministic.
            state = self._load(match_id)
            events = [json.loads(row[0]) for row in self.db.execute(
                "SELECT body FROM events WHERE match_id=? ORDER BY revision", (match_id,))]
            return {"schema_version": 1, "snapshot": state, "events": events}

    def integrity(self):
        with self._lock:
            if self._integrity_failed:
                raise DomainError("Score integrity is quarantined until verified recovery", 503)
            self.db.execute("BEGIN")
            try:
                return inspect_connection(self.db)
            except Exception:
                self._integrity_failed = True
                raise
            finally:
                self.db.execute("ROLLBACK")

    def close(self):
        with self._lock:
            if hasattr(self, "db"):
                self.db.close()
            if not self._file.closed:
                self._file.close()

"""Bounded display presence and instrumented acknowledgement telemetry, not score authority."""
from collections import OrderedDict, deque
from datetime import datetime
from threading import RLock
from uuid import uuid4

from core.ports import DomainError


class DisplayMonitor:
    def __init__(self,clock):
        self.clock,self.lock=clock,RLock()
        self.connections=OrderedDict()
        self.samples=deque(maxlen=256)

    def open(self):
        with self.lock:
            if sum(c["connected"] for c in self.connections.values())>=32:
                raise DomainError("Display connection capacity reached",503)
            while len(self.connections)>=64:
                old=next((key for key,c in self.connections.items() if not c["connected"]),None)
                if old is None:
                    break
                self.connections.pop(old)
            identity=str(uuid4())
            self.connections[identity]=dict(connected=True,opened_at=self.clock.utcnow(),last_ack=None,
                last_ack_match=None,last_ack_revision=None,last_sent_match=None,last_sent_revision=None,history=OrderedDict())
            return identity

    def sent(self,identity,snapshot):
        if snapshot is None:
            return
        with self.lock:
            c=self.connections[identity]
            if c["last_sent_match"]!=snapshot["match_id"]:
                c["history"].clear()
                c.update(last_ack=None,last_ack_match=None,last_ack_revision=None)
            c.update(last_sent_match=snapshot["match_id"],last_sent_revision=snapshot["revision"])
            event=snapshot.get("last_event")
            if event:
                key=(snapshot["match_id"],snapshot["revision"],event["event_id"])
                c["history"].setdefault(key,dict(event=event,acknowledged=False))
                while len(c["history"])>16:
                    c["history"].popitem(last=False)

    def acknowledge(self,identity,message):
        if message.get("type")!="rendered" or isinstance(message.get("revision"),bool) or not isinstance(message.get("revision"),int):
            return
        with self.lock:
            c=self.connections[identity]
            key=(message.get("match_id"),message["revision"],message.get("event_id"))
            try:
                record=c["history"].get(key)
            except TypeError:
                return
            if record is None:
                return
            if c["last_ack_match"]==key[0] and c["last_ack_revision"] is not None and key[1]<c["last_ack_revision"]:
                return
            c.update(last_ack=self.clock.monotonic(),last_ack_match=key[0],last_ack_revision=key[1])
            if record["acknowledged"]:
                return
            record["acknowledged"]=True
            event=record["event"]
            recorded=datetime.fromisoformat(event["recorded_at"])
            if event["type"] in ("goal_confirmed","correction_applied") and recorded>=c["opened_at"]:
                self.samples.append(dict(match_id=key[0],revision=key[1],event_id=key[2],
                    commit_to_render_ack_seconds=max(0.,(self.clock.utcnow()-recorded).total_seconds())))

    def close(self,identity):
        with self.lock:
            if identity in self.connections:
                self.connections[identity]["connected"]=False

    def status(self):
        with self.lock:
            records=[]
            for identity,c in self.connections.items():
                age=None if c["last_ack"] is None else max(0.,self.clock.monotonic()-c["last_ack"])
                state="disconnected" if not c["connected"] else "waiting_for_render" if age is None else "stale" if age>3 else "rendering"
                if state=="rendering" and c["last_ack_revision"]!=c["last_sent_revision"]:
                    state="awaiting_update"
                records.append(dict(connection_id=identity,state=state,last_ack_age_seconds=age,
                    match_id=c["last_ack_match"],revision=c["last_ack_revision"],last_sent_revision=c["last_sent_revision"]))
            return dict(connections=records,connected=sum(c["connected"] for c in self.connections.values()),
                rendered_samples=list(self.samples),physical_display_verified=False,
                measurement="Commit-to-double-animation-frame acknowledgement receipt; includes network return; client acknowledgements are untrusted telemetry")

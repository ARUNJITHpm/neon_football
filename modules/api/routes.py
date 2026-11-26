import asyncio
import secrets
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import ValidationError

from core.bus import EventBus
from core.ports import DomainError, ScoreStore
from core.schemas import Action, Command
from core.capture import CaptureService, ClipRequest
from core.review import DisplayService, ReviewService
from core.attribution import AttributionService
from core.analytics import AnalyticsService


STATIC = Path(__file__).parent / "static"


def public_snapshot(snapshot):
    if snapshot is None:
        return None
    return {key:snapshot[key] for key in ("schema_version","match_id","revision","status","mode","review_mode",
        "score","teams","duration_seconds","elapsed_seconds","duration_reached","server_time","clock_boundary_at",
        "clock_reconciliation_required","restart_required","last_event") if key in snapshot}


def router(store: Callable[[], ScoreStore], key: Callable[[], str], bus: EventBus, venue_name: str, duration: int,
           capture: Callable[[], CaptureService | None] = lambda: None,
           capture_error: Callable[[], str | None] = lambda: None,
           review: Callable[[], ReviewService | None] = lambda: None,
           displays: Callable[[], DisplayService | None] = lambda: None,
           report: Callable[[dict],dict] | None = None,
           text_report: Callable[[dict],str] | None = None,
           demo_enabled: bool = True,
           operations: Callable[[], dict] | None = None,
           attribution: Callable[[], AttributionService | None] = lambda: None,
           analytics: Callable[[], AnalyticsService | None] = lambda: None) -> APIRouter:
    routes = APIRouter()

    def authorized(request: Request):
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            raise HTTPException(403, "Use the operator page on this server")
        authorization = request.headers.get("authorization", "")
        expected = f"Bearer {key()}"
        if not secrets.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "Enter a valid operator key", headers={"WWW-Authenticate": "Bearer"})
        encoded_actor = request.headers.get("x-operator-name", "operator")
        if len(encoded_actor) > 720:
            raise HTTPException(422, "Operator name must be 1–60 characters")
        try:
            actor = unquote(encoded_actor, encoding="utf-8", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise HTTPException(422, "Operator name encoding is invalid") from exc
        if not actor or len(actor) > 60:
            raise HTTPException(422, "Operator name must be 1–60 characters")
        return actor

    def execute(match_id, command, actor):
        try:
            prepared=None
            prepared_attribution=None
            prepared_analytics=None
            if command.action==Action.DEMO_INCIDENT and demo_enabled and review():
                prepared=review().prepare(match_id,command,store().snapshot(match_id))
            if command.action==Action.SET_REVIEW_MODE and command.payload.get("mode")=="demo_review" and not demo_enabled:
                raise DomainError("Dummy review is disabled in server configuration",422)
            if command.action==Action.DEMO_ATTRIBUTION and demo_enabled and attribution():
                prepared_attribution=attribution().prepare(match_id,command,store().snapshot(match_id))
            if command.action==Action.DEMO_ANALYTICS and demo_enabled and analytics():
                prepared_analytics=analytics().prepare(match_id,command,store().snapshot(match_id))
            result = store().execute(match_id, command, actor,prepared_review=prepared,prepared_attribution=prepared_attribution,
                                     prepared_analytics=prepared_analytics)
        except DomainError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        except ValidationError as exc:
            raise HTTPException(422, [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]) from exc
        if not result["duplicate"]:
            bus.publish(result["event"])
        return result

    @routes.get("/", include_in_schema=False)
    @routes.get("/operator", include_in_schema=False)
    def operator():
        return FileResponse(STATIC / "operator.html")

    @routes.get("/scoreboard", include_in_schema=False)
    def scoreboard():
        return FileResponse(STATIC / "scoreboard.html")

    @routes.get("/health")
    def health():
        return {"status": "ok", "mode": "manual", "schema_version": 1}

    @routes.get("/api/v1/config")
    def configuration():
        return {"venue_name": venue_name, "default_duration_seconds": duration, "mode": "manual","demo_review_enabled":demo_enabled}

    @routes.post("/api/v1/operator/check")
    def check_operator(actor: str = Depends(authorized)):
        return {"actor": actor, "authorized": True}

    @routes.get("/api/v1/capture/status")
    def capture_health(actor: str = Depends(authorized)):
        service = capture()
        return service.status() if service else {"enabled": False, "error": capture_error()}

    @routes.post("/api/v1/capture/clips", status_code=202)
    def capture_clip(body: ClipRequest, actor: str = Depends(authorized)):
        service = capture()
        if service is None:
            raise HTTPException(503, "Capture is disabled or unavailable")
        try:
            return service.request_clip(body)
        except DomainError as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @routes.get("/api/v1/capture/clips/{clip_id}")
    def capture_clip_status(clip_id: str, actor: str = Depends(authorized)):
        service = capture()
        if service is None:
            raise HTTPException(503, "Capture is disabled or unavailable")
        try:
            return service.clip_status(clip_id)
        except DomainError as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @routes.get("/api/v1/capture/clips/{clip_id}/file")
    def capture_clip_file(clip_id: str, actor: str = Depends(authorized)):
        service=capture()
        if service is None:
            raise HTTPException(503,"Capture is disabled or unavailable")
        try:
            path=service.clip_file(clip_id)
        except DomainError as exc:
            raise HTTPException(exc.status,exc.message) from exc
        return FileResponse(path,media_type="application/octet-stream",filename="review-clip.mjpeg")

    @routes.get("/api/v1/displays/status")
    def display_status(actor: str = Depends(authorized)):
        service=displays()
        return service.status() if service else {"connected":0,"connections":[],"rendered_samples":[],"physical_display_verified":False}

    @routes.get("/api/v1/operations/status")
    def operations_status(actor: str = Depends(authorized)):
        if operations is None:
            raise HTTPException(503,"Operations status unavailable")
        return operations()

    @routes.get("/api/v1/operator/matches/current")
    def operator_current(actor: str = Depends(authorized)):
        try:
            return {"match":store().current()}
        except DomainError as exc:
            raise HTTPException(exc.status,exc.message) from exc

    @routes.get("/api/v1/matches/current")
    def current():
        try:
            return {"match": public_snapshot(store().current())}
        except DomainError as exc:
            raise HTTPException(exc.status,exc.message) from exc

    @routes.get("/api/v1/matches/{match_id}")
    def snapshot(match_id: str):
        try:
            return public_snapshot(store().snapshot(match_id))
        except DomainError as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @routes.post("/api/v1/matches", status_code=201)
    def create(command: Command, actor: str = Depends(authorized)):
        if command.action != Action.CREATE:
            raise HTTPException(422, "Use action create for a new match")
        return execute(None, command, actor)

    @routes.post("/api/v1/matches/{match_id}/commands")
    def command(match_id: str, command: Command, actor: str = Depends(authorized)):
        if command.action == Action.CREATE:
            raise HTTPException(422, "Create matches at /api/v1/matches")
        return execute(match_id, command, actor)

    @routes.get("/api/v1/matches/{match_id}/events")
    def events(match_id: str, actor: str = Depends(authorized)):
        try:
            return store().export(match_id)["events"]
        except DomainError as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @routes.get("/api/v1/matches/{match_id}/export")
    def export(match_id: str, actor: str = Depends(authorized)):
        try:
            result = store().export(match_id)
        except DomainError as exc:
            raise HTTPException(exc.status, exc.message) from exc
        return JSONResponse(result, headers={"Content-Disposition": f'attachment; filename="match-{result["snapshot"]["match_id"]}.json"'})

    @routes.get("/api/v1/matches/{match_id}/report")
    def match_report(match_id: str, actor: str = Depends(authorized)):
        if report is None:
            raise HTTPException(503,"Report service unavailable")
        try:
            return report(store().export(match_id))
        except DomainError as exc:
            raise HTTPException(exc.status,exc.message) from exc

    @routes.get("/api/v1/matches/{match_id}/report.txt")
    def match_text(match_id: str, actor: str = Depends(authorized)):
        if report is None or text_report is None:
            raise HTTPException(503,"Report service unavailable")
        try:
            text=text_report(report(store().export(match_id)))
        except DomainError as exc:
            raise HTTPException(exc.status,exc.message) from exc
        return PlainTextResponse(text,headers={"Content-Disposition":'attachment; filename="neon-match-report.txt"'})

    @routes.get("/api/v1/matches/{match_id}/candidates/{candidate_id}/clip")
    def candidate_clip_status(match_id: str,candidate_id: str,actor: str = Depends(authorized)):
        try:
            snapshot=store().snapshot(match_id)
            candidate=next((c for c in snapshot["candidates"] if c["candidate_id"]==candidate_id),None)
            if candidate is None:
                raise DomainError("Candidate not found",404)
            return {"candidate_id":candidate_id,"clips":candidate.get("review",{}).get("clips",[])}
        except DomainError as exc:
            raise HTTPException(exc.status,exc.message) from exc

    @routes.get("/api/v1/matches/{match_id}/candidates/{candidate_id}/clip/file")
    def candidate_clip_file(match_id: str,candidate_id: str,actor: str = Depends(authorized)):
        try:
            snapshot=store().snapshot(match_id)
            candidate=next((c for c in snapshot["candidates"] if c["candidate_id"]==candidate_id),None)
            if candidate is None or review() is None:
                raise DomainError("Candidate media unavailable",404)
            path=review().clip_file(candidate)
        except DomainError as exc:
            raise HTTPException(exc.status,exc.message) from exc
        return FileResponse(path,media_type="video/mp4",filename="generated-review-pattern.mp4",content_disposition_type="inline")

    @routes.websocket("/ws/matches/current")
    async def updates(websocket: WebSocket):
        await stream(websocket,private=False)

    @routes.websocket("/ws/operator/current")
    async def operator_updates(websocket: WebSocket):
        await stream(websocket,private=True)

    async def stream(websocket,*,private):
        origin = websocket.headers.get("origin")
        scheme = "https" if websocket.url.scheme == "wss" else "http"
        if origin and origin != f"{scheme}://{websocket.headers.get('host')}":
            await websocket.close(code=1008)
            return
        await websocket.accept()
        if private:
            try:
                message=await asyncio.wait_for(websocket.receive_json(),timeout=3)
                token=message.get("operator_key","") if isinstance(message,dict) else ""
                if not isinstance(token,str) or len(token)>256 or not secrets.compare_digest(token.encode(),key().encode()):
                    await websocket.close(code=1008)
                    return
            except (asyncio.TimeoutError,ValueError,WebSocketDisconnect,RuntimeError):
                await websocket.close(code=1008)
                return
        monitor=displays() if not private else None
        connection_id=None
        if monitor:
            try:
                connection_id=monitor.open()
            except DomainError:
                await websocket.close(code=1013)
                return
        # Current-state delivery is authoritative: missed messages recover on reconnect.
        # Timed snapshots also keep the physical display's clock aligned to the host.
        try:
            while True:
                match = await asyncio.to_thread(store().current)
                snapshot=match if private else public_snapshot(match)
                if monitor:
                    monitor.sent(connection_id,snapshot)
                envelope={"type":"snapshot","match":snapshot}
                if match:
                    envelope.update(match_id=match["match_id"],revision=match["revision"],
                        event_id=match.get("last_event",{}).get("event_id") if match.get("last_event") else None,
                        server_clock={k:match[k] for k in ("status","elapsed_seconds","server_time","clock_boundary_at")})
                await websocket.send_json(envelope)
                try:
                    message = await asyncio.wait_for(websocket.receive(), timeout=0.5)
                    if message["type"] == "websocket.disconnect":
                        break
                    if monitor and message.get("text") and len(message["text"])<=4096:
                        import json
                        try:
                            ack=json.loads(message["text"])
                            if isinstance(ack,dict):
                                monitor.acknowledge(connection_id,ack)
                        except (ValueError,TypeError):
                            pass
                except asyncio.TimeoutError:
                    pass
        except DomainError:
            await websocket.close(code=1011)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if monitor and connection_id:
                monitor.close(connection_id)

    return routes

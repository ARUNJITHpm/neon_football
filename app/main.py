from contextlib import asynccontextmanager
import asyncio
from queue import Empty
import hashlib

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.settings import Settings, load_settings
from core.bus import EventBus
from core.capture import ClipRequest
from modules.api.routes import STATIC, router
from modules.storage.store import SQLiteStore
from modules.capture.manager import CaptureManager
from app.review import DummyReview
from app.display import DisplayMonitor
from app.reports import enriched_report, enriched_text
from app.operations import Operations
from app.attribution import DummyAttribution
from app.analytics import DummyAnalytics


def create_app(settings: Settings | None = None, *, operator_key: str | None = None, clock=None) -> FastAPI:
    settings = settings or load_settings()
    if settings.automatic_scoring_enabled:
        raise ValueError("Automatic scoring is unavailable in this milestone")
    bus = EventBus()

    async def goal_clips(manager, channel):
        try:
            while True:
                try:
                    event = channel.get_nowait()
                except Empty:
                    await asyncio.sleep(0.05)
                    continue
                if event["type"] == "resync_required":
                    manager.incident(None, "clip_notification_overflow")
                    bus.unsubscribe(channel)
                    channel = bus.subscribe()
                elif event["type"] == "goal_confirmed":
                    for camera in settings.cameras:
                        try:
                            # Receipt window around processing the committed manual goal;
                            # never represent the operator click as physical crossing time.
                            clip_id = hashlib.sha256(f"{event['event_id']}:{camera.id}".encode()).hexdigest()
                            await asyncio.to_thread(manager.request_clip, ClipRequest(camera_id=camera.id, clip_id=clip_id, event_id=event['event_id']))
                        except Exception:
                            manager.incident(camera.id, "goal_clip_request_failed", event_id=event["event_id"])
        finally:
            bus.unsubscribe(channel)

    @asynccontextmanager
    async def lifespan(application):
        store = SQLiteStore(settings.database_path, clock)
        manager = None
        task = None
        channel = None
        operations_task = None
        try:
            application.state.operator_key = operator_key or settings.operator_key()
            application.state.store = store
            application.state.review = DummyReview(settings.demo_review_enabled)
            application.state.attribution = DummyAttribution()
            application.state.analytics = DummyAnalytics()
            application.state.displays = DisplayMonitor(store.clock)
            application.state.capture = None
            application.state.capture_error = None
            if settings.capture.enabled:
                try:
                    manager = CaptureManager(settings.cameras, settings.capture)
                    manager.start()
                    application.state.capture = manager
                    channel = bus.subscribe()
                    task = asyncio.create_task(goal_clips(manager, channel))
                except Exception:
                    application.state.capture_error = "Capture startup failed; manual scoring remains available"
                    if manager:
                        manager.close()
                    manager = None
            application.state.operations = Operations(settings, store, capture=lambda: application.state.capture,
                displays=lambda: application.state.displays, clip_task=lambda: task)
            async def integrity_monitor():
                while True:
                    await asyncio.to_thread(application.state.operations.check_integrity)
                    await asyncio.sleep(settings.operations.integrity_interval_seconds)
            operations_task = asyncio.create_task(integrity_monitor())
            yield
        finally:
            if operations_task:
                operations_task.cancel()
                try:
                    await operations_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass  # Cleanup must still release capture and the database owner.
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass  # A failed clip consumer is health-reported; do not leak the owner.
            if channel:
                bus.unsubscribe(channel)
            try:
                if manager:
                    await asyncio.to_thread(manager.close)
            finally:
                store.close()

    application = FastAPI(title="Neon Score", version="0.1.0", lifespan=lifespan)
    application.include_router(router(lambda: application.state.store, lambda: application.state.operator_key,
                                      bus, settings.venue_name, settings.default_duration_seconds,
                                      lambda: application.state.capture,
                                      lambda: application.state.capture_error,
                                      lambda: application.state.review,
                                      lambda: application.state.displays,
                                      enriched_report,enriched_text,settings.demo_review_enabled,
                                      lambda: application.state.operations.status(),
                                      lambda: application.state.attribution,
                                      lambda: application.state.analytics))
    application.mount("/static", StaticFiles(directory=STATIC), name="static")

    @application.middleware("http")
    async def browser_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        if request.url.path not in ("/docs", "/redoc"):
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; img-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    return application

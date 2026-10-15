"""Local FastAPI application serving live inference and Python-only policy replay."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from secrets import randbelow
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse, Response, StreamingResponse

from . import waldo
from .batch import BatchStreamingResponse, stream_batch
from .batch_models import BatchRequest, JiraTicket
from .catalog import SCENARIOS
from .models import Decision, EvaluateRequest, Evaluation, Health, PolicyRequest, Scenario
from .policy import decide
from .runner.session import play
from .runner.world import Challenge, Mode
from .service import JevError, Settings, evaluate
from .snake import play as play_snake
from .tickets import TICKETS


def get_scenario(scenario_id: str) -> Scenario:
    """Resolve a server-owned preset instead of accepting arbitrary model instructions."""
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Unknown scenario.")
    return scenario


def create_app(
    settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    """Create an isolated application with a lifespan-managed outbound connection pool."""
    config = settings if settings is not None else Settings()
    active_client: httpx.AsyncClient | None = None
    runner_active = False
    snake_active = False
    waldo_active = False

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        """Reuse outbound connections and close them when the application stops."""
        nonlocal active_client
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10),
            headers={"Content-Type": "application/json"},
            transport=transport,
        ) as client:
            active_client = client
            yield
        active_client = None

    application = FastAPI(title="Jev Decision Lab", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )

    def get_client() -> httpx.AsyncClient:
        """Provide the app's initialized TypeSafe transport."""
        if active_client is None:
            raise HTTPException(status_code=503, detail="The server is starting. Try again.")
        return active_client

    @application.get("/api/health")
    def health() -> Health:
        """Expose readiness without ever returning the credential."""
        return Health(
            configured=bool(config.typesafe_api_key.get_secret_value()), model=config.typesafe_model
        )

    @application.get("/api/scenarios")
    def scenarios() -> list[Scenario]:
        """Return editable text examples and the exact question definitions."""
        return list(SCENARIOS.values())

    @application.post("/api/evaluate")
    async def evaluate_state(
        request: EvaluateRequest, client: Annotated[httpx.AsyncClient, Depends(get_client)]
    ) -> Evaluation:
        """Run one real Jev request; errors never silently fall back to invented results."""
        try:
            return await evaluate(client, config, get_scenario(request.scenario_id), request)
        except JevError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from None

    @application.post("/api/policy")
    def replay_policy(request: PolicyRequest) -> Decision:
        """Change the threshold against an existing response without spending model tokens."""
        try:
            return decide(get_scenario(request.scenario_id), request.response, request.threshold)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @application.get("/api/triage/tickets")
    def jira_tickets() -> list[JiraTicket]:
        """Return the twenty fictional Jira issues available for a live batch."""
        return TICKETS

    @application.post("/api/triage/batch")
    async def evaluate_batch(
        request: BatchRequest, client: Annotated[httpx.AsyncClient, Depends(get_client)]
    ) -> StreamingResponse:
        """Stream a bounded batch; the browser can stop work by closing the response."""
        if not config.typesafe_api_key.get_secret_value():
            raise HTTPException(status_code=503, detail="Configure TYPESAFE_API_KEY on the server.")
        available = {ticket.id: ticket for ticket in TICKETS}
        if any(ticket_id not in available for ticket_id in request.ticket_ids):
            raise HTTPException(status_code=404, detail="The batch contains an unknown ticket.")
        selected = [available[ticket_id] for ticket_id in request.ticket_ids]
        return BatchStreamingResponse(stream_batch(client, config, request, selected))

    @application.websocket("/api/runner/play")
    async def runner(
        socket: WebSocket,
        seed: Annotated[int, Query(ge=0, le=2147483647)],
        mode: Mode = "jev",
        challenge: Challenge = "timed",
        pace: Annotated[float, Query(ge=0.5, le=2, allow_inf_nan=False)] = 1.0,
    ) -> None:
        """Keep one local game active and reject unrelated browser origins."""
        nonlocal runner_active
        origin = socket.headers.get("origin")
        allowed = {
            f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (8000, 5173)
        }
        if origin is not None and origin not in allowed:
            await socket.close(code=1008)
            return
        await socket.accept()
        error = None
        if runner_active:
            error = "A run is already active. Stop it in the other tab first."
        elif mode == "jev" and not config.typesafe_api_key.get_secret_value():
            error = "Configure TYPESAFE_API_KEY on the server, or try manual mode."
        elif active_client is None:
            error = "The server is starting. Try again."
        if error is not None or active_client is None:
            await socket.send_json({"type": "error", "message": error})
            await socket.close(code=1008)
            return
        runner_active = True
        try:
            await play(socket, active_client, config, seed, mode, pace, challenge)
        finally:
            runner_active = False

    @application.websocket("/api/snake/play")
    async def snake(
        socket: WebSocket,
        seed: Annotated[int, Query(ge=0, le=2147483647)],
    ) -> None:
        """Run one answer-driven Snake game with server-only credentials."""
        nonlocal snake_active
        allowed = {
            f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (8000, 5173)
        }
        if socket.headers.get("origin") not in allowed | {None}:
            await socket.close(code=1008)
            return
        await socket.accept()
        error = None
        if snake_active:
            error = "A Snake game is already active. Stop it in the other tab first."
        elif not config.typesafe_api_key.get_secret_value():
            error = "Configure TYPESAFE_API_KEY on the server."
        elif active_client is None:
            error = "The server is starting. Try again."
        if error is not None or active_client is None:
            await socket.send_json({"type": "error", "message": error})
            await socket.close(code=1008)
            return
        snake_active = True
        try:
            await play_snake(socket, active_client, config, seed)
        finally:
            snake_active = False

    @application.get("/api/waldo/catalog")
    def waldo_catalog(mode: waldo.Mode = "sprint") -> dict[str, object]:
        """Return solution-free image metadata for preloading before the match clock starts."""
        return {
            "configured": bool(config.typesafe_api_key.get_secret_value()),
            "model": waldo.MODEL,
            "images": [p.public() for p in waldo.playable_puzzles(mode)],
        }

    @application.get("/api/waldo/references")
    def waldo_references(mode: waldo.Mode = "sprint") -> dict[str, object]:
        """Publish reviewed solutions for the dedicated inspection page, never model requests."""
        return {
            "head_coverage": waldo.HEAD_COVERAGE,
            "box_precision": waldo.BOX_PRECISION,
            "padding": waldo.BODY_PADDING,
            "answer_padding": waldo.ANSWER_PADDING,
            "images": [p.review() for p in waldo.playable_puzzles(mode)],
        }

    @application.get("/api/waldo/images/{puzzle_id}")
    def waldo_image(puzzle_id: str) -> Response:
        """Serve the exact, unannotated JPEG passed to the Box question."""
        try:
            content = waldo.image_bytes(puzzle_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Bild nicht gefunden.") from None
        return Response(
            content, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"}
        )

    @application.put("/api/waldo/references/{puzzle_id}")
    async def correct_waldo_reference(
        puzzle_id: str, correction: waldo.ReferenceCorrection
    ) -> dict[str, object]:
        """Save local corrections between matches so a running game's rules cannot change."""
        if waldo_active:
            raise HTTPException(409, "Bitte das laufende Duell zuerst beenden.")
        puzzle = waldo.BY_ID.get(puzzle_id)
        if puzzle is None:
            raise HTTPException(404, "Bild nicht gefunden.")
        try:
            waldo.save_correction(puzzle, correction)
        except ValueError:
            raise HTTPException(
                422, "Die Boxen müssen in beiden Bildansichten sichtbar bleiben."
            ) from None
        return puzzle.review()

    @application.websocket("/api/waldo/play")
    async def waldo_game(
        socket: WebSocket,
        duration: Annotated[int, Query(ge=15, le=180)] = 60,
        mode: waldo.Mode = "sprint",
    ) -> None:
        """Limit this local demo to one race, starting inference only on an explicit start."""
        nonlocal waldo_active
        allowed = {
            f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (8000, 5173)
        }
        if socket.headers.get("origin") not in allowed | {None}:
            await socket.close(code=1008)
            return
        await socket.accept()
        message = None
        if waldo_active:
            message = "Ein Duell läuft bereits. Beende es zuerst im anderen Tab."
        elif not config.typesafe_api_key.get_secret_value():
            message = "Bitte TYPESAFE_API_KEY auf dem Server hinterlegen."
        elif active_client is None:
            message = "Der Server startet gerade. Bitte erneut versuchen."
        if message is not None or active_client is None:
            await socket.send_json({"type": "error", "message": message})
            await socket.close(code=1008)
            return
        waldo_active = True
        try:
            await waldo.play(socket, active_client, config, duration, mode, randbelow(2**31))
        finally:
            waldo_active = False

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend_dist.is_dir():

        @application.get("/waldo", include_in_schema=False)
        @application.get("/waldo/", include_in_schema=False)
        @application.get("/waldo/referenzen", include_in_schema=False)
        @application.get("/waldo/referenzen/", include_in_schema=False)
        def waldo_page() -> FileResponse:
            """Serve the Eraneos localization game, including direct links and reloads."""
            return FileResponse(frontend_dist / "waldo.html")

        application.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return application


app = create_app()

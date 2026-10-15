"""Check Snake rules, ASCII observations, and movement only on validated model answers."""

import asyncio
from time import sleep

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from starlette.websockets import WebSocketDisconnect
from test_workbench import DUMMY_KEY, TransportHandler, never_request

from jev_demo.app import create_app
from jev_demo.service import Settings
from jev_demo.snake import (
    SIZE,
    STRUCTURED_OBSERVATION,
    SnakeChoice,
    SnakeFrame,
    SnakeRequest,
    World,
    format_request,
)


def snake_client(handler: TransportHandler) -> TestClient:
    """Create a typed WebSocket test client with a mocked provider."""
    settings = Settings(typesafe_api_key=SecretStr(DUMMY_KEY))
    return TestClient(create_app(settings, httpx.MockTransport(handler)))


def response_body() -> dict[str, object]:
    """Return a known direction without adding hidden game intelligence."""
    return {
        "model": "jev-1.13.0",
        "usage": {"input_tokens": 500, "output_tokens": 30},
        "answers": {
            "direction": {
                "choice": "up",
                "confidence": 0.8,
                "probabilities": {"up": 0.9, "right": 0.1, "down": 0, "left": 0},
            }
        },
    }


def test_ascii_board_is_complete_and_food_is_seeded() -> None:
    """Preserve geometry, heading, body, tail and food without prose or hints."""
    world = World(42)
    assert world.board() == World(42).board()
    rows = world.board().splitlines()
    assert len(rows) == SIZE + 2
    assert all(len(row) == SIZE + 2 for row in rows)
    assert rows[0] == rows[-1] == "#" * (SIZE + 2)
    assert rows[6][3:6] == "To>"
    assert world.board().count("*") == 1
    assert world.food not in world.snake
    assert set(world.board()) <= set("#.*oT>\n")


def test_eating_grows_and_free_movement_preserves_length() -> None:
    """Food adds one segment and respawns off the snake; normal moves release the tail."""
    world = World(3)
    world.food = (5, 5)
    world.step("right")
    assert world.score == 1
    assert len(world.snake) == 4
    assert world.food not in world.snake
    world.food = (0, 0)
    world.step("down")
    assert len(world.snake) == 4
    assert world.snake[0] == (5, 6)


def test_reverse_is_a_body_collision_without_a_safety_override() -> None:
    """An incorrect Jev reversal loses instead of being silently corrected."""
    world = World(2)
    world.step("left")
    assert world.phase == "lost"
    assert world.reason == "Body collision."
    before = world.board()
    world.step("up")
    assert world.board() == before


def test_wall_collision_does_not_wrap() -> None:
    """The board has solid boundaries."""
    world = World(2)
    world.snake = [(9, 5), (8, 5), (7, 5)]
    world.step("right")
    assert world.phase == "lost"
    assert world.reason == "Wall collision."


def test_tail_cell_is_available_when_not_eating() -> None:
    """A move into the cell vacated on the same tick is legal."""
    world = World(2)
    world.snake = [(4, 4), (4, 5), (3, 5), (3, 4)]
    world.food = (0, 0)
    world.step("left")
    assert world.phase == "running"
    assert world.snake == [(3, 4), (4, 4), (4, 5), (3, 5)]


def test_full_board_wins_without_food_placement_loop() -> None:
    """Eating into the final free cell completes the game."""
    world = World(2)
    world.snake = [(8, 9)] + [
        (x, y) for y in range(SIZE) for x in range(SIZE) if (x, y) not in {(8, 9), (9, 9)}
    ]
    world.food = (9, 9)
    world.step("right")
    assert world.phase == "won"
    assert world.food is None
    assert len(world.snake) == SIZE * SIZE


@pytest.mark.parametrize("issue", ["missing", "sum", "winner", "nan"])
def test_invalid_decision_is_rejected(issue: str) -> None:
    """Malformed probabilities never become a movement command."""
    probabilities = {"up": 0.9, "right": 0.1, "down": 0.0, "left": 0.0}
    choice = "up"
    if issue == "missing":
        probabilities.pop("left")
    elif issue == "sum":
        probabilities["up"] = 0.4
    elif issue == "winner":
        choice = "down"
    else:
        probabilities["up"] = float("nan")
    with pytest.raises(ValidationError):
        SnakeChoice.model_validate(
            {"choice": choice, "confidence": 0.8, "probabilities": probabilities}
        )


def test_socket_preserves_request_response_and_cost() -> None:
    """Send exactly the ASCII board and preserve the provider decision and token pricing."""
    recorded: list[SnakeRequest] = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Capture credential-free wire input."""
        recorded.append(SnakeRequest.model_validate_json(request.content))
        return httpx.Response(200, json=response_body())

    with (
        snake_client(respond) as client,
        client.websocket_connect("/api/snake/play?seed=42") as socket,
    ):
        first = SnakeFrame.model_validate(socket.receive_json())
        assert first.board == World(42).board()
        assert (
            first.sent_board == format_request(Settings(), World(42), STRUCTURED_OBSERVATION).state
        )
        assert first.requests == 1
        frame = SnakeFrame.model_validate(socket.receive_json())
        assert frame.responses == 1
        assert frame.direction == "up"
        assert frame.steps == 1
        assert frame.snake[0] == (4, 4)
        assert frame.estimated_cost_usd == pytest.approx(0.000021)
        assert frame.response_request is not None
        assert frame.response_request.state == recorded[0].state == first.sent_board
        assert DUMMY_KEY not in frame.model_dump_json()
        while frame.phase == "running":
            frame = SnakeFrame.model_validate(socket.receive_json())
            assert frame.steps == frame.responses
            if frame.phase == "running":
                assert frame.request is not None
                assert frame.sent_board == frame.request.state
                assert frame.sent_step == frame.steps
        assert frame.phase == "lost"
        assert frame.steps == 6
        assert len(recorded) == 6


def test_slow_inference_keeps_board_still_and_cancels_on_stop() -> None:
    """Waiting never moves the snake, and stopping cancels pending provider work."""
    cancelled: list[bool] = []

    async def slow_response(_request: httpx.Request) -> httpx.Response:
        """Keep inference pending until the session cancels it."""
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        return httpx.Response(200, json=response_body())

    settings = Settings(typesafe_api_key=SecretStr(DUMMY_KEY))
    app = create_app(settings, httpx.MockTransport(slow_response))
    with (
        TestClient(app) as client,
        client.websocket_connect("/api/snake/play?seed=42") as socket,
    ):
        first = SnakeFrame.model_validate(socket.receive_json())
        sleep(0.6)
        socket.send_json({"type": "stop"})
        stopped = SnakeFrame.model_validate(socket.receive_json())
        assert stopped.phase == "stopped"
        assert stopped.steps == stopped.responses == 0
        assert stopped.snake == first.snake
        assert stopped.board == first.board
        assert stopped.requests == 1
    assert cancelled == [True]


def test_provider_failure_stops_without_inventing_a_choice() -> None:
    """Safe provider errors end the run rather than masking failure with an autopilot."""

    def reject(_request: httpx.Request) -> httpx.Response:
        """Simulate a busy provider."""
        return httpx.Response(429)

    with (
        snake_client(reject) as client,
        client.websocket_connect("/api/snake/play?seed=42") as socket,
    ):
        socket.receive_json()
        frame = SnakeFrame.model_validate(socket.receive_json())
        assert frame.phase == "stopped"
        assert frame.decision is None
        assert frame.responses == 0
        assert frame.reason is not None and "busy" in frame.reason


def test_foreign_origin_rejected_before_inference() -> None:
    """Unrelated pages cannot start games that spend the configured API key."""
    with (
        snake_client(never_request) as client,
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(
            "/api/snake/play?seed=42", headers={"Origin": "https://unrelated.example"}
        ),
    ):
        pytest.fail("Foreign origin was accepted.")


def test_structured_observation_reports_cell_contents_without_move_labels() -> None:
    """Expose factual neighbors, heading and full geometry without pruning actions."""
    world = World(42)
    world.food = (4, 4)
    request = format_request(Settings(), world, STRUCTURED_OBSERVATION)
    assert request.state.split("\n\n")[2] == (
        "Adjacent cell contents (one cell from head):\n"
        "UP of head: food\nRIGHT of head: empty\nDOWN of head: empty\nLEFT of head: body"
    )
    assert request.state.startswith("Current direction: RIGHT\n\n")
    assert "H marks the head" in request.questions["direction"].instructions
    assert "^ > v <" not in request.questions["direction"].instructions
    assert set(request.questions["direction"].criteria) == {"up", "right", "down", "left"}
    rows = request.state.split("\n\n")[-1].splitlines()
    unlabelled = ["".join(row.split()[1:]) for row in rows[1:]]
    assert "\n".join(unlabelled) == world.board().replace(">", "H")
    assert "safe" not in request.state.lower()
    assert "recommended" not in request.state.lower()


def test_structured_observation_distinguishes_walls_body_and_departing_tail() -> None:
    """Describe corner neighbors literally instead of preclassifying their legality."""
    world = World(42)
    world.snake = [(0, 0), (1, 0), (1, 1), (0, 1)]
    world.direction = "left"
    world.food = (0, 4)
    request = format_request(Settings(), world, STRUCTURED_OBSERVATION)
    assert request.state.split("\n\n")[2] == (
        "Adjacent cell contents (one cell from head):\n"
        "UP of head: wall\nRIGHT of head: body\nDOWN of head: tail\nLEFT of head: wall"
    )

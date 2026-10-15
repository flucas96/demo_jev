"""Exercise seeded geometry, scoring, decision deadlines, and real transport cancellation."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import JsonValue, SecretStr, TypeAdapter, ValidationError

from jev_demo.app import create_app
from jev_demo.runner.inference import RunnerChoice, RunnerRequest, infer, make_request
from jev_demo.runner.session import Command, GameClock, decide_encounter
from jev_demo.runner.world import ACTIONS, SPEED, Encounter, Frame, World
from jev_demo.service import JevError, Settings


def settings() -> Settings:
    """Avoid loading any local credential in tests."""
    return Settings.model_construct(typesafe_api_key=SecretStr("test"), typesafe_model="jev-latest")


@pytest.mark.parametrize(
    ("kind", "bottom", "top", "expected"),
    [
        ("crate", 0, 28, "jump"),
        ("beam", 28, 104, "duck"),
        ("beam", 53, 104, "stand"),
        ("clear", 0, 0, "stand"),
    ],
)
def test_geometry_has_expected_safe_action(kind: str, bottom: int, top: int, expected: str) -> None:
    """Crates, low screens, high screens, and open space require different choices."""
    encounter = Encounter(1, 3, "clear", 30, bottom, top)
    assert kind in ("crate", "beam", "clear")
    encounter.kind = kind
    assert encounter.optimal() == expected
    assert encounter.safe(encounter.optimal())
    if kind != "clear":
        assert not all(encounter.safe(action) for action in ACTIONS)


def test_random_course_is_replayable_and_always_survivable() -> None:
    """Multiple seeds produce different reproducible geometry with at least one safe move."""
    for seed in range(80):
        left, right = World(seed, "jev", "a"), World(seed, "jev", "b")
        assert left.current == right.current
        for i in range(20):
            encounter = left.generate(i, i * 4)
            assert encounter == right.generate(i, i * 4)
            assert any(encounter.safe(action) for action in ACTIONS)
    assert World(1, "jev", "a").current != World(2, "jev", "b").current


@pytest.mark.parametrize(("action", "rate"), [("stand", 1.0), ("duck", 0.2), ("jump", 0.0)])
def test_points_come_only_from_distance(action: str, rate: float) -> None:
    """Identical travelled distances reward upright more than ducking and never jumping."""
    assert action in ACTIONS
    world = World(1, "manual", "a")
    world.current = Encounter(1, 20, "clear", 30, 0, 0)
    world.action = action
    world.action_started = 0
    world.advance(1)
    assert world.score == pytest.approx(SPEED * world.time / 10 * rate)
    assert world.frame().distance_m == pytest.approx(SPEED * world.time / 10)
    assert world.history == []


def test_choice_changes_pose_immediately_without_a_score_bonus() -> None:
    """A response starts its animation now, not at the old scheduled trigger."""
    world = World(1, "jev", "a")
    world.current = Encounter(1, 3, "clear", 30, 0, 0)
    world.advance(2.5)
    assert world.begin_observation() is not None
    score_before = world.score
    assert world.choose(1, "jump", world.time)
    assert world.action == "jump"
    assert world.action_started < world.current.trigger
    assert world.frame().action_age == 0
    assert world.score == score_before
    world.advance(2.7)
    assert world.frame().player_y > 0
    assert world.score == score_before


def test_deadline_miss_keeps_distance_scoring_and_rejects_stale_actions() -> None:
    """A missing response earns no action bonus; movement still obeys the distance rule."""
    world = World(1, "jev", "a")
    world.current = Encounter(1, 3, "clear", 30, 0, 0)
    world.advance(2.5)
    world.begin_observation()
    assert not world.choose(2, "stand", 2.6)
    assert not world.choose(1, "stand", world.current.deadline)
    world.advance(4)
    assert world.score == pytest.approx(SPEED * world.time / 10)
    assert world.misses == 1
    assert world.timely == 0
    assert world.history[0].action is None
    assert world.history[0].reward == 0
    assert world.history[0].status == "missed"


def test_collision_costs_one_life_and_cannot_be_repaired() -> None:
    """Contact subtracts its penalty only once, independently of distance points."""
    world = World(1, "manual", "a")
    world.current = Encounter(1, 3, "crate", 30, 0, 25)
    world.advance(2.5)
    world.begin_observation()
    world.advance(4)
    assert world.score == pytest.approx(SPEED * world.time / 10 - 25)
    assert world.lives == 2
    assert len(world.history) == 1
    assert not world.choose(1, "jump", 4)
    assert world.history[0].collision


def test_duck_persists_and_always_ducking_scores_less() -> None:
    """Duck remains a posture, preventing a hidden automatic return to high-scoring upright."""
    world = World(1, "manual", "a")
    world.current = Encounter(1, 20, "clear", 30, 0, 0)
    world.action = "duck"
    world.advance(4)
    assert world.action == "duck"
    assert world.frame().player_height == 19
    assert world.score == pytest.approx(world.frame().distance_m * 0.2)


def test_latency_affects_real_collision_outcomes() -> None:
    """The same correct jump clears a crate promptly but collides when started too late."""
    results: list[bool] = []
    for response_at in (2.8, 3.3):
        world = World(1, "jev", "a")
        world.current = Encounter(1, 3, "crate", 38, 0, 28)
        world.advance(world.current.contact_start - 0.8)
        world.begin_observation()
        assert world.choose(1, "jump", response_at)
        world.advance(4)
        results.append(world.history[0].collision)
    assert results == [False, True]


def test_speed_changes_preserve_position_and_scale_only_future_time() -> None:
    """Speed changes accumulate distance continuously and leave wall-time latency untouched."""
    clock = GameClock(sampled_at=100)
    assert clock.sample(102) == 2
    clock.set_pace(2, 102)
    assert clock.sample(103) == 4
    clock.set_pace(0.5, 103)
    assert clock.sample(105) == 5
    world = World(1, "manual", "a")
    world.advance(world.current.contact_start - 0.8)
    world.begin_observation()
    before = world.frame()
    world.pace = 2
    after = world.frame()
    assert before.obstacles == after.obstacles
    assert before.distance_m == after.distance_m
    assert after.speed == before.speed * 2
    assert before.decision is not None and after.decision is not None
    assert after.decision.seconds_left == before.decision.seconds_left / 2


@pytest.mark.parametrize("pace", [0, 0.25, 3, float("nan"), float("inf")])
def test_invalid_speed_is_rejected(pace: float) -> None:
    """The public speed control cannot freeze, reverse, or unbound the simulation."""
    with pytest.raises(ValidationError):
        Command(type="speed", pace=pace)


@pytest.mark.parametrize("pace", [0.5, 1.0, 2.0])
def test_full_round_and_terminal_partial_encounter(pace: float) -> None:
    """A complete round has no partial unobserved final obstacle and no post-finish inference."""
    world = World(42, "manual", "a")
    world.pace = pace
    for tick in range(int(60 / pace * 20) + 2):
        world.advance(tick / 20 * pace)
        encounter = world.begin_observation()
        if encounter is not None:
            assert world.choose(encounter.id, encounter.optimal(), world.time)
    assert world.phase == "finished"
    assert world.time == 60
    assert world.lives == 3
    assert world.presented == len(world.history)
    assert world.correct == world.presented
    assert world.begin_observation() is None


def test_input_contains_geometry_without_oracle_or_visual_input() -> None:
    """The model receives text facts and scoring rules, never a reference answer."""
    world = World(1, "jev", "a")
    payload = make_request(settings(), world.observation(world.current))
    assert set(payload.questions) == {"action"}
    assert set(payload.questions["action"].criteria) == set(ACTIONS)
    assert '"next_obstacle"' in payload.state
    assert "expected" not in payload.state
    assert "optimal" not in payload.state
    assert "image" not in payload.model_dump_json()


@pytest.mark.parametrize(
    ("until_contact", "phase"), [(2.0, "distant"), (0.6, "approaching"), (-0.1, "crossing")]
)
def test_observation_distinguishes_screen_clearance_and_crossing_phase(
    until_contact: float, phase: str
) -> None:
    """The screen's open gap and remaining crossing time must survive snapshot serialization."""
    world = World(1, "jev", "observation")
    world.time = 10
    world.current = Encounter(1, 10 + until_contact - 0.32, "beam", 30, 28, 104)
    state = TypeAdapter(dict[str, JsonValue]).validate_json(world.observation(world.current))
    obstacle = state["next_obstacle"]
    assert isinstance(obstacle, dict)
    assert obstacle["kind"] == "overhead_screen"
    assert obstacle["passage_underneath_px"] == 28
    assert obstacle["top_above_ground_px"] == 104
    assert obstacle["phase"] == phase
    assert obstacle["game_seconds_until_contact"] == max(0, until_contact)
    remaining = obstacle["game_seconds_until_fully_passed"]
    assert isinstance(remaining, float)
    assert remaining == pytest.approx(until_contact + 50 / SPEED, abs=0.001)


def test_clear_road_has_no_phantom_obstacle_countdown() -> None:
    """An internal clear encounter should not look like a timed physical hazard to Jev."""
    world = World(1, "jev", "observation")
    world.current = Encounter(1, 3, "clear", 30, 0, 0)
    state = world.observation(world.current)
    assert '"next_obstacle":null' in state
    assert "until_contact" not in state


def test_obstacle_urgency_accounts_for_response_time_and_game_speed() -> None:
    """A request must anticipate where the crate will be when its answer reaches the game."""
    world = World(1, "jev", "response-timing")
    world.current = Encounter(1, 0.88, "crate", 30, 0, 28)
    world.response_seconds = 0.2
    adapter = TypeAdapter(dict[str, JsonValue])
    normal = adapter.validate_json(world.observation(world.current))["next_obstacle"]
    world.pace = 2
    fast = adapter.validate_json(world.observation(world.current))["next_obstacle"]
    assert isinstance(normal, dict) and isinstance(fast, dict)
    assert normal["phase"] == "distant"
    assert fast["phase"] == "approaching"
    assert fast["game_seconds_until_contact"] == 1.2
    assert fast["estimated_game_seconds_until_contact_on_response"] == 0.8


@pytest.mark.parametrize(
    ("pace", "delay"), [(1, 0.3), (1.23, 0.36), (1.23, 0.45), (1.23, 0.5), (2, 0.3)]
)
def test_sequential_correct_choices_clear_reported_course_with_response_delay(
    monkeypatch: pytest.MonkeyPatch, pace: float, delay: float
) -> None:
    """Replay the reported seed with realistic latency while preserving genuine jump physics."""
    from jev_demo.runner.session import control_continuously

    async def exercise() -> None:
        """Use a deterministic clock and correct model choices to isolate request timing."""
        now = 0.0
        monkeypatch.setattr("jev_demo.runner.session.perf_counter", lambda: now)
        monkeypatch.setattr("jev_demo.service.perf_counter", lambda: now)
        world = World(1286777811, "jev", "reported-course")
        world.pace = pace

        def respond(request: httpx.Request) -> httpx.Response:
            """Return a choice from the observed phase only, after simulated network latency."""
            nonlocal now
            payload = RunnerRequest.model_validate_json(request.content)
            state = TypeAdapter(dict[str, JsonValue]).validate_json(payload.state)
            runner, obstacle = state["runner"], state["next_obstacle"]
            assert isinstance(runner, dict)
            choice = "jump" if runner["current_posture"] == "jump" else "stand"
            if isinstance(obstacle, dict) and obstacle["phase"] != "distant":
                clearance = obstacle["passage_underneath_px"]
                assert isinstance(clearance, (int, float))
                choice = (
                    "jump"
                    if obstacle["kind"] == "ground_crate"
                    else "duck"
                    if clearance < 40
                    else "stand"
                )
            now += delay
            if len(world.history) >= 8:
                world.interrupt("Replay checked.")
            return httpx.Response(
                200,
                json={
                    "model": "jev-1.13.0",
                    "usage": {"input_tokens": 100, "output_tokens": 5},
                    "answers": {
                        "action": {
                            "choice": choice,
                            "confidence": 1,
                            "probabilities": {move: int(move == choice) for move in ACTIONS},
                        }
                    },
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await asyncio.wait_for(
                control_continuously(
                    world, GameClock(pace=pace, sampled_at=0), client, settings(), asyncio.Event()
                ),
                timeout=1,
            )
        assert len(world.history) >= 8
        assert world.lives == 3
        assert all(not trace.collision for trace in world.history)
        assert world.response_seconds == pytest.approx(delay, abs=0.001)

    asyncio.run(exercise())


def test_correct_but_late_jump_is_still_a_collision_with_timing_reason() -> None:
    """Latency compensation must not turn correct labels into automatic collision immunity."""
    world = World(1, "jev", "late-jump")
    world.current = Encounter(1, 3, "crate", 30, 0, 28)
    assert world.choose(1, "jump", 3.29, continuous=True)
    world.advance(3.4)
    assert world.lives == 2
    assert world.history[0].action == world.history[0].expected == "jump"
    assert world.history[0].collision_reason == "Jump too late"


@pytest.mark.parametrize(("clearance", "action"), [(28, "duck"), (53, "stand")])
def test_grounding_mid_jump_can_clear_an_overhead_screen(clearance: int, action: str) -> None:
    """The prompt's emergency jump cancellation matches actual physics for both screen sizes."""
    assert action in ACTIONS
    world = World(1, "jev", "cancel-jump")
    world.current = Encounter(1, 3, "beam", 30, clearance, 104)
    assert world.choose(1, "jump", 2.5, continuous=True)
    world.advance(2.9)
    assert world.frame().player_y > 0
    assert world.choose(1, action, 2.9, continuous=True)
    assert world.frame().player_y == 0
    world.advance(3.8)
    assert world.lives == 3
    assert world.history[0].optimal


@pytest.mark.parametrize(
    "raw",
    [
        '{"choice":"fly","confidence":1,"probabilities":{"fly":1}}',
        '{"choice":"stand","confidence":1,"probabilities":{"stand":1}}',
        '{"choice":"stand","confidence":1,"probabilities":{"stand":0.1,"jump":0.8,"duck":0.1}}',
        '{"choice":"stand","confidence":1,"probabilities":{"stand":0.8,"jump":0.8,"duck":0.1}}',
    ],
)
def test_invalid_choice_is_rejected(raw: str) -> None:
    """Only complete, consistent action distributions are executable."""
    with pytest.raises(ValidationError):
        RunnerChoice.model_validate_json(raw)


def test_inference_records_real_usage_and_safe_errors() -> None:
    """Valid provider data is preserved while provider error bodies are never disclosed."""

    async def exercise() -> None:
        """Run the actual adapter against an in-memory HTTP transport."""

        def respond(request: httpx.Request) -> httpx.Response:
            """Validate the outgoing schema and return a single Choice answer."""
            payload = RunnerRequest.model_validate_json(request.content)
            assert set(payload.questions) == {"action"}
            return httpx.Response(
                200,
                json={
                    "model": "jev-1.13.0",
                    "usage": {"input_tokens": 100, "output_tokens": 5},
                    "answers": {
                        "action": {
                            "choice": "stand",
                            "confidence": 0.9,
                            "probabilities": {"stand": 0.9, "jump": 0.05, "duck": 0.05},
                        }
                    },
                },
            )

        world = World(1, "jev", "a")
        world.advance(world.current.contact_start - 0.8)
        encounter = world.begin_observation()
        assert encounter is not None
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await decide_encounter(
                world, encounter, GameClock(game_time=world.time), client, settings()
            )
        assert encounter.selected == "stand"
        assert world.input_tokens == 100
        assert world.cost == pytest.approx(0.0000042)
        assert encounter.response is not None and "test" not in encounter.response

        def reject(_request: httpx.Request) -> httpx.Response:
            """Return an intentionally private body that must never reach the UI."""
            return httpx.Response(401, text="private provider body")

        async with httpx.AsyncClient(transport=httpx.MockTransport(reject)) as client:
            with pytest.raises(JevError, match="rejected the server API key") as failure:
                await infer(client, settings(), make_request(settings(), "geometry"))
            assert "private provider body" not in failure.value.message

    asyncio.run(exercise())


def test_slow_inference_does_not_pause_world_and_is_cancelled() -> None:
    """The simulation passes the trigger even while an upstream request remains blocked."""

    async def exercise() -> None:
        """Use an event barrier instead of relying on network timing."""
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def respond(_request: httpx.Request) -> httpx.Response:
            """Hold the request until its owner cancels it."""
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            raise AssertionError("Unreachable")

        world = World(1, "jev", "a")
        world.advance(world.current.contact_start - 0.8)
        encounter = world.begin_observation()
        assert encounter is not None
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            task = asyncio.create_task(
                decide_encounter(
                    world, encounter, GameClock(game_time=world.time), client, settings()
                )
            )
            await asyncio.wait_for(started.wait(), 1)
            world.advance(encounter.contact_end + 0.1)
            assert world.time > encounter.contact_end
            assert world.misses == 1
            assert not task.done()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert cancelled.is_set()
            assert encounter.selected is None

    asyncio.run(exercise())


def test_websocket_stop_and_origin_validation() -> None:
    """The actual route emits frames, stops cleanly, and rejects unrelated browser origins."""
    with TestClient(create_app(settings())) as client:
        with client.websocket_connect("/api/runner/play?seed=10&mode=manual") as socket:
            first = Frame.model_validate_json(socket.receive_text())
            assert first.phase == "running"
            socket.send_json({"type": "stop"})
            final = first
            for _ in range(10):
                final = Frame.model_validate_json(socket.receive_text())
                if final.phase != "running":
                    break
            assert final.phase == "interrupted"
            assert final.reason == "Stopped."
        from starlette.websockets import WebSocketDisconnect

        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect(
                "/api/runner/play?seed=10&mode=manual",
                headers={"origin": "https://unrelated.example"},
            ),
        ):
            pass


def test_session_disconnect_cancels_in_flight_request() -> None:
    """Closing the real WebSocket propagates cancellation to the provider transport."""
    from threading import Event

    cancelled = Event()

    async def respond(_request: httpx.Request) -> httpx.Response:
        """Keep a request active until the game session is disconnected."""
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("Unreachable")

    with TestClient(create_app(settings(), httpx.MockTransport(respond))) as client:
        with client.websocket_connect("/api/runner/play?seed=1&mode=jev") as socket:
            for _ in range(100):
                frame = Frame.model_validate_json(socket.receive_text())
                if frame.thinking:
                    break
            else:
                pytest.fail("The decision window never opened.")
        assert cancelled.wait(timeout=2)
        with client.websocket_connect("/api/runner/play?seed=1&mode=manual") as socket:
            assert Frame.model_validate_json(socket.receive_text()).phase == "running"


def test_single_run_limit_and_manual_without_credential() -> None:
    """A second tab cannot start extra paid inference; manual mode needs no key."""
    config = Settings.model_construct(typesafe_api_key=SecretStr(""), typesafe_model="jev-latest")
    with TestClient(create_app(config)) as client:
        with client.websocket_connect("/api/runner/play?seed=1&mode=jev") as socket:
            assert "Configure TYPESAFE_API_KEY" in socket.receive_text()
        with client.websocket_connect("/api/runner/play?seed=1&mode=manual") as first:
            assert Frame.model_validate_json(first.receive_text()).phase == "running"
            with client.websocket_connect("/api/runner/play?seed=2&mode=manual") as second:
                assert "already active" in second.receive_text()


def test_live_speed_command_updates_frames() -> None:
    """The slider can change speed during an existing WebSocket run without restarting it."""
    with (
        TestClient(create_app(settings())) as client,
        client.websocket_connect("/api/runner/play?seed=10&mode=manual&pace=0.5") as socket,
    ):
        before = Frame.model_validate_json(socket.receive_text())
        assert before.pace == 0.5
        socket.send_json({"type": "speed", "pace": 2})
        after = before
        for _ in range(10):
            after = Frame.model_validate_json(socket.receive_text())
            if after.pace == 2:
                break
        assert after.pace == 2
        assert after.speed == 240
        assert after.run_id == before.run_id
        assert after.distance_m >= before.distance_m


def test_endless_continues_beyond_timed_limit_and_bounds_history() -> None:
    """Survival continues beyond 60 seconds while trace storage remains bounded."""
    from jev_demo.runner.world import HISTORY_LIMIT

    world = World(42, "manual", "endless-test", "endless")
    for tick in range(6001):
        world.advance(tick / 20)
        encounter = world.begin_observation()
        if encounter is not None:
            assert world.choose(encounter.id, encounter.optimal(), world.time)
    assert world.time > 299
    assert world.phase == "running"
    assert world.lives == 3
    assert world.presented > HISTORY_LIMIT
    assert len(world.history) == HISTORY_LIMIT
    assert world.correct > HISTORY_LIMIT
    frame = world.frame()
    assert frame.duration is None
    assert frame.challenge == "endless"
    assert frame.collisions == 0


def test_endless_ends_on_third_collision() -> None:
    """No timer is required to finish an endless game when the last heart is lost."""
    world = World(1, "manual", "endless-test", "endless")
    for index in range(3):
        trigger = world.time + 1
        world.current = Encounter(index + 1, trigger, "crate", 30, 0, 25)
        world.advance(trigger + 1)
        assert world.lives == 2 - index
        assert world.phase == ("finished" if index == 2 else "running")
    assert world.frame().collisions == 3
    finished_time = world.time
    world.advance(finished_time + 100)
    assert world.time == finished_time
    assert world.begin_observation() is None


def test_endless_acceleration_is_wall_time_based_and_partition_independent() -> None:
    """Gentle acceleration integrates consistently regardless of snapshot frequency."""
    from jev_demo.runner.session import ENDLESS_ACCELERATION

    whole = GameClock(sampled_at=100, acceleration=ENDLESS_ACCELERATION)
    split = GameClock(sampled_at=100, acceleration=ENDLESS_ACCELERATION)
    assert whole.sample(110) == pytest.approx(10.5)
    assert whole.pace == pytest.approx(1.1)
    for tick in range(1, 201):
        split.sample(100 + tick / 20)
    assert split.game_time == pytest.approx(whole.game_time)
    assert split.pace == pytest.approx(whole.pace)
    whole.sample(160)
    assert whole.pace == pytest.approx(1.6)
    assert whole.game_time == pytest.approx(78)
    whole.sample(220)
    assert whole.pace == pytest.approx(2.2)


def test_endless_socket_reports_auto_speed_and_rejects_manual_override() -> None:
    """The live mode starts at the selected speed and cannot be reset with slider commands."""
    with (
        TestClient(create_app(settings())) as client,
        client.websocket_connect(
            "/api/runner/play?seed=10&mode=manual&pace=0.5&challenge=endless"
        ) as socket,
    ):
        first = Frame.model_validate_json(socket.receive_text())
        assert first.challenge == "endless"
        assert first.duration is None
        socket.send_json({"type": "speed", "pace": 2})
        latest = first
        for _ in range(4):
            latest = Frame.model_validate_json(socket.receive_text())
        assert latest.pace > first.pace
        assert latest.pace < 0.6
        assert latest.run_id == first.run_id


@pytest.mark.parametrize("pace", [0.5, 1, 2, 4])
def test_obstacles_enter_from_right_without_popping_or_repositioning(pace: float) -> None:
    """Every new drawing object starts outside the canvas and retains its scrolling position."""
    from jev_demo.runner.world import SCENE_WIDTH

    world = World(42, "manual", "edge-test", "endless")
    previous: dict[int, float] = {}
    previous_time = 0.0
    seen: set[int] = set()
    for tick in range(401):
        world.advance(tick * 0.05 * pace)
        encounter = world.begin_observation()
        if encounter is not None:
            world.choose(encounter.id, encounter.optimal(), world.time)
        frame = world.frame()
        positions = {obstacle.id: obstacle.x for obstacle in frame.obstacles}
        for identifier in positions.keys() - seen:
            assert positions[identifier] >= SCENE_WIDTH + 2
        for identifier in positions.keys() & previous.keys():
            assert positions[identifier] == pytest.approx(
                previous[identifier] - SPEED * (frame.time - previous_time)
            )
        seen.update(positions)
        previous, previous_time = positions, frame.time
    assert len(seen) >= 3
    assert world.lives == 3


def test_continuous_controller_requeries_immediately_with_fresh_state() -> None:
    """Several answers arrive before any obstacle window, with fresh inputs and no overlap."""
    from jev_demo.runner.session import control_continuously

    async def exercise() -> None:
        """Stop after three successful responses without waiting for a game event."""
        world = World(1, "jev", "continuous-test")
        captured: list[str] = []
        active, maximum = 0, 0

        async def respond(request: httpx.Request) -> httpx.Response:
            """Yield once so overlapping requests would be detected by the active counter."""
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            captured.append(RunnerRequest.model_validate_json(request.content).state)
            try:
                await asyncio.sleep(0)
                action = "stand" if len(captured) == 1 else "jump"
                if len(captured) == 3:
                    world.interrupt("Test complete.")
                return httpx.Response(
                    200,
                    json={
                        "model": "jev-1.13.0",
                        "usage": {"input_tokens": 100, "output_tokens": 5},
                        "answers": {
                            "action": {
                                "choice": action,
                                "confidence": 1,
                                "probabilities": {move: int(move == action) for move in ACTIONS},
                            }
                        },
                    },
                )
            finally:
                active -= 1

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await asyncio.wait_for(
                control_continuously(world, GameClock(), client, settings(), asyncio.Event()),
                timeout=1,
            )
        assert maximum == 1
        assert world.requests == world.responses == len(captured) == 3
        assert world.presented == 0
        assert '"current_posture":"stand"' in captured[0]
        assert '"current_posture":"jump"' in captured[2]
        assert world.input_tokens == 300
        assert not world.thinking

    asyncio.run(exercise())


def test_repeating_jump_does_not_restart_the_arc() -> None:
    """Repeated control decisions cannot keep resetting the character to the start of a jump."""
    world = World(1, "jev", "continuous-test")
    assert world.choose(world.current.id, "jump", 0.1, continuous=True)
    started = world.action_started
    assert world.choose(world.current.id, "jump", 0.4, continuous=True)
    assert world.action_started == started
    assert world.frame().player_y > 0
    world.advance(2)
    assert world.action == "stand"


def test_expired_jump_response_does_not_trigger_a_second_jump() -> None:
    """A response based on an airborne snapshot becomes a no-op after that jump lands."""

    async def exercise() -> None:
        """Complete the jump before delivering its delayed continuation response."""
        world = World(1, "jev", "continuous-test")
        world.current = Encounter(1, 20, "clear", 30, 0, 0)
        world.action = "jump"
        world.action_started = 0

        def respond(_request: httpx.Request) -> httpx.Response:
            """Return a valid command to continue the previously observed jump."""
            return httpx.Response(
                200,
                json={
                    "model": "jev-1.13.0",
                    "usage": {"input_tokens": 100, "output_tokens": 5},
                    "answers": {
                        "action": {
                            "choice": "jump",
                            "confidence": 1,
                            "probabilities": {"stand": 0, "duck": 0, "jump": 1},
                        }
                    },
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            await decide_encounter(
                world, world.current, GameClock(game_time=2), client, settings(), continuous=True
            )
        assert world.action == "stand"
        assert world.responses == 1
        assert world.last_decision is not None
        assert world.last_decision.status == "missed"

    asyncio.run(exercise())

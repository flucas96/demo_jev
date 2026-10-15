"""Exercise fair scoring, timer boundaries, reference isolation, and real-shaped image transport."""

import base64
import json
from io import BytesIO
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr, TypeAdapter, ValidationError

from jev_demo import waldo
from jev_demo.app import create_app
from jev_demo.service import Settings
from jev_demo.waldo import (
    BY_ID,
    FEEDBACK_SECONDS,
    MODEL,
    PUZZLES,
    Box,
    BoxRequest,
    BoxResponse,
    Match,
    Point,
    Puzzle,
    ReferenceCorrection,
    image_bytes,
    make_request,
    overlap,
    playable_puzzles,
)

LEGACY = {
    puzzle.id: puzzle
    for puzzle in TypeAdapter(list[Puzzle]).validate_json(
        (Path(__file__).parent / "fixtures" / "waldo-legacy-geometry.json").read_bytes()
    )
}


def settings() -> Settings:
    """Keep transport tests independent of local provider credentials."""
    return Settings(typesafe_api_key=SecretStr("waldo-test-secret"))


def response(box: Box | None = None, model: str = MODEL) -> BoxResponse:
    """Represent the documented new primitive without fabricating any production output."""
    return BoxResponse.model_validate(
        {
            "model": model,
            "answers": {
                "waldo": {
                    "type": "box",
                    "box": (box or PUZZLES[0].reference).model_dump(),
                    "confidence": 0.8,
                }
            },
            "usage": {"input_tokens": 2000, "output_tokens": 21},
        }
    )


def test_overlap_requires_localization_and_rejects_full_image_cheating() -> None:
    """A precise hit scores; a distant box and a whole-image box do not."""
    reference = Box(left=0.2, right=0.3, top=0.4, bottom=0.5)
    assert overlap(reference, reference) == 1
    assert overlap(Box(left=0.8, right=0.9, top=0.8, bottom=0.9), reference) == 0
    assert overlap(Box(left=0, right=1, top=0, bottom=1), reference) < 0.02


def test_head_body_and_padding_count_but_neighbours_and_feet_do_not() -> None:
    """Recognition permits head-only or loose body bounds, without crediting unrelated pixels."""
    puzzle = Puzzle(
        id="test",
        mode="sprint",
        width=1152,
        height=648,
        source_id=1,
        source_crop=(0, 0, 1152, 648),
        reference=Box(left=0.4, right=0.5, top=0.2, bottom=0.6),
        head=Box(left=0.42, right=0.48, top=0.22, bottom=0.3),
    )
    assert puzzle.accepts(puzzle.head)
    assert puzzle.accepts(puzzle.reference)
    assert puzzle.accepts(puzzle.reference.padded(0.2))
    assert puzzle.accepts(Box(left=0.43, right=0.47, top=0.25, bottom=0.29))
    assert not puzzle.accepts(Box(left=0.4, right=0.5, top=0.5, bottom=0.62))
    assert not puzzle.accepts(Box(left=0.4, right=0.9, top=0.2, bottom=0.6))
    assert not puzzle.accepts(Box(left=0, right=1, top=0, bottom=1))
    assert not puzzle.accepts(Box(left=0.43, right=0.44, top=0.24, bottom=0.25))


@pytest.mark.parametrize(
    "scene,correct", [(3, True), (8, True), (10, True), (9, False), (12, False)]
)
def test_visually_reviewed_live_answers(scene: int, correct: bool) -> None:
    """Regress the tiny head and full-body false negatives alongside broad and headless misses."""
    predictions = {
        3: Box(left=0.65, right=0.69, top=0.74, bottom=0.81),
        8: Box(left=0.22, right=0.33, top=0.76, bottom=0.96),
        10: Box(left=0.35, right=0.46, top=0.19, bottom=0.54),
        9: Box(left=0.46, right=0.65, top=0.45, bottom=0.68),
        12: Box(left=0.49, right=0.56, top=0.41, bottom=0.46),
    }
    assert LEGACY[f"scene-{scene:02}-sprint"].accepts(predictions[scene]) is correct


@pytest.mark.parametrize(
    "bounds",
    [
        {"left": 0.8, "right": 0.2, "top": 0, "bottom": 1},
        {"left": 0, "right": 1, "top": 0.5, "bottom": 0.5},
        {"left": -1, "right": 1, "top": 0, "bottom": 1},
        {"left": float("nan"), "right": 1, "top": 0, "bottom": 1},
    ],
)
def test_invalid_boxes_are_rejected(bounds: dict[str, float]) -> None:
    """Nonfinite and impossible geometry never enters a match."""
    with pytest.raises(ValidationError):
        Box.model_validate(bounds)


def test_players_share_order_and_scoring_but_progress_independently() -> None:
    """Identical decisions earn identical scores without advancing the other player's image."""
    match = Match(60, "sprint", 42, 100)
    reference = match.puzzle("human").reference
    assert match.puzzle("jev") == match.puzzle("human")
    assert match.submit("human", 0, reference, 101)
    assert match.submit("jev", 0, reference, 101)
    assert match.players["human"].score == match.players["jev"].score == 1
    assert not match.submit("human", 0, reference, 101.1)
    match.tick(102)
    assert match.players["human"].round == match.players["jev"].round == 1
    assert not match.submit("human", 0, reference, 102)
    assert match.submit("human", 1, match.puzzle("human").reference, 103)
    match.tick(104)
    assert match.players["human"].round == 2
    assert match.players["jev"].round == 1


def test_clicks_score_body_hits_and_reject_duplicate_late_and_distant_picks() -> None:
    """A body click earns one point; stale clicks and background taps cannot gain points."""
    match = Match(60, "sprint", 42, 100)
    body = match.puzzle("human").reference
    point = Point(x=(body.left + body.right) / 2, y=body.bottom - 0.01)
    assert match.submit("human", 0, None, 101, point=point)
    assert match.players["human"].score == 1
    assert not match.submit("human", 0, None, 101.1, point=point)
    assert not match.submit("jev", 0, None, 101.1, point=point)
    match.tick(102)
    assert not match.submit("human", 0, None, 103, point=point)
    assert match.submit("human", 1, None, 103, point=Point(x=0, y=0))
    assert match.players["human"].score == 0
    assert match.players["human"].feedback is not None
    assert not match.players["human"].feedback["skipped"]
    match.tick(104)
    assert match.players["human"].round == 1
    assert not match.submit("human", 1, None, 160, point=point)


@pytest.mark.parametrize("point", [{"x": -0.1, "y": 0.5}, {"x": 0.5, "y": float("nan")}])
def test_invalid_clicks_are_rejected(point: dict[str, float]) -> None:
    """Coordinates outside the image or without a finite value cannot reach scoring."""
    with pytest.raises(ValidationError):
        Point.model_validate(point)


def test_three_wrong_answers_advance_after_equal_feedback_delay() -> None:
    """Both competitors lose a point per miss and leave an unsolved scene after three."""
    match = Match(60, "sprint", 42, 100)
    wrong = Box(left=0, right=1, top=0, bottom=1)
    for attempt in range(3):
        now = 101 + attempt
        for who in ("human", "jev"):
            assert match.submit(who, 0, wrong, now)
            assert match.players[who].score == -(attempt + 1)
        match.tick(now + FEEDBACK_SECONDS + 0.01)
    assert match.players["human"].round == match.players["jev"].round == 1


def test_deadline_rejects_late_points_but_accounts_for_returned_tokens() -> None:
    """Responses at or after the deadline cannot change scores, even with a correct box."""
    match = Match(60, "sprint", 42, 100)
    reference = match.puzzle("jev").reference
    assert not match.submit("human", 0, reference, 160)
    match.tick(160)
    assert not match.submit("jev", 0, reference, 160.01)
    match.calls = 1
    match.record_usage(response(reference), 789)
    assert match.ended
    assert match.players["jev"].score == 0
    assert match.completed == 1
    assert match.cost == pytest.approx(0.000084)


def test_all_assets_fit_api_and_references_stay_inside_images() -> None:
    """Every mode has a valid JPEG and a visible positive-area target after its crop transform."""
    for puzzle in PUZZLES:
        with Image.open(BytesIO(image_bytes(puzzle.id))) as image:
            assert image.size == (puzzle.width, puzzle.height)
            assert image.format == "JPEG"
            assert 256 <= image.width <= 1568
            assert 256 <= image.height <= 1568
            assert image.width * image.height >= 78400
        assert 0 < puzzle.reference.area < 0.1
        assert puzzle.accepts(puzzle.head)
        assert puzzle.accepts(puzzle.reference)
        ReferenceCorrection(reference=puzzle.reference, head=puzzle.head)


def test_generated_default_deck_preserves_original_scenes_and_requests() -> None:
    """Mix clear and crowded generated scenes while preserving originals and saved corrections."""
    generated = playable_puzzles("sprint")
    assert len(generated) == 60
    assert len({p.id for p in generated}) == 60
    assert playable_puzzles("classic") == generated
    assert all(p.generated and (p.width, p.height) == (1568, 882) for p in generated)
    assert all(p.generated for p in Match(60, "sprint", 42, 100).course)
    for puzzle in generated:
        payload = make_request(puzzle)
        assert puzzle.title not in payload.model_dump_json()
        assert base64.b64decode(next(iter(payload.assets.values())).data_base64) == image_bytes(
            puzzle.id
        )
    assert "scene-03-sprint" not in BY_ID


def test_request_and_catalog_do_not_leak_the_ground_truth() -> None:
    """Jev gets exact displayed bytes but never IDs, reference coordinates, or prior scores."""
    puzzle = BY_ID["scene-16-sprint"]
    payload = make_request(puzzle)
    assert payload.model == MODEL
    assert set(payload.state) == {"scene"}
    assert set(payload.assets) == set(payload.state.values())
    assert len(payload.assets) == 1
    assert set(payload.questions) == {"waldo"}
    assert payload.questions["waldo"].instructions == "Where is Waldo in `scene`?"
    assert "criteria" not in payload.questions["waldo"].model_dump()
    asset = next(iter(payload.assets.values()))
    assert base64.b64decode(asset.data_base64) == image_bytes(puzzle.id)
    assert "reference" not in payload.model_dump_json()
    with TestClient(create_app(settings())) as test_client:
        client = cast(httpx.Client, test_client)
        result = client.get("/api/waldo/catalog")
        assert result.status_code == 200
        assert "reference" not in result.text
        assert "source_id" not in result.text
        assert '"head"' not in result.text
        assert client.get(f"/api/waldo/images/{puzzle.id}").content == image_bytes(puzzle.id)
        assert client.get("/api/waldo/images/manifest.json").status_code == 404


def test_websocket_sends_live_images_and_stop_does_not_start_another_call() -> None:
    """The live path pins the new model and header while keeping credentials server-side."""
    requests: list[BoxRequest] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Inspect the outbound contract and return a known valid provider response."""
        assert request.headers["TypeSafe-Danger-Zone-Images"] == "true"
        assert request.headers["Authorization"] == "Bearer waldo-test-secret"
        payload = BoxRequest.model_validate_json(request.content)
        requests.append(payload)
        return httpx.Response(200, json=response().model_dump(mode="json"))

    with (
        TestClient(create_app(settings(), httpx.MockTransport(handler))) as client,
        client.websocket_connect("/api/waldo/play?duration=15") as socket,
    ):
        first = TypeAdapter(dict[str, object]).validate_python(socket.receive_json())
        assert "waldo-test-secret" not in json.dumps(first)
        correction = ReferenceCorrection(reference=PUZZLES[0].reference, head=PUZZLES[0].head)
        assert (
            cast(httpx.Client, client)
            .put(f"/api/waldo/references/{PUZZLES[0].id}", json=correction.model_dump())
            .status_code
            == 409
        )
        socket.send_json({"type": "stop"})
        for _ in range(10):
            state = TypeAdapter(dict[str, object]).validate_python(socket.receive_json())
            if state.get("ended") is True:
                assert state.get("aborted") is True
                break
        else:
            pytest.fail("Stop did not end the match.")
    assert len(requests) <= 1
    assert all(payload.model == MODEL for payload in requests)


def test_unknown_models_never_receive_a_fabricated_cost() -> None:
    """Keep unsupported prices separate from the known partial estimate."""
    match = Match(60, "sprint", 42, 100)
    match.record_usage(response(model="future-model"), 100)
    assert match.cost == 0
    assert match.unpriced == 1


def test_corrections_persist_and_transform_both_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A browser edit survives reloads and updates the whole scene from the same source pixels."""
    annotations = tmp_path / "reviewed-annotations.json"
    annotations.write_bytes(waldo.ANNOTATIONS.read_bytes())
    puzzles = [puzzle.model_copy(deep=True) for puzzle in [*PUZZLES, *LEGACY.values()]]
    (tmp_path / "manifest.json").write_bytes(TypeAdapter(list[Puzzle]).dump_json(puzzles))
    monkeypatch.setattr(waldo, "ASSETS", tmp_path)
    monkeypatch.setattr(waldo, "ANNOTATIONS", annotations)
    monkeypatch.setattr(waldo, "PUZZLES", puzzles)
    monkeypatch.setattr(waldo, "BY_ID", {puzzle.id: puzzle for puzzle in puzzles})
    puzzle = waldo.BY_ID["scene-03-sprint"]
    edited = ReferenceCorrection(reference=puzzle.reference.padded(0.1), head=puzzle.head)
    original_classic = waldo.BY_ID["scene-03-classic"].reference
    with TestClient(create_app(settings())) as test_client:
        client = cast(httpx.Client, test_client)
        assert (
            client.put(f"/api/waldo/references/{puzzle.id}", json=edited.model_dump()).status_code
            == 200
        )
        assert client.get("/api/waldo/references").status_code == 200
        assert (
            client.put("/api/waldo/references/missing", json=edited.model_dump()).status_code == 404
        )
        invalid = {"reference": edited.head.model_dump(), "head": edited.reference.model_dump()}
        assert client.put(f"/api/waldo/references/{puzzle.id}", json=invalid).status_code == 422
    assert waldo.BY_ID["scene-03-classic"].reference != original_classic
    reloaded = {puzzle.id: puzzle for puzzle in waldo.load_puzzles()}
    assert reloaded[puzzle.id].reference.left == pytest.approx(edited.reference.left)
    assert reloaded[puzzle.id].head.top == pytest.approx(edited.head.top)
    assert not list(tmp_path.glob(".annotations-*"))

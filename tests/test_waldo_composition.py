"""Check placement geometry, transparent pixels, and reproducible image identities."""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from jev_demo.waldo_composition import (
    Backdrop,
    Composition,
    Placement,
    compose_scenes,
    place_target,
)


def sprite() -> Image.Image:
    """Use an asymmetric transparent test figure with known visible edges."""
    image = Image.new("RGBA", (20, 40))
    ImageDraw.Draw(image).rectangle((2, 2, 17, 37), fill="red")
    return image


@pytest.mark.parametrize("mirrored,head_left", [(False, 46.5), (True, 50.5)])
def test_visible_pixels_and_boxes_share_the_placement_transform(
    mirrored: bool, head_left: float
) -> None:
    """Mirroring and resizing move actual pixels and head bounds together."""
    picture, body, head = place_target(
        Image.new("RGB", (100, 100), "white"),
        sprite(),
        (3, 3, 9, 11),
        Placement(x=50, feet=70, height=20),
        mirrored=mirrored,
    )
    assert body == (46, 51, 54, 69)
    assert head[0] == head_left
    assert head[1:] == (51.5, head_left + 3, 55.5)
    assert picture.getpixel((48, 60)) == pytest.approx((255, 0, 0), abs=2)
    assert picture.getpixel((30, 60)) == (255, 255, 255)


def test_clipped_or_opaque_sprites_are_rejected() -> None:
    """Malformed assets cannot silently introduce a rectangular background or clipped target."""
    background = Image.new("RGB", (100, 100), "white")
    with pytest.raises(ValueError, match="clip"):
        place_target(
            background, sprite(), (3, 3, 9, 11), Placement(x=0, feet=70, height=20), mirrored=False
        )
    with pytest.raises(ValueError, match="transparent"):
        place_target(
            background,
            background,
            (3, 3, 9, 11),
            Placement(x=50, feet=70, height=20),
            mirrored=False,
        )


def test_new_compositions_do_not_reuse_saved_annotation_identities(tmp_path: Path) -> None:
    """Same inputs reproduce pixels; a new seed gets new IDs so corrections cannot drift."""
    sprite().save(tmp_path / "target.png")
    Image.new("RGB", (200, 200), "white").save(tmp_path / "crowd.png")
    config = Composition(
        sprite="target.png",
        head=(3, 3, 9, 11),
        backgrounds=[
            Backdrop(slug="crowd", title="Test", slots=[Placement(x=100, feet=150, height=100)])
        ],
    )
    first = compose_scenes(tmp_path, config)[0]
    replay = compose_scenes(tmp_path, config)[0]
    changed = compose_scenes(tmp_path, config.model_copy(update={"seed": 42}))[0]
    assert first.id == replay.id
    assert first.image.tobytes() == replay.image.tobytes()
    assert first.annotation == replay.annotation
    assert changed.id != first.id
    assert changed.annotation.source_id != first.annotation.source_id

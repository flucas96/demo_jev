"""Reproducibly place a transparent target in reviewed crowd-scene slots."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import cast

from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from .waldo_annotations import Annotation, Edges


class Placement(BaseModel):
    """A reviewed ground position and perspective-matched target height in source pixels."""

    x: int
    feet: int
    height: int = Field(gt=0)


class Backdrop(BaseModel):
    """A Waldo-free illustration and its unobstructed placement slots."""

    slug: str
    title: str
    slots: list[Placement] = Field(min_length=1)


class Composition(BaseModel):
    """Source geometry for a cropped transparent sprite and crowd backgrounds."""

    seed: int = 20261015
    sprite: str
    head: Edges
    backgrounds: list[Backdrop]


@dataclass
class ComposedScene:
    """An unmarked game image paired with exact transformed target bounds."""

    id: str
    title: str
    image: Image.Image
    annotation: Annotation


def place_target(
    background: Image.Image,
    sprite: Image.Image,
    head: Edges,
    slot: Placement,
    *,
    mirrored: bool,
) -> tuple[Image.Image, Edges, Edges]:
    """Composite one target and transform both boxes through the same resize and reflection."""
    if sprite.mode != "RGBA" or sprite.getchannel("A").getextrema()[0] == 255:
        raise ValueError("The Waldo sprite must have a transparent background.")
    alpha_bounds = sprite.getchannel("A").getbbox()
    if alpha_bounds is None:
        raise ValueError("The Waldo sprite is empty.")
    width = round(slot.height * sprite.width / sprite.height)
    resize = cast(Callable[[tuple[int, int], int], Image.Image], sprite.resize)
    target = resize((width, slot.height), Image.Resampling.LANCZOS)
    x = round(slot.x - width / 2)
    y = slot.feet - slot.height
    if x < 0 or y < 0 or x + width > background.width or slot.feet > background.height:
        raise ValueError("The placement would clip Waldo at the image edge.")
    if mirrored:
        target = ImageOps.mirror(target)

    def transform(bounds: Edges) -> Edges:
        """Apply the exact image placement transform to source-pixel edges."""
        left, top, right, bottom = bounds
        if mirrored:
            left, right = sprite.width - right, sprite.width - left
        return (
            x + left * width / sprite.width,
            y + top * slot.height / sprite.height,
            x + right * width / sprite.width,
            y + bottom * slot.height / sprite.height,
        )

    picture = background.convert("RGBA")
    picture.alpha_composite(target, (x, y))
    return picture.convert("RGB"), transform(alpha_bounds), transform(head)


def compose_scenes(sources: Path, config: Composition) -> list[ComposedScene]:
    """Render each reviewed slot once with seeded size, position, and facing variation."""
    with Image.open(sources / config.sprite) as original:
        sprite = original.convert("RGBA")
    scenes: list[ComposedScene] = []
    config_hash = hashlib.sha256(config.model_dump_json().encode()).digest()
    sprite_hash = hashlib.sha256(sprite.tobytes()).digest()
    for backdrop in config.backgrounds:
        with Image.open(sources / f"{backdrop.slug}.png") as original:
            background = original.convert("RGB")
        background_hash = hashlib.sha256(background.tobytes()).digest()
        for index, slot in enumerate(backdrop.slots):
            identity = hashlib.sha256(
                config_hash + sprite_hash + background_hash + str(index).encode()
            ).hexdigest()[:12]
            random = Random(identity)
            placement = Placement(
                x=slot.x + random.randint(-3, 3),
                feet=slot.feet + random.randint(-2, 2),
                height=slot.height + random.randint(-3, 3),
            )
            image, body, head = place_target(
                background, sprite, config.head, placement, mirrored=bool(random.getrandbits(1))
            )
            scenes.append(
                ComposedScene(
                    id=f"mix-{backdrop.slug}-{identity}",
                    title=f"{backdrop.title} · {index + 1:02}",
                    image=image,
                    annotation=Annotation(source_id=int(identity, 16), body=body, head=head),
                )
            )
    return scenes

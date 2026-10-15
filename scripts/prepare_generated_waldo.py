"""Package generated scenes at the API's maximum width without replacing saved corrections."""

import json
from pathlib import Path

from PIL import Image
from pydantic import TypeAdapter

from jev_demo.waldo_annotations import Annotation, normalize
from jev_demo.waldo_composition import Composition, compose_scenes

ASSETS = Path("backend/jev_demo/assets/waldo")
SOURCES = ASSETS / "generated-sources"


class GeneratedScene(Annotation):
    """A generated source image and its visually reviewed initial annotation."""

    puzzle_id: str
    slug: str
    title: str


def package_scene(
    picture: Image.Image,
    scene: GeneratedScene,
    annotations: dict[int, Annotation],
    *,
    procedural: bool = False,
) -> dict[str, object]:
    """Save API-sized image bytes and preserve corrections for an unchanged image identity."""
    crop = (0, 0, picture.width, picture.height)
    picture.thumbnail((1568, 1568), Image.Resampling.LANCZOS)
    picture.save(ASSETS / f"{scene.puzzle_id}.jpg", "JPEG", quality=97, subsampling=0)
    annotation = annotations.setdefault(
        scene.source_id, Annotation(source_id=scene.source_id, body=scene.body, head=scene.head)
    )
    return {
        "id": scene.puzzle_id,
        "mode": "sprint",
        "width": picture.width,
        "height": picture.height,
        "source_crop": crop,
        "source_id": scene.source_id,
        "reference": normalize(annotation.body, crop),
        "head": normalize(annotation.head, crop),
        "generated": True,
        "procedural": procedural,
        "title": scene.title,
    }


def main() -> None:
    """Encode compositions as baseline JPEGs while preserving saved annotation edits."""
    scenes = TypeAdapter(list[GeneratedScene]).validate_json(
        (SOURCES / "catalog.json").read_bytes()
    )
    annotations_path = ASSETS / "reviewed-annotations.json"
    annotations = {
        item.source_id: item
        for item in TypeAdapter(list[Annotation]).validate_json(annotations_path.read_bytes())
    }
    manifest_path = ASSETS / "manifest.json"
    identities = {scene.puzzle_id for scene in scenes}
    manifest = [
        item
        for item in TypeAdapter(list[dict[str, object]]).validate_json(manifest_path.read_bytes())
        if item.get("id") not in identities and not item.get("procedural")
    ]
    for scene in scenes:
        with Image.open(SOURCES / f"{scene.slug}.png") as original:
            picture = original.convert("RGB")
        manifest.append(package_scene(picture, scene, annotations))
    composition_path = SOURCES / "composition.json"
    if composition_path.exists():
        config = Composition.model_validate_json(composition_path.read_bytes())
        for composition in compose_scenes(SOURCES, config):
            scene = GeneratedScene(
                **composition.annotation.model_dump(),
                puzzle_id=composition.id,
                slug=composition.id,
                title=composition.title,
            )
            manifest.append(package_scene(composition.image, scene, annotations, procedural=True))
        with Image.open(SOURCES / config.sprite) as original:
            target = original.convert("RGBA")
        target.thumbnail((120, 240), Image.Resampling.LANCZOS)
        portrait = Image.new("RGB", target.size, "white")
        portrait.paste(target, mask=target.getchannel("A"))
        portrait.save(ASSETS / "target.jpg", "JPEG", quality=97)
    annotations_path.write_bytes(
        TypeAdapter(list[Annotation]).dump_json(list(annotations.values()), indent=2) + b"\n"
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"Prepared {sum(bool(item.get('generated')) for item in manifest)} generated scenes; "
        "archived originals and saved corrections preserved."
    )


if __name__ == "__main__":
    main()

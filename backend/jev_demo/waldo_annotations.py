"""Shared source-coordinate annotations for image preparation and manual corrections."""

from pydantic import BaseModel

type Edges = tuple[float, float, float, float]
type Crop = tuple[int, int, int, int]


class Annotation(BaseModel):
    """Reviewed visible-body and head edges in original source pixels."""

    source_id: int
    body: Edges
    head: Edges


def normalize(bounds: Edges, crop: Crop) -> dict[str, float]:
    """Apply the image crop's exact affine transform to a source annotation."""
    left, top, right, bottom = bounds
    x, y, width, height = crop
    return {
        "left": (left - x) / width,
        "right": (right - x) / width,
        "top": (top - y) / height,
        "bottom": (bottom - y) / height,
    }


def denormalize(bounds: Edges, crop: Crop) -> Edges:
    """Convert an edited display rectangle back to source pixels without rounding drift."""
    left, top, right, bottom = bounds
    x, y, width, height = crop
    return x + left * width, y + top * height, x + right * width, y + bottom * height

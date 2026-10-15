"""Validated normalized coordinates and overlap operations for localization games."""

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from .models import Probability


class Point(BaseModel):
    """A normalized human click within the displayed image."""

    model_config = ConfigDict(extra="forbid")
    x: Probability
    y: Probability


class Box(BaseModel):
    """Normalized image edges, independent of display scale and drag direction."""

    model_config = ConfigDict(extra="forbid")
    left: Probability
    right: Probability
    top: Probability
    bottom: Probability

    @model_validator(mode="after")
    def ordered_edges(self) -> Self:
        """Reject empty, reversed, or nonfinite rectangles before scoring."""
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("A box must have positive width and height.")
        return self

    @property
    def area(self) -> float:
        """Return the fraction of image area covered by this rectangle."""
        return (self.right - self.left) * (self.bottom - self.top)

    def padded(self, fraction: float) -> Box:
        """Expand each edge relative to the target size, clipped to the actual image."""
        dx = (self.right - self.left) * fraction
        dy = (self.bottom - self.top) * fraction
        return Box(
            left=max(0, self.left - dx),
            right=min(1, self.right + dx),
            top=max(0, self.top - dy),
            bottom=min(1, self.bottom + dy),
        )


def intersection(candidate: Box, reference: Box) -> float:
    """Return the shared normalized area of two rectangles."""
    return max(
        0.0, min(candidate.right, reference.right) - max(candidate.left, reference.left)
    ) * max(0.0, min(candidate.bottom, reference.bottom) - max(candidate.top, reference.top))


def overlap(candidate: Box, reference: Box) -> float:
    """Report body IoU for inspection; head-only hits do not need to match body proportions."""
    shared = intersection(candidate, reference)
    return shared / (candidate.area + reference.area - shared)

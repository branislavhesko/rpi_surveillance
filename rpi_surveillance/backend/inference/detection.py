"""Hardware-independent detection result shared by the detector and its users."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    """One detected object in frame pixel coordinates."""

    class_id: int
    label: str
    score: float  # 0..1
    box: tuple[int, int, int, int]

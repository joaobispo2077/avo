"""Immutable pacing seeds; targets never grant editorial deletion permission."""

from dataclasses import dataclass

FAMILIES = (
    "analysis-review",
    "tutorial",
    "interview-podcast",
    "narration-essay",
    "spoken-short",
    "react-gameplay",
)
INTENSITIES = ("conservative", "balanced", "dynamic")
_SEEDS = {
    "analysis-review": (
        (250, 700, 1800),
        ((None, 650, 750), (450, 450, 550), (300, 300, 400)),
    ),
    "tutorial": (
        (300, 900, 2200),
        ((None, 800, 1000), (550, 650, 800), (400, 450, 600)),
    ),
    "interview-podcast": (
        (350, 1000, 2500),
        ((None, 1000, 1200), (700, 800, 1000), (550, 600, 800)),
    ),
    "narration-essay": (
        (250, 650, 1600),
        ((None, 650, 800), (400, 500, 650), (300, 350, 450)),
    ),
    "spoken-short": (
        (200, 500, 1200),
        ((None, 450, 550), (300, 350, 450), (200, 250, 350)),
    ),
    "react-gameplay": (
        (300, 800, 2000),
        ((None, 750, 1000), (500, 600, 800), (350, 450, 650)),
    ),
}


@dataclass(frozen=True)
class CutProfile:
    family: str
    intensity: str
    upper_bounds_ms: tuple[int, int, int]
    targets_ms: tuple[int | None, int | None, int | None]
    calibration_status: str = "unvalidated-seed"

    def pause_band(self, duration_ms: int) -> str:
        if (
            isinstance(duration_ms, bool)
            or not isinstance(duration_ms, int)
            or duration_ms < 0
        ):
            raise ValueError(
                "pause duration must be a nonnegative integer in milliseconds"
            )
        for name, upper in zip(("micro", "quick", "medium"), self.upper_bounds_ms):
            if duration_ms < upper:
                return name
        return "long"

    def retention_target(self, band: str) -> int | None:
        if band == "micro":
            return None
        return self.targets_ms[("quick", "medium", "long").index(band)]

    def payload(self) -> dict:
        return {
            "family": self.family,
            "intensity": self.intensity,
            "pauseBands": dict(zip(("micro", "quick", "medium"), self.upper_bounds_ms)),
            "retention": dict(zip(("quick", "medium", "long"), self.targets_ms)),
            "calibrationStatus": self.calibration_status,
        }


def get_profile(family: str, intensity: str = "balanced") -> CutProfile:
    if family not in _SEEDS or intensity not in INTENSITIES:
        raise ValueError("unknown cutting family or intensity")
    bands, targets = _SEEDS[family]
    return CutProfile(family, intensity, bands, targets[INTENSITIES.index(intensity)])

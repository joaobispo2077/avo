"""Shared native programme clock admission for explicit authoring requests."""

from fractions import Fraction


class ProgramClockError(ValueError):
    pass


def require_program_clock(workspace, clock, *, subject):
    from .bmap_service import BMapService
    from .initial_cut import _clock_boundary, _precise_clock_mode
    from .mapping import cmap_output_duration, cmap_output_timebase

    if workspace.authority != "canonical":
        raise ProgramClockError(f"{subject} proposals require a canonical approved cut")
    _, cmap, _ = BMapService(workspace).current_basis()
    snapshot = cmap["snapshot"]
    base = cmap_output_timebase(snapshot)
    fps = Fraction(clock["frameRate"]["num"], clock["frameRate"]["den"])
    extent = Fraction(cmap_output_duration(snapshot) * base["num"], base["den"]) * fps
    if snapshot.get("layoutMode") == "placed":
        canonical_rate = snapshot["layout"]["programClock"]["frameRate"]
        if fps != Fraction(canonical_rate["num"], canonical_rate["den"]):
            raise ProgramClockError(
                f"{subject} clock differs from the placed picture clock"
            )
    else:
        extent = _clock_boundary(extent, _precise_clock_mode(workspace, snapshot))
    if extent != clock["programEndFrame"]:
        raise ProgramClockError(
            f"{subject} clock differs from the approved program extent"
        )
    return fps

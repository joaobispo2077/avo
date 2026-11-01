"""One immutable timeline validation batch shares byte and pixel observations."""

from contextlib import contextmanager
from contextvars import ContextVar

from avo.timeline.contracts import fingerprint_stage

_PIXEL_OBSERVATIONS: ContextVar[dict | None] = ContextVar(
    "proof_pixel_observations", default=None
)


def in_proof_validation_batch() -> bool:
    return _PIXEL_OBSERVATIONS.get() is not None


def proof_pixel_observations() -> dict | None:
    return _PIXEL_OBSERVATIONS.get()


@contextmanager
def proof_validation_batch():
    """Return only after every observed file passes a fresh final hash."""
    with fingerprint_stage(verify_on_exit=True):
        token = _PIXEL_OBSERVATIONS.set({})
        try:
            yield
        finally:
            _PIXEL_OBSERVATIONS.reset(token)

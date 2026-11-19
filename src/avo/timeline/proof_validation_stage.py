"""One immutable timeline validation batch shares byte and pixel observations."""

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path

from avo.timeline.contracts import ContractError, file_fingerprint, fingerprint_stage

_PIXEL_OBSERVATIONS: ContextVar[dict | None] = ContextVar(
    "proof_pixel_observations", default=None
)
_BATCH_RESOURCES: ContextVar[ExitStack | None] = ContextVar(
    "proof_batch_resources", default=None
)
_BATCH_DEPENDENCIES: ContextVar[dict | None] = ContextVar(
    "proof_batch_dependencies", default=None
)


def in_proof_validation_batch() -> bool:
    return _PIXEL_OBSERVATIONS.get() is not None


def proof_pixel_observations() -> dict | None:
    return _PIXEL_OBSERVATIONS.get()


def proof_batch_resources() -> ExitStack | None:
    return _BATCH_RESOURCES.get()


def track_proof_dependency(fingerprint: dict) -> None:
    """Keep a nested renderer's dependency inside the enclosing byte guard."""
    dependencies = _BATCH_DEPENDENCIES.get()
    if dependencies is None:
        raise RuntimeError("Proof dependency tracking requires a validation batch")
    path = str(Path(fingerprint["locator"]).resolve())
    previous = dependencies.setdefault(path, deepcopy(fingerprint))
    if any(previous[key] != fingerprint[key] for key in ("sha256", "sizeBytes")):
        raise ContractError(f"Proof batch dependency changed: {path}")


def _enroll_batch_dependencies(dependencies):
    for path, expected in dependencies.items():
        try:
            actual = file_fingerprint(Path(path))
        except OSError as error:
            raise ContractError(f"Proof batch dependency is missing: {path}") from error
        if any(actual[key] != expected[key] for key in ("sha256", "sizeBytes")):
            raise ContractError(f"Proof batch dependency changed: {path}")


@contextmanager
def proof_validation_batch(*, reuse_video_stages=False):
    """Return only after every observed file passes a fresh final hash."""
    # Temporary stages must survive both dependency enrollment and the fresh guard.
    with ExitStack() as resources, fingerprint_stage(verify_on_exit=True):
        dependencies = {}
        pixel_token = _PIXEL_OBSERVATIONS.set({})
        resource_token = _BATCH_RESOURCES.set(resources if reuse_video_stages else None)
        dependency_token = _BATCH_DEPENDENCIES.set(dependencies)
        try:
            yield
            _enroll_batch_dependencies(dependencies)
        finally:
            _BATCH_DEPENDENCIES.reset(dependency_token)
            _BATCH_RESOURCES.reset(resource_token)
            _PIXEL_OBSERVATIONS.reset(pixel_token)

"""Concrete proof dependencies for entry points and legacy default bridges.

Timeline application services receive these dependencies explicitly from CLI.
Legacy calls may resolve the same defaults here without constructing adapters
inside the timeline. Imports stay lazy to preserve optional tool loading.
"""

from pathlib import Path


def create_timeline_render_port():
    from avo.adapters.media.timeline_render import TimelineRenderAdapter

    return TimelineRenderAdapter()


def create_sync_materializer():
    from avo.adapters.media.sync_materializer import SyncMaterializer

    return SyncMaterializer()


def probe_audio_sample_rate(selection: dict, locator: Path) -> int:
    from avo.adapters.media.ffprobe import audio_sample_rate

    return audio_sample_rate(selection, locator)

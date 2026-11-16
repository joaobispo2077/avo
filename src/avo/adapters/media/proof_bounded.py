"""Private bounded-storage execution of the canonical placed picture graph.

Placement decoders retain their complete sampling/fade state. Only raw picture
windows touch scratch; generated overlays and audio enter one final encoder.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path

from avo.timeline.contracts import file_fingerprint, fingerprint_stage
from avo.timeline.proof_validation_stage import in_proof_validation_batch

from .proof_stream import ManagedProcess, StorageBudget, copy_frames, pump_file

MAX_CHUNK_FRAMES = 60
_MIX_OBSERVER = ContextVar("placed_mix_observer", default=None)


@contextmanager
def observe_mix(observer):
    """Let an in-process job qualify its exact continuous mix before picture."""
    token = _MIX_OBSERVER.set(observer)
    try:
        yield
    finally:
        _MIX_OBSERVER.reset(token)


class _PictureCursor:
    def __init__(self, source, directory, spec, fps, ordinal):
        from . import proof_placed as placed

        self.source = source
        self.stack = ExitStack()
        item = source["item"]
        self.remaining = (
            item["outputRange"]["endFrameExclusive"] - item["outputRange"]["startFrame"]
        )
        transform = placed._scaled_transform(item, spec)
        self.width = transform["width"] if transform else spec["width"]
        self.height = transform["height"] if transform else spec["height"]
        self.bytes_per_frame = self.width * self.height * 4
        try:
            if item["mediaKind"] == "title":
                from .proof_title import title_command

                self.width, self.height = spec["width"], spec["height"]
                self.bytes_per_frame = self.width * self.height * 4
                arguments, cwd = self.stack.enter_context(
                    title_command(
                        source,
                        directory,
                        spec,
                        fps,
                        self.remaining,
                        placed._picture_fades(item, self.remaining),
                    )
                )
            else:
                arguments, count = placed._picture_arguments(source, spec, fps)
                if count != self.remaining:
                    raise RuntimeError("Placement decoder frame contract differs")
                cwd = None
            self.process = self.stack.enter_context(
                ManagedProcess(
                    [
                        *arguments,
                        "-c:v",
                        "rawvideo",
                        "-pix_fmt",
                        "bgra",
                        "-f",
                        "rawvideo",
                        "pipe:1",
                    ],
                    stderr_path=directory / f"decoder-{ordinal:04d}.log",
                    stdout=True,
                    cwd=cwd,
                )
            )
        except BaseException:
            self.stack.close()
            raise

    def take(self, path, frames, monitor):
        if not 0 < frames <= self.remaining:
            raise RuntimeError("Placement cursor would consume outside its extent")
        copy_frames(
            self.process.stdout,
            path,
            bytes_per_frame=self.bytes_per_frame,
            frame_count=frames,
            verify_eof=frames == self.remaining,
            monitor=monitor,
        )
        self.remaining -= frames
        if self.remaining == 0:
            self.stack.close()
        return {"path": path, "width": self.width, "height": self.height}

    def close(self):
        if self.remaining:
            failure = RuntimeError("Placement cursor cancelled before EOF")
            self.stack.__exit__(type(failure), failure, None)
        else:
            self.stack.close()


def _picture_cost(sources, spec):
    from . import proof_placed as placed

    cost = spec["width"] * spec["height"] * 4
    for source in sources:
        item = source["item"]
        transform = placed._scaled_transform(item, spec)
        if transform and item["mediaKind"] != "title":
            cost += transform["width"] * transform["height"] * 4
        else:
            cost += spec["width"] * spec["height"] * 4
    return cost


def _intersect(source, first, last):
    item = source["item"]
    region = item["outputRange"]
    return (
        item["enabled"]
        and region["startFrame"] < last
        and region["endFrameExclusive"] > first
    )


def _audio_scratch_bytes(graph, samples):
    # Native mixing retains each admitted source PCM until the complete mix
    # exists. Counting duplicate nodes again is conservative and avoids relying
    # on a cache's path/range equivalence for disk safety.
    total = samples * 8 + 4096
    for node in graph["nodes"]:
        if node["kind"] != "silence":
            region = node["outputRange"]
            total += (region["endSampleExclusive"] - region["startSample"]) * 8 + 4096
    return total


def _reserve_audio(budget, needed, mix_size):
    budget.check()
    # Source PCM exists only while mixing. Its native TemporaryDirectory must
    # close successfully before this function's caller can start picture work.
    # Reserve the larger phase, retaining the final mix in both, rather than
    # charging source PCM and the later candidate simultaneously.
    required = budget.headroom + max(needed, budget.candidate_reserve + mix_size)
    if shutil.disk_usage(budget.directory).free < required:
        raise RuntimeError("Insufficient space for source PCM and complete audio mix")


def _publish(candidate, output):
    # Same-filesystem hard-link creation is atomic and refuses an existing
    # destination on both Windows and POSIX, unlike POSIX rename.
    os.link(candidate, output)
    try:
        candidate.unlink()
    except BaseException:
        if output.samefile(candidate):
            output.unlink()
        raise


def _verify_mix(mixed, audio):
    with fingerprint_stage():
        if file_fingerprint(mixed) != audio["output"]:
            raise RuntimeError("Continuous audio mix changed within this render job")


def _candidate_size(candidate):
    return candidate.stat().st_size if candidate.exists() else 0


def _stage_chunk(
    sources, cursors, directory, diagnostics, spec, fps, first, last, monitor
):
    staged = []
    for ordinal, source in enumerate(sources):
        if not _intersect(source, first, last):
            continue
        item = source["item"]
        identity = item["placementId"]
        if identity not in cursors:
            cursors[identity] = _PictureCursor(source, diagnostics, spec, fps, ordinal)
        region = item["outputRange"]
        start = max(first, region["startFrame"])
        end = min(last, region["endFrameExclusive"])
        path = directory / f"layer-{ordinal:04d}.bgra"
        descriptor = cursors[identity].take(path, end - start, monitor)
        staged.append(
            (
                {
                    **item,
                    "outputRange": {"startFrame": start, "endFrameExclusive": end},
                },
                descriptor,
            )
        )
    return staged


def _stream_picture(
    execution,
    sources,
    directory,
    candidate,
    spec,
    fps,
    total,
    mixed,
    overlays,
    budget,
    diagnostics,
):
    from . import proof_executor as native
    from . import proof_placed as placed

    arguments, metadata = native._final_arguments(
        [
            "-f",
            "rawvideo",
            "-pixel_format",
            "bgra",
            "-video_size",
            f"{spec['width']}x{spec['height']}",
            "-framerate",
            str(fps),
            "-i",
            "pipe:0",
        ],
        candidate,
        overlays,
        spec,
        fps,
        0,
        total,
        mixed,
    )
    cursors = {}
    frames, chunks, peak_scratch = 0, 0, 0

    def monitor():
        size = _candidate_size(candidate)
        budget.check(candidate_size=size)

    try:
        with ManagedProcess(
            arguments, stdin=True, stderr_path=diagnostics / "encoder.log"
        ) as encoder:
            while frames < total:
                possible = [
                    s
                    for s in sources
                    if _intersect(s, frames, min(total, frames + MAX_CHUNK_FRAMES))
                ]
                count = budget.chunk_frames(
                    _picture_cost(possible, spec),
                    total - frames,
                    candidate_size=_candidate_size(candidate),
                )
                last = frames + count
                staged = _stage_chunk(
                    sources,
                    cursors,
                    directory,
                    diagnostics,
                    spec,
                    fps,
                    frames,
                    last,
                    monitor,
                )
                picture = directory / "picture.bgra"
                monitor()
                placed._compose_picture(
                    staged,
                    picture,
                    spec,
                    fps,
                    (frames, last),
                    placed._layout_operation(execution)["parameters"].get(
                        "privacyMasks"
                    ),
                    raw=True,
                )
                scratch = sum(p.stat().st_size for p in directory.iterdir())
                peak_scratch = max(peak_scratch, scratch)
                monitor()
                written = pump_file(picture, encoder.stdin)
                if written != count * spec["width"] * spec["height"] * 4:
                    raise RuntimeError("Final encoder input frame count differs")
                for path in directory.iterdir():
                    path.unlink()
                frames, chunks = last, chunks + 1
                # Diagnostics survive failure without retaining consumed scratch.
                (diagnostics / "progress.json").write_text(
                    json.dumps(
                        {
                            "frames": frames,
                            "totalFrames": total,
                            "chunks": chunks,
                            "maxChunkFrames": MAX_CHUNK_FRAMES,
                            "peakPictureScratchBytes": peak_scratch,
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
            if any(cursor.remaining for cursor in cursors.values()):
                raise RuntimeError("Placement decoder has unconsumed frames")
    finally:
        # ExitStack attempts every close even if an earlier child/temporary
        # title folder raises during cleanup.
        with ExitStack() as cleanup:
            for cursor in cursors.values():
                cleanup.callback(cursor.close)
    return metadata


def render_bounded(
    execution,
    output,
    admitted,
    total,
    spec,
    fps,
    resolver,
    generated,
    generated_asset_validator,
):
    from . import proof_executor as native
    from . import proof_placed as placed

    if output.exists():
        raise RuntimeError(f"Refusing to replace existing proof: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep small diagnostics after failure. Temporary media alone is ephemeral.
    diagnostics = Path(tempfile.mkdtemp(prefix="proof-bounded-log-", dir=output.parent))
    candidate = diagnostics / (
        "candidate.mkv" if spec.get("conformance") is True else "candidate.mp4"
    )
    try:
        with (
            fingerprint_stage(reuse_current=in_proof_validation_batch()),
            tempfile.TemporaryDirectory(
                prefix="proof-bounded-", dir=output.parent
            ) as folder,
        ):
            directory = Path(folder)
            scratch = directory / "picture"
            scratch.mkdir()
            budget = StorageBudget(scratch, max_frames=MAX_CHUNK_FRAMES)
            samples = placed._sample_boundary(total, fps)
            _reserve_audio(
                budget,
                _audio_scratch_bytes(execution["audioGraph"], samples),
                samples * 8 + 4096,
            )
            mixed = directory / "mix.wav"
            with fingerprint_stage():
                audio = placed.render_proof_audio_mix(
                    execution["audioGraph"],
                    mixed,
                    source_resolver=resolver,
                    window=(0, samples),
                )
            budget.check(mixed_size=mixed.stat().st_size)
            observer = _MIX_OBSERVER.get()
            if observer is not None:
                observer(mixed, audio, spec)
            _verify_mix(mixed, audio)
            ordered = sorted(
                admitted, key=lambda s: (s["item"]["zOrder"], s["item"]["placementId"])
            )
            metadata = _stream_picture(
                execution,
                ordered,
                scratch,
                candidate,
                spec,
                fps,
                total,
                mixed,
                native._proof_overlays(generated, total),
                budget,
                diagnostics,
            )
            _verify_mix(mixed, audio)
            media = native._check_encoded(candidate, fps, total)
            placed._revalidate_sources(
                execution,
                [s["item"] for s in admitted],
                generated,
                generated_asset_validator,
            )
            budget.check(candidate_size=candidate.stat().st_size)
            (diagnostics / "complete.json").write_text(
                json.dumps(
                    {
                        "status": "verified-before-publication",
                        "frames": total,
                        "audioMix": audio,
                        "continuousEncoder": True,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        # Scratch cleanup and every fallible validation/receipt precede the
        # sole publication step. A concurrent destination must not be replaced.
        if output.exists():
            raise RuntimeError(f"Refusing to replace existing proof: {output}")
        _publish(candidate, output)
    except BaseException as exc:
        candidate.unlink(missing_ok=True)
        # Child stderr and progress live outside ephemeral media scratch.
        (diagnostics / "failure.json").write_text(
            json.dumps(
                {
                    "status": "fail",
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        raise
    return media, audio, metadata

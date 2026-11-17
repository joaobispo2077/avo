"""Job-level ownership and ordering for one continuous bounded proof encoder."""

import io
import json
from contextlib import contextmanager
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

import pytest

from avo.adapters.media import proof_bounded, proof_executor, proof_placed, proof_stream
from avo.timeline.contracts import file_fingerprint


@pytest.fixture
def job(tmp_path, monkeypatch):
    state = SimpleNamespace(
        fault=None,
        events=[],
        windows=[],
        cursors=[],
        encoder_count=0,
        encoder_closed=0,
        candidate=None,
        mixed=None,
        written=None,
        checks=[],
    )
    state.output = tmp_path / "published.mkv"
    state.sentinel = tmp_path / "unrelated.txt"
    state.sentinel.write_text("retain this file", encoding="utf-8")
    state.audio_receipt = {"mixIdentity": "one-canonical-continuous-mix"}
    state.spec = {"width": 2, "height": 1, "conformance": True}
    state.source = {
        "item": {
            "placementId": "one-picture",
            "mediaKind": "video",
            "enabled": True,
            "zOrder": 0,
            "outputRange": {"startFrame": 0, "endFrameExclusive": 7},
        }
    }
    state.execution = {
        "audioGraph": {"nodes": [{"kind": "silence"}]},
        "videoGraph": {"operations": [{"kind": "source-layout", "parameters": {}}]},
    }
    monkeypatch.setattr(proof_bounded, "MAX_CHUNK_FRAMES", 3)
    monkeypatch.setattr(
        proof_stream.shutil, "disk_usage", lambda path: SimpleNamespace(free=10**12)
    )

    def make_budget(directory, *, max_frames):
        value = proof_stream.StorageBudget(
            directory,
            candidate_reserve=4096,
            headroom=0,
            scratch_limit=1024**2,
            max_frames=max_frames,
        )
        check = value.check

        def checked(*args, **kwargs):
            state.checks.append(kwargs)
            if state.fault == "disk":
                raise proof_stream.StreamError("disk capacity exhausted")
            return check(*args, **kwargs)

        value.check = checked
        return value

    def mix(graph, output, *, source_resolver, window):
        assert graph is state.execution["audioGraph"]
        assert window == (0, 14000)
        assert source_resolver is state.resolver
        assert not state.events
        state.events.append("mix")
        output.write_bytes(b"exact-continuous-PCM")
        state.mixed = output
        state.audio_receipt["output"] = file_fingerprint(output)
        return state.audio_receipt

    def final_arguments(inputs, candidate, overlays, spec, fps, first, last, mixed):
        assert mixed == state.mixed and mixed.read_bytes() == b"exact-continuous-PCM"
        assert (first, last, fps) == (0, 7, Fraction(24))
        assert spec is state.spec
        state.events.append("encoder-arguments")
        state.candidate = candidate
        return ["one-native-encoder"], {"continuous": True}

    class EncoderInput(io.BytesIO):
        def write(self, data):
            if state.fault == "encoder" and self.tell():
                state.candidate.write_bytes(b"partial-encode")
                raise BrokenPipeError("encoder failed during later chunk")
            return super().write(data)

    @contextmanager
    def encoder(arguments, *, stdin, stderr_path):
        assert arguments == ["one-native-encoder"] and stdin is True
        state.encoder_count += 1
        state.events.append("encoder-open")
        stream = EncoderInput()
        stderr_path.write_text("durable native diagnostic", encoding="utf-8")
        try:
            yield SimpleNamespace(stdin=stream)
            state.written = stream.getvalue()
            state.candidate.write_bytes(b"complete-encode")
        finally:
            state.encoder_closed += 1
            stream.close()

    class Cursor:
        def __init__(self, source, directory, spec, fps, ordinal):
            assert source is state.source
            self.remaining, self.calls, self.closed = 7, 0, False
            state.cursors.append(self)

        def take(self, path, frames, monitor):
            self.calls += 1
            if state.fault == "decoder" and self.calls == 2:
                path.write_bytes(b"partial-frame")
                raise proof_stream.StreamError("decoder stopped before EOF")
            monitor()
            path.write_bytes(b"L" * frames * 8)
            self.remaining -= frames
            return {"path": path, "width": 2, "height": 1}

        def close(self):
            self.closed = True

    def compose(staged, output, spec, fps, window, masks, *, raw):
        assert raw is True and masks is None
        assert staged[0][1]["path"].is_file()
        state.windows.append(window)
        output.write_bytes(b"".join(bytes([frame]) * 8 for frame in range(*window)))

    def check_encoded(candidate, fps, count):
        assert candidate.read_bytes() == b"complete-encode"
        state.events.append("encoded-check")
        return {"frames": count}

    def revalidate(*args):
        state.events.append("source-check")
        if state.fault == "source":
            raise RuntimeError("canonical source changed before publication")

    state.resolver = lambda source: source
    monkeypatch.setattr(proof_bounded, "StorageBudget", make_budget)
    monkeypatch.setattr(proof_bounded, "ManagedProcess", encoder)
    monkeypatch.setattr(proof_bounded, "_PictureCursor", Cursor)
    monkeypatch.setattr(proof_placed, "render_proof_audio_mix", mix)
    monkeypatch.setattr(proof_placed, "_compose_picture", compose)
    monkeypatch.setattr(proof_placed, "_revalidate_sources", revalidate)
    monkeypatch.setattr(proof_executor, "_final_arguments", final_arguments)
    monkeypatch.setattr(proof_executor, "_check_encoded", check_encoded)
    return state


def _render(job):
    return proof_bounded.render_bounded(
        job.execution,
        job.output,
        [job.source],
        7,
        job.spec,
        Fraction(24),
        job.resolver,
        {},
        None,
    )


def _diagnostics(job):
    folders = list(job.output.parent.glob("proof-bounded-log-*"))
    assert len(folders) == 1
    assert job.sentinel.read_text(encoding="utf-8") == "retain this file"
    assert not [
        path
        for path in job.output.parent.glob("proof-bounded-*")
        if path not in folders
    ]
    assert not list(folders[0].rglob("*.bgra"))
    assert not list(folders[0].rglob("*.wav"))
    assert not list(folders[0].rglob("*.mkv"))
    return folders[0]


def test_one_mix_is_observed_before_one_continuous_encoder_across_chunks(job):
    observed = []

    def observer(path, receipt, spec):
        assert path == job.mixed and path.read_bytes() == b"exact-continuous-PCM"
        assert receipt is job.audio_receipt and spec is job.spec
        assert job.events == ["mix"]
        observed.append(path)
        job.events.append("observer")

    with proof_bounded.observe_mix(observer):
        media, audio, metadata = _render(job)
    assert job.events == [
        "mix",
        "observer",
        "encoder-arguments",
        "encoder-open",
        "encoded-check",
        "source-check",
    ]
    assert len(observed) == 1 and not observed[0].exists()
    assert job.encoder_count == job.encoder_closed == 1
    assert len(job.cursors) == 1 and job.cursors[0].closed
    assert job.windows == [(0, 3), (3, 6), (6, 7)]
    assert job.written == b"".join(bytes([frame]) * 8 for frame in range(7))
    assert (media, audio, metadata) == (
        {"frames": 7},
        job.audio_receipt,
        {"continuous": True},
    )
    assert job.output.read_bytes() == b"complete-encode"
    diagnostic = _diagnostics(job)
    assert json.loads((diagnostic / "complete.json").read_text())["frames"] == 7
    assert not (diagnostic / "failure.json").exists()
    assert proof_bounded._MIX_OBSERVER.get() is None


@pytest.mark.parametrize("fault", ["disk", "decoder", "encoder", "source"])
def test_failure_never_publishes_and_cleans_only_owned_media(job, fault):
    job.fault = fault
    with pytest.raises(RuntimeError, match="disk|decoder|encoder|source"):
        _render(job)
    assert not job.output.exists()
    assert job.events.count("mix") <= 1
    assert job.encoder_count == job.encoder_closed
    assert all(cursor.closed for cursor in job.cursors)
    diagnostic = _diagnostics(job)
    failure = json.loads((diagnostic / "failure.json").read_text())
    assert failure["status"] == "fail" and fault in failure["message"]
    assert not (diagnostic / "complete.json").exists()
    if fault == "disk":
        assert job.events == []
    else:
        assert (diagnostic / "encoder.log").read_text() == "durable native diagnostic"


def test_receipt_write_failure_precedes_publication_and_removes_candidate(
    job, monkeypatch
):
    write_text = Path.write_text

    def reject_complete(path, *args, **kwargs):
        if path.name == "complete.json":
            raise OSError("completion receipt disk failure")
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", reject_complete)
    with pytest.raises(OSError, match="receipt disk"):
        _render(job)
    assert not job.output.exists()
    diagnostic = _diagnostics(job)
    assert (
        "receipt disk"
        in json.loads((diagnostic / "failure.json").read_text())["message"]
    )


def test_existing_destination_is_retained_before_any_work(job):
    job.output.write_bytes(b"existing-approved-file")
    with pytest.raises(RuntimeError, match="Refusing to replace"):
        _render(job)
    assert job.output.read_bytes() == b"existing-approved-file"
    assert job.events == []
    assert not list(job.output.parent.glob("proof-bounded-*"))


def test_concurrent_destination_wins_atomic_publication_without_being_replaced(
    job, monkeypatch
):
    link = proof_bounded.os.link

    def concurrent_link(candidate, output):
        assert not output.exists()
        output.write_bytes(b"concurrent-approved-file")
        return link(candidate, output)

    monkeypatch.setattr(proof_bounded.os, "link", concurrent_link)
    with pytest.raises(FileExistsError):
        _render(job)
    assert job.output.read_bytes() == b"concurrent-approved-file"
    diagnostic = _diagnostics(job)
    assert json.loads((diagnostic / "failure.json").read_text())["status"] == "fail"


def test_publication_rolls_back_own_link_if_candidate_unlink_fails(
    tmp_path, monkeypatch
):
    candidate, output = tmp_path / "candidate.mkv", tmp_path / "published.mkv"
    candidate.write_bytes(b"verified-candidate")
    unlink = Path.unlink

    def fail_candidate(path, *args, **kwargs):
        if path == candidate:
            raise PermissionError("candidate cleanup refused")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_candidate)
    with pytest.raises(PermissionError, match="candidate cleanup"):
        proof_bounded._publish(candidate, output)
    assert candidate.read_bytes() == b"verified-candidate"
    assert not output.exists()


@pytest.mark.parametrize(
    "audio_bytes,mix_bytes",
    [
        pytest.param(6246873936, 1716292096, id="current-candidate-dominated"),
        pytest.param(18 * 1024**3, 2 * 1024**3, id="source-pcm-dominated"),
    ],
)
def test_audio_reservation_uses_peak_phase_and_preserves_headroom(
    tmp_path, monkeypatch, audio_bytes, mix_bytes
):
    gib = 1024**3
    candidate, headroom = 12 * gib, 2 * gib
    required = headroom + max(audio_bytes, candidate + mix_bytes)
    strict_sum = headroom + candidate + audio_bytes
    assert required < strict_sum
    # Both phases fit independently even when their combined historical estimate
    # exceeds available space. The retained mix is already part of audio_bytes.
    free = [(required + strict_sum) // 2]
    monkeypatch.setattr(
        proof_stream.shutil, "disk_usage", lambda path: SimpleNamespace(free=free[0])
    )
    budget = proof_stream.StorageBudget(tmp_path, scratch_limit=6 * gib)
    proof_bounded._reserve_audio(budget, audio_bytes, mix_bytes)
    free[0] = required
    proof_bounded._reserve_audio(budget, audio_bytes, mix_bytes)
    free[0] = required - 1
    with pytest.raises(RuntimeError, match="space|phase|PCM"):
        proof_bounded._reserve_audio(budget, audio_bytes, mix_bytes)
    assert list(tmp_path.iterdir()) == []


def test_audio_reservation_counts_all_source_pcm_even_when_ranges_overlap():
    graph = {
        "nodes": [
            {"kind": "silence"},
            {
                "kind": "source",
                "outputRange": {"startSample": 0, "endSampleExclusive": 48000},
            },
            {
                "kind": "source",
                "outputRange": {"startSample": 24000, "endSampleExclusive": 72000},
            },
        ]
    }
    assert proof_bounded._audio_scratch_bytes(graph, 96000) == (
        (96000 + 48000 + 48000) * 8 + 3 * 4096
    )


def test_mix_observer_rejection_stops_before_picture_and_resets_scope(job):
    def reject_mix(path, receipt, spec):
        assert path == job.mixed and receipt is job.audio_receipt and spec is job.spec
        raise RuntimeError("continuous mix qualification rejected")

    with pytest.raises(RuntimeError, match="mix qualification rejected"):
        with proof_bounded.observe_mix(reject_mix):
            _render(job)
    assert job.events == ["mix"]
    assert job.encoder_count == 0 and not job.output.exists()
    assert proof_bounded._MIX_OBSERVER.get() is None
    diagnostic = _diagnostics(job)
    assert (
        "mix qualification"
        in json.loads((diagnostic / "failure.json").read_text())["message"]
    )


def test_observer_cannot_change_the_fingerprinted_mix_before_picture(job):
    def mutate_mix(path, receipt, spec):
        path.write_bytes(b"altered-continuous-PCM")

    with pytest.raises(RuntimeError, match="mix|PCM"):
        with proof_bounded.observe_mix(mutate_mix):
            _render(job)
    assert job.events == ["mix"]
    assert job.encoder_count == 0 and not job.output.exists()
    diagnostic = _diagnostics(job)
    assert json.loads((diagnostic / "failure.json").read_text())["status"] == "fail"

"""Materialize canonically bound HyperFrames source as verified silent lossless media."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

from avo.paths import repo_root
from avo.timeline.contracts import (
    document_hash_excluding,
    file_fingerprint,
    fingerprint_stage,
)
from avo.timeline.generated_assets import GeneratedAssetService
from avo.timeline.hyperframes_binding import resolve_binding, verify_binding
from avo.timeline.store import write_immutable_json


class HyperframesMaterializeError(RuntimeError):
    """Source, runtime, seek or lossless output verification failed."""


SNAPSHOT_CHUNK_SIZE = 128


def _require(condition, message):
    if not condition:
        raise HyperframesMaterializeError(message)


def _browser_executable():
    browser = os.environ.get("HYPERFRAMES_BROWSER_PATH")
    if browser:
        browser_path = Path(browser).resolve()
        _require(browser_path.is_file(), "Configured HyperFrames browser is missing")
    else:
        cache = Path.home() / ".cache/hyperframes"
        matches = (
            sorted(
                p.resolve()
                for p in cache.rglob("*")
                if p.is_file()
                and p.name in {"chrome-headless-shell", "chrome-headless-shell.exe"}
            )
            if cache.is_dir()
            else []
        )
        _require(
            len(matches) == 1,
            "Set HYPERFRAMES_BROWSER_PATH to one existing cached browser; no installation is allowed",
        )
        browser_path = matches[0]
    return str(browser_path)


def _tool_environment(root):
    from avo.adapters.motion import hyperframes as adapter_module
    from avo.timeline import hyperframes_binding as binding_module

    package = root / "node_modules/hyperframes"
    manifest = package / "package.json"
    _require(manifest.is_file(), "Installed local HyperFrames package is required")
    version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
    _require(isinstance(version, str) and version, "HyperFrames version is unavailable")
    executables = {}
    for name in ("node", "ffmpeg", "ffprobe"):
        path = shutil.which(name)
        _require(
            path and Path(path).is_file(), f"Installed {name} executable is required"
        )
        executables[name] = str(Path(path).resolve())
    executables["browser"] = _browser_executable()
    cli = package / "bin/hyperframes.mjs"
    distribution = sorted((package / "dist").rglob("*.js"))
    _require(
        cli.is_file() and distribution,
        "HyperFrames CLI/distribution closure is missing",
    )
    paths = [Path(p) for p in executables.values()] + [
        Path(sys.executable),
        cli,
        manifest,
        *distribution,
        Path(__file__),
        Path(adapter_module.__file__),
        Path(binding_module.__file__),
    ]
    files = [file_fingerprint(p) for p in sorted({p.resolve() for p in paths})]
    commands = {
        "node": [executables["node"], "--version"],
        "hyperframes": [executables["node"], str(cli), "--version"],
        "ffmpeg": [executables["ffmpeg"], "-version"],
        "ffprobe": [executables["ffprobe"], "-version"],
        "browser": [executables["browser"], "--version"],
    }
    versions = {}
    for name, command in commands.items():
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=30, check=False
        )
        _require(result.returncode == 0, f"Cannot observe {name} version")
        lines = (result.stdout or result.stderr).splitlines()
        _require(lines, f"Missing {name} version output")
        versions[name] = lines[0].strip()
    result = {
        "version": version,
        "versions": versions,
        "executables": executables,
        "files": files,
        "renderMode": {"browserGpu": False, "bestEffortFrames": False},
    }
    result["hash"] = document_hash_excluding(result, "hash")
    return result


def _tool_inputs(environment):
    return sorted(
        [
            {
                "artifactId": "hyperframes-tool:"
                + hashlib.sha256(item["locator"].encode()).hexdigest()[:24],
                "fingerprint": deepcopy(item),
                "ancestryRole": "dependency",
            }
            for item in environment["files"]
        ],
        key=lambda item: item["artifactId"],
    )


def _contract(binding):
    contract = binding["renderContract"]
    _require(
        type(contract["frameCount"]) is int
        and contract["frameCount"] > 0
        and 0
        < Fraction(contract["frameRate"]["num"], contract["frameRate"]["den"])
        <= 240,
        "HyperFrames requires a positive frame count and supported rational frame rate",
    )
    return contract


def _work_root(workspace, project):
    raw = Path(workspace.raw_dir).resolve()
    directory = (raw / "edit/tmp").resolve()
    _require(
        directory.is_relative_to(raw) and not directory.is_relative_to(project),
        "Temporary outputs must remain outside source project inside raw/edit/tmp",
    )
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _checked_job_path(directory, work):
    directory, work = Path(directory).resolve(), Path(work).resolve()
    _require(
        directory != work and directory.is_relative_to(work),
        "Diagnostic evidence must stay inside raw/edit/tmp",
    )
    _require(
        all(path.resolve().is_relative_to(work) for path in directory.rglob("*")),
        "Diagnostic temporary tree escaped raw/edit/tmp",
    )
    return directory


@contextmanager
def _job_directory(work, prefix, *, evidence_dir=None):
    if evidence_dir is None:
        directory = Path(tempfile.mkdtemp(prefix=prefix, dir=work))
    else:
        directory = _checked_job_path(evidence_dir, work)
        directory.mkdir(parents=True, exist_ok=False)
    directory = _checked_job_path(directory, work)
    details = {}
    try:
        yield directory, details
    except Exception as error:
        _checked_job_path(directory, work)
        report = {
            "errorType": type(error).__name__,
            "error": str(error),
            "details": details,
        }
        (directory / "failure.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        error.add_note(f"HyperFrames failure evidence retained at {directory}")
        raise
    else:
        if evidence_dir is None:
            shutil.rmtree(_checked_job_path(directory, work))


def _run(command):
    done = subprocess.run(command, capture_output=True, check=False)
    _require(
        done.returncode == 0 and not done.stderr.strip(),
        "Media verification failed: " + done.stderr.decode(errors="replace")[:1000],
    )
    return done.stdout


def _pipe_pngs(command, frames, directory):
    """Stream compressed PNGs without retaining full decoded RGBA in Python memory."""
    errors = []
    with tempfile.TemporaryFile(dir=directory) as diagnostic:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=diagnostic
        )

        def feed():
            try:
                for path in frames:
                    with Path(path).open("rb") as source:
                        shutil.copyfileobj(source, process.stdin, 1024 * 1024)
            except (OSError, ValueError) as error:
                errors.append(error)
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass

        writer = threading.Thread(target=feed, daemon=True)
        writer.start()
        output = process.stdout.read()
        process.stdout.close()
        writer.join()
        result = process.wait()
        diagnostic.seek(0)
        detail = diagnostic.read().decode(errors="replace")
    _require(
        result == 0 and not detail.strip() and not errors,
        "PNG pipe/encoding failed: " + detail[:1000] + str(errors[:1]),
    )
    return output


def _parse_frame_hashes(payload):
    hashes = []
    for line in payload.decode("ascii").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(",")]
        _require(
            len(parts) == 6 and re.fullmatch(r"[0-9a-f]{64}", parts[-1]),
            "Invalid decoded RGBA frame-hash output",
        )
        hashes.append(parts[-1])
    _require(hashes, "No decoded RGBA frame hashes")
    return hashes


def _png_hashes(ffmpeg, paths, directory):
    command = [
        str(ffmpeg),
        "-v",
        "error",
        "-xerror",
        "-f",
        "image2pipe",
        "-c:v",
        "png",
        "-i",
        "-",
        "-map",
        "0:v:0",
        "-an",
        "-pix_fmt",
        "rgba",
        "-fps_mode",
        "passthrough",
        "-f",
        "framehash",
        "-hash",
        "sha256",
        "-",
    ]
    hashes = _parse_frame_hashes(_pipe_pngs(command, paths, directory))
    _require(len(hashes) == len(paths), "PNG decode changed the frame count")
    return hashes


def _encoded_verification(output, environment, contract):
    tools = environment["executables"]
    metadata = json.loads(
        _run(
            [
                tools["ffprobe"],
                "-v",
                "error",
                "-count_frames",
                "-show_streams",
                "-of",
                "json",
                str(output),
            ]
        )
    )
    streams = metadata["streams"]
    _require(
        len(streams) == 1 and streams[0].get("codec_type") == "video",
        "Encoded HyperFrames output must be silent with one video stream",
    )
    stream = streams[0]
    rate = Fraction(stream["avg_frame_rate"])
    result = {
        "silent": True,
        "width": stream["width"],
        "height": stream["height"],
        "frameRate": {"num": rate.numerator, "den": rate.denominator},
        "frameCount": int(stream["nb_read_frames"]),
        "codec": stream["codec_name"],
        "pixelFormat": stream["pix_fmt"],
    }
    _require(
        all(
            result[key] == contract[key]
            for key in ("width", "height", "frameRate", "frameCount")
        )
        and result["codec"] == "ffv1"
        and result["pixelFormat"] == "bgra",
        "Encoded FFV1/BGRA dimensions, frame clock or count changed",
    )
    hashes = _parse_frame_hashes(
        _run(
            [
                tools["ffmpeg"],
                "-v",
                "error",
                "-xerror",
                "-i",
                str(output),
                "-map",
                "0:v:0",
                "-an",
                "-pix_fmt",
                "rgba",
                "-fps_mode",
                "passthrough",
                "-f",
                "framehash",
                "-hash",
                "sha256",
                "-",
            ]
        )
    )
    _require(
        len(hashes) == contract["frameCount"], "Encoded decoded frame count changed"
    )
    result["frameHashes"] = hashes
    return result


def _png_dimensions(path, contract):
    with Path(path).open("rb") as stream:
        header = stream.read(24)
    _require(
        len(header) == 24
        and header[:8] == b"\x89PNG\r\n\x1a\n"
        and header[12:16] == b"IHDR",
        "PNG frame header is invalid",
    )
    _require(
        struct.unpack(">II", header[16:24]) == (contract["width"], contract["height"]),
        "PNG frame dimensions disagree with the render contract",
    )


def _require_snapshot_ready(result):
    diagnostics = result.stdout + result.stderr
    incomplete = (
        "Runtime did not become render-ready",
        "Fonts FAILED:",
        "active <video> frame(s) could not be extracted",
        "video frame injection failed",
        "No player API",
    )
    _require(
        not any(marker in diagnostics for marker in incomplete),
        "HyperFrames snapshot media/readiness verification failed: "
        + diagnostics[-1000:],
    )


def _snapshots(adapter, project, frames, destination, root, contract):
    rate = Fraction(contract["frameRate"]["num"], contract["frameRate"]["den"])
    times = [
        format(float(Fraction(frame, 1) / rate), ".12f").rstrip("0").rstrip(".") or "0"
        for frame in frames
    ]
    result = adapter.execute(
        "snapshot",
        project,
        "--at",
        ",".join(times),
        "--no-end",
        "--no-browser-gpu",
        "--describe",
        "false",
        "--output",
        str(destination),
        root=root,
    )
    _require(
        result.exit_code == 0,
        "HyperFrames seek capture failed: " + (result.stderr or result.stdout),
    )
    _require_snapshot_ready(result)
    found = {}
    for path in destination.rglob("*.png"):
        _png_dimensions(path, contract)
        match = re.search(r"-at-([0-9]+(?:\.[0-9]+)?)s\.png$", path.name)
        _require(match, f"Unexpected seek snapshot filename: {path.name}")
        time = float(match.group(1))
        # Snapshot filenames may round the exact requested time to milliseconds.
        candidates = [
            frame
            for frame in frames
            if abs(float(Fraction(frame, 1) / rate) - time) <= 0.00051
        ]
        _require(
            len(candidates) == 1 and candidates[0] not in found,
            "Ambiguous/duplicate seek snapshot",
        )
        found[candidates[0]] = path
    _require(set(found) == set(frames), "Missing exact seek captures")
    return found


def _capture_environment(root, contract):
    tools = _tool_environment(root)
    tools.setdefault("renderMode", {}).update(
        rasterBackend="hyperframes-native-snapshot-png-sequence",
        snapshotChunkSize=SNAPSHOT_CHUNK_SIZE,
    )
    tools.setdefault("renderMode", {})["snapshotClockCompatibility"] = {
        "policy": "export-render-seek-config-v1",
        "property": "__HF_EXPORT_RENDER_SEEK_CONFIG",
        "qualifiedHyperframesVersion": "0.7.109",
        "bootstrapDeduplication": "configuration-key-parts",
        "initializeMissingConfiguration": True,
        "frameRate": deepcopy(contract["frameRate"]),
    }
    tools["renderMode"]["snapshotRepaintCompatibility"] = {
        "policy": "seek-completion-top-roots-display-reset-v1",
        "property": "__hfWaitForSeekCompletion",
        "qualifiedHyperframesVersion": "0.7.109",
        "scope": "capture-clone-only",
        "boundary": "after-successful-native-seek-completion",
        "roots": "top-level-[data-composition-id]",
        "eligibility": "no-native-animation-no-css-animation-or-transition",
        "styleRestoration": "exact-style-attribute-null-preserved",
        "runtimeHookIdentity": "wrapped-native-function-in-isolated-capture-page",
        "limitation": "after-seek-boundary-not-universal-post-lut-callback",
    }
    tools["hash"] = document_hash_excluding(tools, "hash")
    return tools


def _copy_capture_inputs(binding, destination):
    project = Path(binding["project"]).resolve()
    registered = {
        Path(item["fingerprint"]["locator"]).resolve(): item["fingerprint"]
        for item in binding["inputs"]
        if Path(item["fingerprint"]["locator"]).resolve().is_relative_to(project)
    }
    actual = {path.resolve() for path in project.rglob("*") if path.is_file()}
    _require(set(registered) == actual, "Capture source closure changed")
    # Copies belong to this observation, not the caller's longer-lived source guard.
    # Verify them before injecting clock metadata and before temporary cleanup.
    with fingerprint_stage(verify_on_exit=True):
        for source, fingerprint in sorted(registered.items()):
            target = destination / source.relative_to(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied = file_fingerprint(target)
            _require(
                all(copied[key] == fingerprint[key] for key in ("sha256", "sizeBytes")),
                "Capture copy does not match a registered frozen input",
            )


def _capture_project(binding, directory, work):
    """Pin snapshot clock/repaint behavior in isolated copies of frozen sources."""
    destination = _checked_job_path(directory / "capture-project", work)
    destination.mkdir(exist_ok=False)
    _copy_capture_inputs(binding, destination)
    index = destination / "index.html"
    source = index.read_text(encoding="utf-8")
    head = re.search(r"<head(?:\s[^>]*)?>", source, re.IGNORECASE)
    _require(head is not None, "Capture source requires an explicit HTML head")
    rate = binding["renderContract"]["frameRate"]
    # HyperFrames 0.7.109 snapshot has no --fps option or render configuration.
    # Seed missing clock metadata and intercept any later native assignment.
    # Construct the key in parts because its runtime stripper removes inline
    # scripts containing the complete bootstrap marker before serving HTML.
    script = """<script data-avo-capture-clock="export-render-seek-config-v1">
(() => {
  const key = ["__HF_EXPORT_RENDER", "_SEEK_CONFIG"].join("");
  const pin = value => {
    if (!value || typeof value !== "object") return value;
    const config = {...value, fps: FPS_NUM / FPS_DEN, fpsSource: "render-options"};
    delete config.fallbackReason;
    delete config.fpsFallbackReason;
    return config;
  };
  let current = pin(window[key] ?? {});
  Object.defineProperty(window, key, {
    configurable: true, enumerable: true,
    get() { return current; },
    set(value) { current = pin(value); }
  });
  const waitKey = ["__hfWaitFor", "SeekCompletion"].join("");
  const wrapped = new WeakMap();
  const wrappers = new WeakSet();
  const unanimated = root => {
    if (typeof root.getAnimations !== "function" ||
        typeof window.getComputedStyle !== "function" ||
        root.getAnimations({subtree: true}).length !== 0) return false;
    return [root, ...root.querySelectorAll("*")].every(element => {
      const style = window.getComputedStyle(element);
      return style.animationName.split(",").every(name => name.trim() === "none") &&
        style.transitionDuration.split(",").every(time => Number.parseFloat(time) === 0);
    });
  };
  const repaint = () => {
    const roots = [...document.querySelectorAll("[data-composition-id]")]
      .filter(root => !root.parentElement?.closest("[data-composition-id]"))
      .filter(unanimated);
    const styles = roots.map(root => root.getAttribute("style"));
    try {
      roots.forEach(root => root.style.setProperty("display", "none", "important"));
      roots.forEach(root => { void root.offsetHeight; });
    } finally {
      roots.forEach((root, index) => {
        if (styles[index] === null) root.removeAttribute("style");
        else root.setAttribute("style", styles[index]);
      });
      roots.forEach(root => { void root.offsetHeight; });
    }
  };
  const wrap = native => {
    if (typeof native !== "function" || wrappers.has(native)) return native;
    if (!wrapped.has(native)) {
      const wrapper = async function(...args) {
        const result = await Reflect.apply(native, this, args);
        repaint();
        return result;
      };
      wrapped.set(native, wrapper);
      wrappers.add(wrapper);
    }
    return wrapped.get(native);
  };
  let wait = wrap(window[waitKey]);
  Object.defineProperty(window, waitKey, {
    configurable: true, enumerable: true,
    get() { return wait; },
    set(value) { wait = wrap(value); }
  });
})();
</script>""".replace("FPS_NUM", str(rate["num"])).replace("FPS_DEN", str(rate["den"]))
    index.write_text(
        source[: head.end()] + script + source[head.end() :], encoding="utf-8"
    )
    return destination


def observe(adapter, workspace, binding, *, output=None, root=None, evidence_dir=None):
    """Observe real tool files, repeat/reverse seeks and optional actual encoded pixels."""
    root = Path(root or repo_root()).resolve()
    verify_binding(workspace, binding)
    contract = _contract(binding)
    project = Path(binding["project"]).resolve()
    tools = _capture_environment(root, contract)
    work = _work_root(workspace, project)
    count = contract["frameCount"]
    frames = sorted({0, count * 3 // 10, count // 2, count * 91 // 100, count - 1})
    with _job_directory(work, "hyperframes-observe-", evidence_dir=evidence_dir) as (
        directory,
        details,
    ):
        capture_project = _capture_project(binding, directory, work)
        details["captureProject"] = str(capture_project)
        forward = _snapshots(
            adapter, capture_project, frames, directory / "forward", root, contract
        )
        reverse = _snapshots(
            adapter,
            capture_project,
            list(reversed(frames)),
            directory / "reverse",
            root,
            contract,
        )
        hashes = _png_hashes(
            tools["executables"]["ffmpeg"], [forward[i] for i in frames], directory
        )
        repeated = _png_hashes(
            tools["executables"]["ffmpeg"], [reverse[i] for i in frames], directory
        )
        details.update(frames=frames, forwardRgba=hashes, reverseRgba=repeated)
        _require(
            hashes == repeated, "Repeated/reversed seek captures changed decoded RGBA"
        )
        evidence = {
            "frames": frames,
            "rgbaSha256": {str(i): digest for i, digest in zip(frames, hashes)},
        }
        encoded = (
            _encoded_verification(Path(output), tools, contract)
            if output is not None
            else None
        )
        verify_binding(workspace, binding)
        _require(
            _capture_environment(root, contract) == tools,
            "Tool environment changed during observation",
        )
    result = {
        "toolEnvironment": tools,
        "toolInputs": _tool_inputs(tools),
        "captureEvidence": evidence,
        "encodedVerification": encoded,
    }

    if evidence_dir is not None:
        (directory / "observation.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
    return result


def _snapshot_sequence(adapter, workspace, binding, output, root):
    """Use the same native raster backend for production and independent seeks."""
    from .hyperframes import _timeline_output

    project = Path(binding["project"]).resolve()
    adapter.check_timeline_instance(
        project=project,
        instance={**binding, "reducedMotion": False},
        component_contract=binding["componentContract"],
        root=root,
        output_format="png-sequence",
    )
    contract = _contract(binding)
    work = _work_root(workspace, project)
    output.mkdir(parents=True, exist_ok=False)
    capture_project = _capture_project(binding, output.parent, work)
    for first in range(0, contract["frameCount"], SNAPSHOT_CHUNK_SIZE):
        indices = list(
            range(first, min(first + SNAPSHOT_CHUNK_SIZE, contract["frameCount"]))
        )
        captured = _snapshots(
            adapter,
            capture_project,
            indices,
            output.parent / f"chunk-{first:06d}",
            root,
            contract,
        )
        for index in indices:
            shutil.copyfile(captured[index], output / f"frame_{index:06d}.png")
    return {"status": "pass", "output": _timeline_output(output, "png-sequence")}


def _rendered_frames(rendered, directory, contract):
    value = rendered.get("output", {})
    _require(
        rendered.get("status") == "pass"
        and Path(value.get("path", "")).resolve() == directory.resolve(),
        "Renderer did not return the requested PNG sequence",
    )
    frames = []
    for expected in value.get("frames", []):
        path = Path(expected["locator"]).resolve()
        _require(
            path.is_relative_to(directory.resolve()) and path.suffix.lower() == ".png",
            "Rendered frame escaped its sequence directory",
        )
        _require(file_fingerprint(path) == expected, "Rendered PNG fingerprint changed")
        _png_dimensions(path, contract)
        frames.append(path)

    def number(path):
        match = re.search(r"(\d+)$", path.stem)
        _require(match, "Rendered PNG requires a numeric frame filename")
        return int(match.group(1))

    frames.sort(key=number)
    numbers = [number(path) for path in frames]
    _require(
        len(frames) == contract["frameCount"]
        and len(set(frames)) == len(frames)
        and numbers == list(range(numbers[0], numbers[0] + len(frames)))
        and numbers[0] in {0, 1}
        and set(directory.rglob("*.png")) == set(frames),
        "Rendered sequence frame count/order/closure changed",
    )
    return frames


def _encode_frames(frames, output, environment, contract, directory):
    rate = contract["frameRate"]
    command = [
        environment["executables"]["ffmpeg"],
        "-v",
        "error",
        "-xerror",
        "-n",
        "-f",
        "image2pipe",
        "-framerate",
        f"{rate['num']}/{rate['den']}",
        "-c:v",
        "png",
        "-i",
        "-",
        "-map",
        "0:v:0",
        "-an",
        "-c:v",
        "ffv1",
        "-level",
        "3",
        "-pix_fmt",
        "bgra",
        "-fps_mode",
        "passthrough",
        "-frames:v",
        str(contract["frameCount"]),
        "-f",
        "matroska",
        str(output),
    ]
    _pipe_pngs(command, frames, directory)


def _record_frame_comparison(details, hashes, paths, evidence):
    mismatches = [
        i for i in evidence["frames"] if hashes[i] != evidence["rgbaSha256"][str(i)]
    ]
    details["renderedFrameHashes"] = {
        "actualRgba": hashes,
        "expectedSeekRgba": evidence["rgbaSha256"],
        "mismatchFrameIndices": mismatches,
        "renderedFramePaths": [str(path) for path in paths],
    }
    return not mismatches


def materialize(adapter, workspace, instance_id, *, output, root=None):
    """Freeze current inputs, render originals only, prove pixel equality, then admit."""
    root = Path(root or repo_root()).resolve()
    binding = resolve_binding(workspace, instance_id)
    contract = _contract(binding)
    project = Path(binding["project"]).resolve()
    raw = Path(workspace.raw_dir).resolve()
    destination = Path(output).resolve()
    derived = (raw / "edit/derived").resolve()
    _require(
        derived.is_relative_to(raw)
        and destination.is_relative_to(derived)
        and not destination.is_relative_to(project)
        and destination.suffix.lower() == ".mkv",
        "Output must be a new MKV outside source project inside raw/edit/derived",
    )
    lock_path = destination.with_suffix(".input-lock.json")
    identity = (
        "hyperframes-" + hashlib.sha256(str(destination).encode()).hexdigest()[:24]
    )
    service = GeneratedAssetService(workspace)
    _require(
        not destination.exists()
        and not lock_path.exists()
        and not service.path(identity).exists(),
        "Refusing existing output, input lock or generated receipt",
    )
    work = _work_root(workspace, project)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _job_directory(work, "hyperframes-materialize-") as (directory, details):
        before = observe(
            adapter, workspace, binding, root=root, evidence_dir=directory / "before"
        )
        details["before"] = before
        lock = {
            "instanceId": instance_id,
            "binding": deepcopy(binding),
            "environment": before["toolEnvironment"],
        }
        lock["inputLockHash"] = document_hash_excluding(lock, "inputLockHash")
        write_immutable_json(lock_path, lock)
        lock_ref = {
            "path": str(lock_path),
            "sha256": file_fingerprint(lock_path)["sha256"],
        }
        rendered = _snapshot_sequence(
            adapter, workspace, binding, directory / "frames", root
        )
        verify_binding(workspace, binding)
        frames = _rendered_frames(rendered, directory / "frames", contract)
        hashes = _png_hashes(
            before["toolEnvironment"]["executables"]["ffmpeg"], frames, directory
        )
        _require(
            _record_frame_comparison(
                details, hashes, frames, before["captureEvidence"]
            ),
            "Rendered PNG frames disagree with independent seek captures",
        )
        _encode_frames(
            frames, destination, before["toolEnvironment"], contract, directory
        )
        after = observe(
            adapter,
            workspace,
            binding,
            output=destination,
            root=root,
            evidence_dir=directory / "after",
        )
        details["after"] = after
        _require(
            before["toolEnvironment"] == after["toolEnvironment"]
            and before["captureEvidence"] == after["captureEvidence"],
            "Tool environment or seek captures changed during rendering",
        )
        _require(
            hashes == after["encodedVerification"]["frameHashes"],
            "Encoded frames changed from rendered PNG RGBA",
        )
        verify_binding(workspace, binding)
        inputs = [
            *deepcopy(binding["inputs"]),
            {
                "artifactId": "hyperframes-input-lock:" + instance_id,
                "fingerprint": file_fingerprint(lock_path),
                "ancestryRole": "dependency",
            },
            *after["toolInputs"],
        ]
        record = {
            "assetId": identity,
            "role": "authored-graphic",
            "generator": {
                "adapterId": "hyperframes",
                "version": after["toolEnvironment"]["version"],
                "executableSha256": after["toolEnvironment"]["hash"],
            },
            "parameters": {
                "hyperframes": {
                    "instanceId": instance_id,
                    "instanceHash": binding["instanceHash"],
                    "inputLockRef": lock_ref,
                    "canonicalInputLock": binding["canonicalInputLock"],
                    "renderContract": contract,
                    "seekEvidence": after["captureEvidence"],
                    "outputVerification": after["encodedVerification"],
                }
            },
            "inputs": sorted(inputs, key=lambda item: item["artifactId"]),
            "sourceFree": False,
            "environment": {
                "platform": sys.platform,
                "dependencies": {"toolEnvironment": after["toolEnvironment"]["hash"]},
            },
            "output": file_fingerprint(destination),
            "reproducibility": "verified",
            "approvalReference": None,
        }
        registered = service.register(record, hyperframes_environment=after)
        admitted = service.admit(registered["assetId"], hyperframes_environment=after)
        return {
            "status": "pass",
            "instanceId": instance_id,
            "assetId": admitted["assetId"],
            "record": admitted,
            "generatedAssetRef": {
                "path": str(service.path(identity)),
                "sha256": file_fingerprint(service.path(identity))["sha256"],
            },
            "inputLockRef": lock_ref,
            "output": admitted["output"],
            "binding": binding,
            "environment": after,
        }

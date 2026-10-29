"""Managed, optional browser runtime for deterministic local drawings."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import io
import json
import mimetypes
import os
import platform
import shutil
import subprocess
import threading
import urllib.request
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from avo import motion_runtime
from avo.adapters.base import JobRequest, JobResult
from avo.motion import (
    MotionError,
    load_composition,
    local_composition_path,
    resolve_motion_selection,
)
from avo.templates.code_drawn import (
    BRUSH_LICENSE_SHA256,
    BRUSH_SHA256,
    BRUSH_VERSION,
    brush_cache_paths,
)
from avo.timeline.contracts import content_hash, file_fingerprint

PLAYWRIGHT_VERSION = motion_runtime.PLAYWRIGHT_VERSION
BRUSH_BASE_URL = f"https://cdn.jsdelivr.net/npm/p5.brush@{BRUSH_VERSION}"


def brush_cache_dir() -> Path:
    return brush_cache_paths()[0].parent


def brush_files() -> tuple[Path, Path]:
    return motion_runtime.brush_files(
        directory=brush_cache_dir(), hashes=(BRUSH_SHA256, BRUSH_LICENSE_SHA256)
    )


_runtime_repair = motion_runtime.runtime_repair
_driver_paths = motion_runtime.driver_paths
browser_identity = motion_runtime.browser_identity
managed_browser_path = motion_runtime.managed_browser_path


def runtime_readiness(*, brush: bool = False) -> dict[str, Any]:
    return motion_runtime.runtime_readiness(
        brush=brush, paths=_driver_paths, brush_check=brush_files
    )


def motion_result(
    operation: str,
    *,
    artifacts: list | None = None,
    checks: list | None = None,
    readiness: dict | None = None,
) -> dict[str, Any]:
    return {
        "operation": operation,
        "status": "ok",
        "selection": resolve_motion_selection(invocation={"engine": "code-drawn"}),
        "savedPreferences": {},
        "runSelection": None,
        "recordedAnimation": None,
        "readiness": readiness
        or {
            "ready": True,
            "state": "available",
            "checks": [],
            "blockers": [],
            "nextActions": [],
        },
        "artifacts": artifacts or [],
        "checks": checks or [],
        "errors": [],
    }


def _install_brush() -> None:
    import hashlib
    import tempfile

    directory = brush_cache_dir()
    staged = []
    try:
        directory.mkdir(parents=True, exist_ok=True)
        pending = []
        for remote, name, digest in (
            ("dist/brush.js", "brush.js", BRUSH_SHA256),
            ("LICENSE.md", "LICENSE.md", BRUSH_LICENSE_SHA256),
        ):
            with urllib.request.urlopen(
                f"{BRUSH_BASE_URL}/{remote}", timeout=60
            ) as response:
                data = response.read(2 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != digest:
                raise MotionError(
                    "CODE_DRAWN_ASSET_NOT_READY", f"Brush integrity mismatch: {name}"
                )
            pending.append((directory / name, data))
        for target, data in pending:
            descriptor, name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".partial", dir=directory
            )
            temporary = Path(name)
            staged.append((temporary, target))
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
        for temporary, target in staged:
            temporary.replace(target)
    except MotionError:
        raise
    except (OSError, ValueError) as error:
        raise MotionError(
            "CODE_DRAWN_ASSET_NOT_READY",
            "Cannot provision the local brush script and license.",
            remediation="Repair network/cache access, then retry runtime-install --brush.",
        ) from error
    finally:
        for temporary, _target in staged:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _installation_failure(stderr: str | None) -> str:
    diagnostic = (stderr or "")[-4000:].strip()
    if any(
        marker in diagnostic.casefold()
        for marker in ("://", "authorization", "token", "secret", "password")
    ):
        diagnostic = ""
    message = "Managed Chromium installation failed."
    return message + (" " + diagnostic if diagnostic else "")


def install_runtime(*, brush: bool = False) -> dict[str, Any]:
    import subprocess

    try:
        installed = importlib.metadata.version("playwright")
        if installed != PLAYWRIGHT_VERSION:
            raise ImportError(
                f"Expected Playwright {PLAYWRIGHT_VERSION}, found {installed}."
            )
        from playwright._impl._driver import get_driver_env

        node, cli = _driver_paths()
        if not node.is_file() or not cli.is_file():
            raise FileNotFoundError("Missing bundled Playwright driver files.")
    except (ImportError, importlib.metadata.PackageNotFoundError, OSError) as error:
        raise MotionError(
            "CODE_DRAWN_RUNTIME_MISSING", str(error), remediation=_runtime_repair()
        ) from error

    repair = "Repair browser download/system dependencies, then retry runtime-install."
    try:
        result = subprocess.run(
            [str(node), str(cli), "install", "--no-shell", "chromium"],
            env=get_driver_env(),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MotionError(
            "CODE_DRAWN_RUNTIME_MISSING",
            "Managed Chromium installation failed: bundled driver could not complete.",
            remediation=repair,
        ) from error
    if result.returncode:
        raise MotionError(
            "CODE_DRAWN_RUNTIME_MISSING",
            _installation_failure(result.stderr),
            remediation=repair,
        )
    if brush:
        _install_brush()
    readiness = runtime_readiness(brush=brush)
    if not readiness["ready"]:
        raise MotionError(
            "CODE_DRAWN_RUNTIME_MISSING", "; ".join(readiness["blockers"])
        )
    return motion_result("runtime-install", readiness=readiness)


class _JobParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise MotionError("CODE_DRAWN_INPUT_INVALID", message)


def _job_parser() -> argparse.ArgumentParser:
    parser = _JobParser(description="Run a deterministic code-drawn operation.")
    operations = parser.add_subparsers(dest="operation", required=True)
    for operation in ("check", "snapshot", "render"):
        command = operations.add_parser(operation)
        command.add_argument("--composition", type=Path, required=True)
        command.add_argument("--input-lock", type=Path, required=operation == "render")
        if operation == "check":
            command.add_argument("--output-lock", type=Path)
        else:
            command.add_argument("--output", type=Path, required=True)
        if operation == "snapshot":
            command.add_argument("--frame", type=int, required=True)
    return parser


def _job_error_code(error: MotionError) -> int:
    if error.code == "CODE_DRAWN_CANCELLED":
        return 130
    if error.code in {
        "CODE_DRAWN_RENDER_FAILED",
        "CODE_DRAWN_OUTPUT_INVALID",
        "CODE_DRAWN_SEEK_MISMATCH",
    }:
        return 1
    return 2


class CodeDrawnAdapter:
    routing_id = "code-drawn"

    def __init__(
        self,
        *,
        timeout_ms: int = 30000,
        cancel_event=None,
        ffmpeg_path: Path | None = None,
    ):
        if type(timeout_ms) is not int or timeout_ms <= 0:
            raise MotionError(
                "CODE_DRAWN_INPUT_INVALID", "timeout_ms must be a positive integer."
            )
        self.timeout_ms = timeout_ms
        self.cancel_event = cancel_event
        self.ffmpeg_path = Path(ffmpeg_path).resolve() if ffmpeg_path else None

    def run(self, request: JobRequest) -> JobResult:
        try:
            args = _job_parser().parse_args(request.argv)
            if args.operation == "check":
                result = self.check(
                    args.composition,
                    input_lock=args.input_lock,
                    output_lock=args.output_lock,
                )
            elif args.operation == "snapshot":
                result = self.snapshot(
                    args.composition,
                    frame=args.frame,
                    output=args.output,
                    input_lock=args.input_lock,
                )
            else:
                result = self.render(
                    args.composition, input_lock=args.input_lock, output=args.output
                )
        except MotionError as error:
            return JobResult(_job_error_code(error), stderr=json.dumps(error.to_dict()))
        return JobResult(
            0,
            stdout=json.dumps(result),
            artifact_paths=[Path(item["path"]) for item in result["artifacts"]],
        )

    def _cancel(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise MotionError(
                "CODE_DRAWN_CANCELLED",
                "Drawing attempt cancelled; no successful output was published.",
            )

    @staticmethod
    def _frame(manifest: dict, frame: int) -> float:
        contract = manifest["renderContract"]
        if type(frame) is not int or not 0 <= frame < contract["frameCount"]:
            raise MotionError(
                "CODE_DRAWN_INPUT_INVALID",
                "Frame must be an integer within the composition, excluding its endpoint.",
            )
        rate = contract["frameRate"]
        return frame * rate["den"] / rate["num"]

    @staticmethod
    def _new_output(output: Path, composition: Path) -> Path:
        output = Path(output)
        if not output.is_absolute():
            raise MotionError(
                "CODE_DRAWN_INPUT_INVALID", f"Output must be absolute: {output}"
            )
        output = output.resolve()
        if output.exists() or output == composition.resolve():
            raise MotionError(
                "CODE_DRAWN_INPUT_INVALID",
                f"Output already exists or aliases an input: {output}",
            )
        return output

    @staticmethod
    def _route_inputs(manifest: dict) -> None:
        if manifest["drawingRoute"] != "brush":
            return
        dependencies = [
            item for item in manifest["dependencies"] if item["name"] == "p5.brush"
        ]
        if len(dependencies) != 1:
            raise MotionError(
                "CODE_DRAWN_ASSET_NOT_READY",
                "The brush route requires the pinned local standalone p5.brush dependency.",
            )
        dependency = dependencies[0]
        expected = (BRUSH_VERSION, "standalone", BRUSH_SHA256)
        actual = (dependency["version"], dependency["build"], dependency["sha256"])
        licenses = [
            item
            for item in manifest["assets"]
            if item["path"] == dependency["licenseRef"]
            and item["sha256"] == BRUSH_LICENSE_SHA256
        ]
        if actual != expected or len(licenses) != 1:
            raise MotionError(
                "CODE_DRAWN_ASSET_NOT_READY",
                "The declared brush build or local license differs from the supported pin.",
            )

    @staticmethod
    def _closure(composition: Path, manifest: dict) -> dict[str, bytes]:
        closure = {}
        for key in ("files", "assets", "dependencies"):
            for item in manifest[key]:
                target = local_composition_path(composition.parent, item["path"])
                data = target.read_bytes()
                if (
                    len(data) != item["sizeBytes"]
                    or hashlib.sha256(data).hexdigest() != item["sha256"]
                ):
                    raise MotionError(
                        "CODE_DRAWN_LOCK_STALE",
                        f"Input changed while staging: {target}",
                    )
                closure[item["path"]] = data
        return closure

    def _route(self, route, closure: dict, failures: list) -> None:
        parsed = urlsplit(route.request.url)
        name = unquote(parsed.path).removeprefix("/")
        try:
            local_composition_path(Path.cwd(), name)
            if (
                parsed.scheme != "http"
                or parsed.netloc != "avo.invalid"
                or parsed.query
                or name not in closure
            ):
                raise MotionError(
                    "CODE_DRAWN_INPUT_INVALID",
                    f"Undeclared/external drawing request: {route.request.url}",
                )
            route.fulfill(
                status=200,
                body=closure[name],
                content_type=mimetypes.guess_type(name)[0]
                or "application/octet-stream",
            )
        except MotionError as error:
            failures.append(str(error))
            route.abort("blockedbyclient")

    def _await(self, page, expression: str, argument=None):
        self._cancel()
        return page.evaluate(
            """async ({expression, argument, timeout}) => {
              return await Promise.race([
                Promise.resolve().then(() => (0,eval)(expression)(argument)),
                new Promise((_, reject) => setTimeout(() => reject(new Error('AVO awaited operation timed out')), timeout))
              ]);
            }""",
            {
                "expression": expression,
                "argument": argument,
                "timeout": self.timeout_ms,
            },
        )

    def _load_assets(self, page, manifest: dict) -> None:
        for asset in manifest["assets"]:
            if asset["kind"] == "font":
                operation = """async a => {
                  const face = new FontFace(a.family, 'url('+JSON.stringify('/'+a.path)+')', {style:a.style,weight:String(a.weight)});
                  await face.load(); document.fonts.add(face); await document.fonts.ready;
                  if(face.status !== 'loaded' || !document.fonts.check(String(a.weight)+' 16px '+JSON.stringify(a.family)))
                    throw new Error('Required font face failed '+a.path);
                }"""
            elif asset["kind"] in {"image", "svg"}:
                operation = """async a => {
                  const image = new Image(); image.src='/'+a.path; await image.decode();
                  if(!image.naturalWidth || (a.width && image.naturalWidth!==a.width) || (a.height && image.naturalHeight!==a.height))
                    throw new Error('Required image dimensions failed '+a.path);
                }"""
            else:
                continue
            try:
                self._await(page, operation, asset)
            except Exception as error:
                raise MotionError(
                    "CODE_DRAWN_ASSET_NOT_READY",
                    f"Cannot load required asset {asset['path']}: {error}",
                    field=asset["path"],
                ) from error

    @contextmanager
    def _session_raw(self, composition: Path, manifest: dict):
        self._cancel()
        self._route_inputs(manifest)
        readiness = runtime_readiness()
        if not readiness["ready"]:
            raise MotionError(
                "CODE_DRAWN_RUNTIME_MISSING", "; ".join(readiness["blockers"])
            )
        from playwright.sync_api import sync_playwright

        contract = manifest["renderContract"]
        failures: list[str] = []
        closure = self._closure(composition, manifest)
        with ExitStack() as stack:
            runtime = stack.enter_context(sync_playwright())
            browser = runtime.chromium.launch(
                channel="chromium", headless=True, timeout=self.timeout_ms
            )
            stack.callback(browser.close)
            context = browser.new_context(
                viewport={"width": contract["width"], "height": contract["height"]},
                device_scale_factor=1,
                locale="en-US",
                timezone_id="UTC",
                color_scheme="light",
                reduced_motion="reduce",
                service_workers="block",
            )
            stack.callback(context.close)
            context.route("**/*", lambda route: self._route(route, closure, failures))
            context.add_init_script("""
              window.__AVO_RENDER__ = true;
              HTMLMediaElement.prototype.play = function(){throw new Error('AVO drawing capture is silent');};
              window.WebSocket = class {constructor(){throw new Error('AVO network sockets are disabled');}};
              window.EventSource = window.WebSocket;
            """)
            page = context.new_page()
            page.set_default_timeout(self.timeout_ms)
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(
                "http://avo.invalid/" + manifest["entry"],
                wait_until="load",
                timeout=self.timeout_ms,
            )
            self._load_assets(page, manifest)
            self._await(
                page,
                """async () => {
              if(!(window.avoReady instanceof Promise) || typeof window.seek !== 'function')
                throw new Error('Required avoReady promise / seek function is missing');
              await window.avoReady; await document.fonts.ready;
            }""",
            )
            bounds = page.locator("#avo-stage").bounding_box(timeout=self.timeout_ms)
            expected = {
                "x": 0,
                "y": 0,
                "width": contract["width"],
                "height": contract["height"],
            }
            if bounds != expected or page.locator("#avo-stage").count() != 1:
                raise MotionError(
                    "CODE_DRAWN_INPUT_INVALID",
                    f"#avo-stage bounds {bounds} must equal {expected}.",
                )
            if page.locator("audio,video").count():
                raise MotionError(
                    "CODE_DRAWN_INPUT_INVALID",
                    "Drawing pages cannot own audio or video playback.",
                )
            graphics = page.evaluate("""() => {
              const c=document.createElement('canvas'), gl=c.getContext('webgl2');
              if(!gl) return {webgl2:false, renderer:'canvas-2d'};
              const ext=gl.getExtension('WEBGL_debug_renderer_info');
              const renderer=ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER);
              return {webgl2:true,renderer};
            }""")
            if manifest["drawingRoute"] == "brush" and not graphics["webgl2"]:
                raise MotionError(
                    "MOTION_CAPABILITY_UNSUPPORTED", "The brush route requires WebGL2."
                )
            environment = self._environment(browser.version, graphics["renderer"])
            self._failures(failures)
            yield page, failures, environment
            self._failures(failures)

    @contextmanager
    def _session(self, composition: Path, manifest: dict):
        try:
            with self._session_raw(composition, manifest) as session:
                yield session
        except MotionError:
            raise
        except Exception as error:
            self._cancel()
            raise MotionError(
                "CODE_DRAWN_RENDER_FAILED",
                f"Drawing runtime failed for {composition}: {error}",
            ) from error

    @staticmethod
    def _driver_fingerprint(node: Path, cli: Path) -> str:
        identities = {"node": file_fingerprint(node)["sha256"]}
        for source in sorted(cli.parent.rglob("*")):
            if source.is_file() and source.suffix in {".js", ".json"}:
                identities[source.relative_to(cli.parent).as_posix()] = (
                    file_fingerprint(source)["sha256"]
                )
        return content_hash(identities)

    def _environment(self, browser_version: str, graphics: str) -> dict:
        node, cli = _driver_paths()
        encoder = self.ffmpeg_path or Path(shutil.which("ffmpeg") or "")
        version = subprocess.run(
            [str(encoder), "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.splitlines()[0]
        browser_file = managed_browser_path()
        browser_hashes = {browser_file.name: file_fingerprint(browser_file)["sha256"]}
        library = browser_file.parent / "chrome.dll"
        if library.is_file():
            browser_hashes[library.name] = file_fingerprint(library)["sha256"]
        return {
            "platform": platform.system() + "-" + platform.machine(),
            "dependencies": {
                "python": platform.python_version(),
                "pillow": importlib.metadata.version("pillow"),
                "playwright": PLAYWRIGHT_VERSION,
                "ffmpeg": version,
                "chromiumBytes": content_hash(browser_hashes),
            },
            "browserVersion": browser_version,
            "browserRevision": browser_identity()["revision"],
            "graphics": graphics,
            "driverSha256": self._driver_fingerprint(node, cli),
            "encoderSha256": file_fingerprint(encoder)["sha256"],
            "locale": "en-US",
            "timezone": "UTC",
            "colorSpace": "srgb",
        }

    @staticmethod
    def _failures(failures: list) -> None:
        if failures:
            raise MotionError("CODE_DRAWN_INPUT_INVALID", "; ".join(failures))

    def _capture(self, page, manifest: dict, frame: int, failures: list) -> bytes:
        self._cancel()
        seconds = self._frame(manifest, frame)
        self._await(page, "async t => { await window.seek(t); }", seconds)
        self._failures(failures)
        data = page.locator("#avo-stage").screenshot(
            type="png",
            omit_background=True,
            animations="disabled",
            timeout=self.timeout_ms,
        )
        self._failures(failures)
        self._cancel()
        return data

    def capture_frames(self, composition: Path, frames: list[int]) -> list[bytes]:
        composition = Path(composition).resolve()
        manifest = load_composition(composition)
        for frame in frames:
            self._frame(manifest, frame)
        with self._session(composition, manifest) as (page, failures, _environment):
            result = [
                self._capture(page, manifest, frame, failures) for frame in frames
            ]
        if load_composition(composition) != manifest:
            raise MotionError(
                "CODE_DRAWN_LOCK_STALE", "Composition changed during capture."
            )
        return result

    @staticmethod
    def _pixels(png: bytes) -> bytes:
        from PIL import Image

        with Image.open(io.BytesIO(png)) as image:
            return image.convert("RGBA").tobytes()

    @staticmethod
    def _moments(count: int) -> list[int]:
        return [round(i * (count - 1) / 9) for i in range(10)]

    def _seek_evidence(self, composition: Path, manifest: dict) -> tuple[dict, dict]:
        moments = self._moments(manifest["renderContract"]["frameCount"])
        sequence = moments + moments + list(reversed(moments))
        with self._session(composition, manifest) as (page, failures, environment):
            samples = [
                hashlib.sha256(
                    self._pixels(self._capture(page, manifest, frame, failures))
                ).hexdigest()
                for frame in sequence
            ]
        with self._session(composition, manifest) as (
            page,
            failures,
            fresh_environment,
        ):
            fresh = [
                hashlib.sha256(
                    self._pixels(self._capture(page, manifest, frame, failures))
                ).hexdigest()
                for frame in moments
            ]
        if environment != fresh_environment:
            raise MotionError(
                "CODE_DRAWN_LOCK_STALE", "Runtime changed between independent sessions."
            )
        if any(
            samples[i] != samples[i + 10]
            or samples[i] != samples[29 - i]
            or samples[i] != fresh[i]
            for i in range(10)
        ):
            raise MotionError(
                "CODE_DRAWN_SEEK_MISMATCH",
                "Repeated, reversed or fresh-session RGBA frames disagree.",
            )
        return {
            "frames": moments,
            "rgbaSha256": fresh,
            "passes": ["repeat", "reverse", "fresh-session"],
            "environment": environment,
        }, environment

    def check(
        self,
        composition: Path,
        input_lock: Path | None = None,
        output_lock: Path | None = None,
    ) -> dict:
        from avo.motion import freeze_code_drawn_lock, verify_code_drawn_lock
        from avo.timeline.store import write_immutable_json

        composition = Path(composition).resolve()
        manifest = load_composition(composition)
        if output_lock:
            output_lock = self._new_output(output_lock, composition)
        original_lock = self._read_lock(input_lock) if input_lock else None
        if original_lock:
            verify_code_drawn_lock(composition, original_lock)
        evidence, environment = self._seek_evidence(composition, manifest)
        if original_lock:
            verify_code_drawn_lock(composition, original_lock, environment=environment)
        if load_composition(composition) != manifest:
            raise MotionError(
                "CODE_DRAWN_LOCK_STALE", "Composition changed during check."
            )
        artifacts = []
        if output_lock:
            if original_lock and original_lock["bindingMode"] == "canonical":
                raise MotionError(
                    "CODE_DRAWN_INPUT_INVALID",
                    "Check only creates standalone locks; canonical binding belongs to the pipeline.",
                )
            lock = freeze_code_drawn_lock(composition, environment=environment)
            write_immutable_json(output_lock, lock)
            artifacts.append(
                {"path": str(output_lock), **file_fingerprint(output_lock)}
            )
        return motion_result(
            "code-drawn-check",
            artifacts=artifacts,
            checks=[
                {"name": "independent-rgba-seek", "ready": True, "evidence": evidence}
            ],
        )

    @staticmethod
    def _read_lock(path: Path) -> dict:
        from avo.motion import validate_input_lock

        try:
            return validate_input_lock(
                json.loads(Path(path).read_text(encoding="utf-8"))
            )
        except (OSError, ValueError) as error:
            if isinstance(error, MotionError):
                raise
            raise MotionError(
                "CODE_DRAWN_INPUT_INVALID", f"Cannot read input lock {path}: {error}"
            ) from error

    def snapshot(
        self,
        composition: Path,
        frame: int,
        output: Path,
        input_lock: Path | None = None,
    ) -> dict:
        from avo.motion import verify_code_drawn_lock

        composition = Path(composition).resolve()
        manifest = load_composition(composition)
        self._frame(manifest, frame)
        output = self._new_output(output, composition)
        lock = self._read_lock(input_lock) if input_lock else None
        if lock:
            verify_code_drawn_lock(composition, lock)
        with self._session(composition, manifest) as (page, failures, environment):
            if lock:
                verify_code_drawn_lock(composition, lock, environment=environment)
            png = self._capture(page, manifest, frame, failures)
        if load_composition(composition) != manifest:
            raise MotionError(
                "CODE_DRAWN_LOCK_STALE", "Composition changed during snapshot."
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(png)
        return motion_result(
            "code-drawn-snapshot",
            artifacts=[{"path": str(output), **file_fingerprint(output)}],
            checks=[{"name": "integer-frame", "ready": True, "frame": frame}],
        )

    def _encoder_command(self, manifest: dict, output: Path) -> list[str]:
        contract = manifest["renderContract"]
        rate = contract["frameRate"]
        encoder = self.ffmpeg_path or Path(shutil.which("ffmpeg") or "")
        return [
            str(encoder),
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-framerate",
            f"{rate['num']}/{rate['den']}",
            "-i",
            "pipe:0",
            "-map",
            "0:v:0",
            "-an",
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-pix_fmt",
            "bgra",
            "-color_range",
            "pc",
            "-colorspace",
            "rgb",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "iec61966-2-1",
            "-frames:v",
            str(contract["frameCount"]),
            "-f",
            "matroska",
            str(output),
        ]

    @contextmanager
    def _process(
        self,
        command: list[str],
        *,
        seconds: float,
        stdin=None,
        stdout=None,
        stderr=None,
    ):
        process = subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr)
        watchdog = threading.Timer(seconds, process.kill)
        watchdog.start()
        try:
            yield process
        finally:
            watchdog.cancel()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)

    def _encode(
        self,
        composition: Path,
        manifest: dict,
        lock: dict,
        candidate: Path,
        *,
        workspace=None,
    ) -> list[str]:
        from avo.motion import verify_code_drawn_lock

        count = manifest["renderContract"]["frameCount"]
        hashes = []
        with candidate.with_suffix(".encoder.log").open("w+b") as log:
            with self._process(
                self._encoder_command(manifest, candidate),
                seconds=max(30, count * self.timeout_ms / 1000),
                stdin=subprocess.PIPE,
                stderr=log,
            ) as encoder:
                try:
                    with self._session(composition, manifest) as (
                        page,
                        failures,
                        environment,
                    ):
                        verify_code_drawn_lock(
                            composition,
                            lock,
                            environment=environment,
                            workspace=workspace,
                        )
                        for frame in range(count):
                            png = self._capture(page, manifest, frame, failures)
                            rgba = self._pixels(png)
                            if manifest["renderContract"][
                                "alphaMode"
                            ] == "opaque" and any(alpha != 255 for alpha in rgba[3::4]):
                                raise MotionError(
                                    "CODE_DRAWN_OUTPUT_INVALID",
                                    f"Opaque contract contains transparency at frame {frame}.",
                                )
                            hashes.append(hashlib.sha256(rgba).hexdigest())
                            encoder.stdin.write(png)
                    encoder.stdin.close()
                    result = encoder.wait(timeout=30)
                except (OSError, subprocess.TimeoutExpired) as error:
                    raise MotionError(
                        "CODE_DRAWN_RENDER_FAILED", f"PNG encoder failed: {error}"
                    ) from error
                if result:
                    log.seek(0)
                    raise MotionError(
                        "CODE_DRAWN_RENDER_FAILED",
                        "FFmpeg encode failed: "
                        + log.read(4096).decode("utf-8", errors="replace"),
                    )
        return hashes

    @staticmethod
    def _read_decoded_frame(stream, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = stream.read(size - len(data))
            if not chunk:
                break
            data.extend(chunk)
        return bytes(data)

    @staticmethod
    def _contrast_evidence(rgba: bytes, contract: dict) -> list[dict]:
        from PIL import Image

        source = Image.frombytes("RGBA", (contract["width"], contract["height"]), rgba)
        checks = []
        for color in ("#000000", "#ffffff"):
            background = Image.new("RGBA", source.size, color)
            composite = Image.alpha_composite(background, source).convert("RGB")
            checks.append(
                {
                    "background": color,
                    "rgbSha256": hashlib.sha256(composite.tobytes()).hexdigest(),
                }
            )
        return checks

    def _probe_output(self, candidate: Path, contract: dict) -> None:
        from fractions import Fraction

        rate = contract["frameRate"]
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-count_frames",
                "-show_streams",
                "-of",
                "json",
                str(candidate),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        streams = json.loads(probe.stdout)["streams"]
        if len(streams) != 1 or streams[0]["codec_type"] != "video":
            raise MotionError(
                "CODE_DRAWN_OUTPUT_INVALID",
                "Generated asset must contain exactly one silent video stream.",
            )
        video = streams[0]
        expected = (
            contract["width"],
            contract["height"],
            contract["frameCount"],
            "ffv1",
            "bgra",
        )
        actual = (
            video["width"],
            video["height"],
            int(video["nb_read_frames"]),
            video["codec_name"],
            video["pix_fmt"],
        )
        if actual != expected or Fraction(video["r_frame_rate"]) != Fraction(
            rate["num"], rate["den"]
        ):
            raise MotionError(
                "CODE_DRAWN_OUTPUT_INVALID",
                f"Encoded contract mismatch: {actual} expected {expected}.",
            )

    def _verify_output(
        self, candidate: Path, manifest: dict, hashes: list[str]
    ) -> dict:
        contract = manifest["renderContract"]
        rate = contract["frameRate"]
        self._probe_output(candidate, contract)
        encoder = self.ffmpeg_path or Path(shutil.which("ffmpeg") or "")
        command = [
            str(encoder),
            "-v",
            "error",
            "-i",
            str(candidate),
            "-map",
            "0:v:0",
            "-fps_mode",
            "passthrough",
            "-pix_fmt",
            "rgba",
            "-f",
            "rawvideo",
            "pipe:1",
        ]
        frame_size = contract["width"] * contract["height"] * 4
        composite_evidence = []
        with self._process(
            command,
            seconds=max(30, len(hashes)),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ) as decoder:
            for index, digest in enumerate(hashes):
                self._cancel()
                data = self._read_decoded_frame(decoder.stdout, frame_size)
                if (
                    len(data) != frame_size
                    or hashlib.sha256(data).hexdigest() != digest
                ):
                    raise MotionError(
                        "CODE_DRAWN_OUTPUT_INVALID",
                        f"Lossless RGBA/alpha round-trip mismatch at frame {index}.",
                    )
                if index in {0, len(hashes) // 2, len(hashes) - 1}:
                    composite_evidence.append(
                        {
                            "frame": index,
                            "checks": self._contrast_evidence(data, contract),
                        }
                    )
            if decoder.stdout.read(1) or decoder.wait(timeout=10):
                raise MotionError(
                    "CODE_DRAWN_OUTPUT_INVALID",
                    "Decoder failed or emitted extra frames.",
                )
        return {
            "width": contract["width"],
            "height": contract["height"],
            "frameRate": rate,
            "frameCount": len(hashes),
            "silent": True,
            "codec": "ffv1",
            "pixelFormat": "bgra",
            "alphaMode": contract["alphaMode"],
            "rgbaRoundTrip": "exact",
            "colorRange": "full",
            "captureColorSpace": "srgb",
            "compositeColorSpace": "sdr-bt709",
            "controlledCompositeChecks": composite_evidence,
        }

    def _receipt(
        self,
        composition: Path,
        manifest: dict,
        lock_path: Path,
        lock: dict,
        output: Path,
        evidence: dict,
        verification: dict,
    ) -> dict:
        from avo.timeline.contracts import document_hash_excluding, validate_document

        extension = {
            "instanceId": lock["instanceId"],
            "manifestRef": lock["manifestRef"],
            "sourceRevision": manifest["sourceRevision"],
            "inputsHash": lock["inputsHash"],
            "inputLockRef": {
                "path": str(lock_path),
                "sha256": file_fingerprint(lock_path)["sha256"],
            },
            "inputLockHash": lock["inputLockHash"],
            "renderContractHash": lock["renderContractHash"],
            "drawingRoute": manifest["drawingRoute"],
            "captureEvidence": evidence,
            "outputVerification": verification,
        }
        if lock["bindingMode"] == "canonical":
            extension["canonicalInputLock"] = lock["canonicalInputLock"]
        inputs = [
            *lock["inputs"],
            {
                "artifactId": "input-lock:" + lock["instanceId"],
                "fingerprint": file_fingerprint(lock_path),
                "ancestryRole": "dependency",
            },
        ]
        value = {
            "schemaVersion": "1.0.0",
            "assetId": "drawing-"
            + content_hash(
                {
                    "inputLockHash": lock["inputLockHash"],
                    "output": file_fingerprint(output),
                }
            )[:24],
            "role": "overlay"
            if manifest["renderContract"]["alphaMode"] == "straight"
            else "authored-graphic",
            "generator": lock["generator"],
            "parameters": {"codeDrawn": extension},
            "inputs": inputs,
            "sourceFree": not any(item.get("sourceRef") for item in manifest["assets"]),
            "environment": {
                key: lock["environment"][key] for key in ("platform", "dependencies")
            },
            "output": {**file_fingerprint(output), "mediaSignature": verification},
            "reproducibility": "verified",
            "approvalReference": None,
        }
        value["recordHash"] = document_hash_excluding(value, "recordHash")
        validate_document(value, "avo.generated-asset.schema.json")
        return value

    def render(
        self, composition: Path, input_lock: Path, output: Path, *, workspace=None
    ) -> dict:
        import tempfile

        from avo.motion import verify_code_drawn_lock
        from avo.timeline.store import write_immutable_json

        self._cancel()
        composition = Path(composition).resolve()
        input_lock = Path(input_lock).resolve()
        manifest = load_composition(composition)
        output = self._new_output(output, composition)
        receipt_path = self._new_output(
            output.with_suffix(".generated-asset.json"), composition
        )
        if output.suffix != ".mkv":
            raise MotionError(
                "CODE_DRAWN_INPUT_INVALID",
                "Generated output must use the .mkv contract.",
            )
        lock = self._read_lock(input_lock)
        verify_code_drawn_lock(composition, lock, workspace=workspace)
        evidence, environment = self._seek_evidence(composition, manifest)
        verify_code_drawn_lock(
            composition, lock, environment=environment, workspace=workspace
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".avo-drawing-", dir=output.parent
        ) as attempt:
            candidate = Path(attempt) / "candidate.mkv"
            hashes = self._encode(
                composition, manifest, lock, candidate, workspace=workspace
            )
            verification = self._verify_output(candidate, manifest, hashes)
            verify_code_drawn_lock(
                composition, lock, environment=environment, workspace=workspace
            )
            self._cancel()
            # Exclusive publication preserves a concurrent creator's destination.
            os.link(candidate, output)
            try:
                receipt = self._receipt(
                    composition,
                    manifest,
                    input_lock,
                    lock,
                    output,
                    evidence,
                    verification,
                )
                write_immutable_json(receipt_path, receipt)
            except Exception:
                output.unlink()
                raise
        return motion_result(
            "code-drawn-render",
            artifacts=[
                {"path": str(output), **file_fingerprint(output)},
                {"path": str(receipt_path), **file_fingerprint(receipt_path)},
            ],
            checks=[
                {"name": "decoded-rgba", "ready": True, "verification": verification},
                {"name": "independent-seek", "ready": True, "evidence": evidence},
            ],
        )

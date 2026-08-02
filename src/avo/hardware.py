"""AVO hardware capability probe (advisory only — never blocks).

Probes CPU / RAM / GPU(VRAM) / disk across OSes (nvidia-smi / wmic / powershell /
system_profiler / /proc), then emits a capability report plus a suggested model
tier map (faster-whisper size + local LLM/qwen size). The driving agent reads the
report and tells the user, in prose, what it selected and the better/worse
alternatives.

Everything degrades gracefully to "unknown"; a failed probe never raises.
Cross-platform: pathlib + subprocess, no hardcoded separators.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


GB = 1024 ** 3
MB = 1024 ** 2


def _run(cmd: list[str], timeout: float = 6.0) -> str:
    exe = shutil.which(cmd[0])
    if not exe:
        return ""
    try:
        out = subprocess.run(
            [exe, *cmd[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return out.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


# ---- CPU --------------------------------------------------------------------

def probe_cpu() -> dict[str, Any]:
    logical = os.cpu_count() or 0
    physical: int | None = None
    model = ""
    system = platform.system()

    try:
        if system == "Linux":
            text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"model name\s*:\s*(.+)", text)
            if m:
                model = m.group(1).strip()
            ids = set(re.findall(r"physical id\s*:\s*(\d+)", text))
            cores = set(re.findall(r"core id\s*:\s*(\d+)", text))
            if ids and cores:
                physical = len(ids) * len(cores)
        elif system == "Darwin":
            model = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
            pc = _run(["sysctl", "-n", "hw.physicalcpu"]).strip()
            physical = int(pc) if pc.isdigit() else None
        elif system == "Windows":
            out = _run(["wmic", "cpu", "get", "Name,NumberOfCores", "/format:list"])
            if not out:
                out = _run([
                    "powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Processor | "
                    "ForEach-Object { \"Name=$($_.Name)`nNumberOfCores=$($_.NumberOfCores)\" }",
                ])
            mm = re.search(r"Name=(.+)", out)
            if mm:
                model = mm.group(1).strip()
            cc = re.search(r"NumberOfCores=(\d+)", out)
            if cc:
                physical = int(cc.group(1))
    except (OSError, ValueError):
        pass

    if not model:
        model = platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "") or "unknown"

    return {"model": model, "logicalCores": logical, "physicalCores": physical}


# ---- RAM --------------------------------------------------------------------

def probe_ram_bytes() -> int:
    system = platform.system()
    try:
        import psutil  # type: ignore
        return int(psutil.virtual_memory().total)
    except Exception:
        pass
    try:
        if system in ("Linux",):
            page = os.sysconf("SC_PAGE_SIZE")
            pages = os.sysconf("SC_PHYS_PAGES")
            return int(page) * int(pages)
        if system == "Darwin":
            val = _run(["sysctl", "-n", "hw.memsize"]).strip()
            return int(val) if val.isdigit() else -1
        if system == "Windows":
            out = _run(["wmic", "computersystem", "get", "TotalPhysicalMemory", "/format:list"])
            if not out:
                out = _run([
                    "powershell", "-NoProfile", "-Command",
                    "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
                ])
            m = re.search(r"(\d{6,})", out)
            return int(m.group(1)) if m else -1
    except (OSError, ValueError):
        return -1
    return -1


# ---- GPU --------------------------------------------------------------------

def probe_gpu() -> list[dict[str, Any]]:
    gpus: list[dict[str, Any]] = []

    # 1) NVIDIA via nvidia-smi (all OSes)
    out = _run([
        "nvidia-smi",
        "--query-gpu=name,memory.total",
        "--format=csv,noheader,nounits",
    ])
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[0]:
            try:
                vram_mb = int(float(parts[1]))
            except ValueError:
                vram_mb = None
            gpus.append({"name": parts[0], "vendor": "nvidia", "vramMB": vram_mb})
    if gpus:
        return gpus

    system = platform.system()
    try:
        if system == "Windows":
            out = _run([
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_VideoController | "
                "ForEach-Object { \"$($_.Name)|$($_.AdapterRAM)\" }",
            ])
            for line in out.splitlines():
                if "|" not in line:
                    continue
                name, ram = line.split("|", 1)
                name = name.strip()
                if not name:
                    continue
                vram_mb = None
                ram = ram.strip()
                if ram.isdigit() and int(ram) > 0:
                    vram_mb = int(ram) // MB
                gpus.append({"name": name, "vendor": "unknown", "vramMB": vram_mb})
        elif system == "Darwin":
            out = _run(["system_profiler", "SPDisplaysDataType"])
            name = None
            vram_mb = None
            for raw in out.splitlines():
                line = raw.strip()
                cm = re.match(r"Chipset Model:\s*(.+)", line)
                if cm:
                    if name:
                        gpus.append({"name": name, "vendor": "apple", "vramMB": vram_mb})
                    name = cm.group(1).strip()
                    vram_mb = None
                vm = re.match(r"VRAM.*:\s*(\d+)\s*(MB|GB)", line)
                if vm:
                    val = int(vm.group(1))
                    vram_mb = val * 1024 if vm.group(2) == "GB" else val
            if name:
                gpus.append({"name": name, "vendor": "apple", "vramMB": vram_mb})
    except (OSError, ValueError):
        pass

    return gpus


# ---- disk -------------------------------------------------------------------

def probe_disk(path: Path | None = None) -> dict[str, Any]:
    target = Path(path) if path else Path.cwd()
    probe = target if target.exists() else Path(target.anchor or Path.cwd())
    try:
        usage = shutil.disk_usage(str(probe))
        return {"path": str(target), "totalBytes": usage.total, "freeBytes": usage.free}
    except OSError:
        return {"path": str(target), "totalBytes": -1, "freeBytes": -1}


# ---- tier suggestion --------------------------------------------------------

def _best_vram_mb(gpus: list[dict[str, Any]]) -> int:
    best = 0
    for g in gpus:
        v = g.get("vramMB")
        if isinstance(v, int) and v > best:
            best = v
    return best


def suggest_tier(report: dict[str, Any]) -> dict[str, Any]:
    gpus = report.get("gpu", [])
    vram_mb = _best_vram_mb(gpus)
    ram_bytes = report.get("ram", {}).get("totalBytes", -1)
    ram_gb = ram_bytes / GB if ram_bytes and ram_bytes > 0 else 0
    cores = report.get("cpu", {}).get("logicalCores", 0) or 0
    has_gpu = vram_mb > 0

    # faster-whisper size
    if vram_mb >= 10 * 1024:
        whisper = "large-v3"
    elif vram_mb >= 5 * 1024:
        whisper = "medium"
    elif vram_mb >= 2 * 1024:
        whisper = "small"
    elif ram_gb >= 16 and cores >= 8:
        whisper = "small"
    else:
        whisper = "base"

    # local LLM (qwen) size
    if vram_mb >= 24 * 1024:
        llm = "qwen2.5-32b"
    elif vram_mb >= 16 * 1024:
        llm = "qwen2.5-14b"
    elif vram_mb >= 10 * 1024:
        llm = "qwen2.5-7b"
    elif vram_mb >= 6 * 1024:
        llm = "qwen2.5-3b"
    elif ram_gb >= 16:
        llm = "qwen2.5-3b"
    elif ram_gb >= 8:
        llm = "qwen2.5-1.5b"
    else:
        llm = "cloud/paid recommended"

    notes = []
    if not has_gpu:
        notes.append("no discrete GPU/VRAM detected — CPU-bound; expect slower renders/transcription")
    if vram_mb and vram_mb < 2 * 1024:
        notes.append("low VRAM — prefer CPU whisper or a smaller model")
    if ram_gb and ram_gb < 8:
        notes.append("low RAM — keep proofs at 360p/720p and avoid large LLMs")

    return {
        "whisper": whisper,
        "llm": llm,
        "catalogWhisper": whisper,
        "catalogLlm": llm if not str(llm).startswith("cloud/") else None,
        "basis": {
            "gpuVramMB": vram_mb or None,
            "ramGB": round(ram_gb, 1) if ram_gb else None,
            "logicalCores": cores or None,
        },
        "advisory": True,
        "notes": notes,
    }


def suggest_tier_catalog(report: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Return suggest_tier plus catalog-aligned ids (same raw ids; explicit for models.py)."""
    tier = suggest_tier(report)
    return {
        **tier,
        "whisper": tier.get("whisper"),
        "llm": tier.get("llm"),
    }


def gather(disk_path: Path | None = None) -> dict[str, Any]:
    cpu = probe_cpu()
    ram = probe_ram_bytes()
    gpu = probe_gpu()
    disk = probe_disk(disk_path)
    report = {
        "os": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "cpu": cpu,
        "ram": {"totalBytes": ram},
        "gpu": gpu,
        "disk": disk,
    }
    report["suggestedTier"] = suggest_tier(report)
    return report


def _fmt_bytes(n: Any) -> str:
    if not isinstance(n, (int, float)) or n < 0:
        return "unknown"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def print_summary(report: dict[str, Any]) -> None:
    cpu = report["cpu"]
    ram = report["ram"]["totalBytes"]
    gpus = report["gpu"]
    disk = report["disk"]
    tier = report["suggestedTier"]

    print("AVO hardware (advisory)")
    print(f"  CPU  : {cpu['model']}  ({cpu['logicalCores']} logical"
          + (f", {cpu['physicalCores']} physical" if cpu.get("physicalCores") else "") + ")")
    print(f"  RAM  : {_fmt_bytes(ram)}")
    if gpus:
        for g in gpus:
            vram = f"{g['vramMB']}MB" if g.get("vramMB") else "unknown VRAM"
            print(f"  GPU  : {g['name']} ({vram})")
    else:
        print("  GPU  : none detected (CPU-bound)")
    print(f"  Disk : {_fmt_bytes(disk.get('freeBytes'))} free of {_fmt_bytes(disk.get('totalBytes'))} ({disk.get('path')})")
    print(f"  Tier : whisper={tier['whisper']}  llm={tier['llm']}")
    for n in tier["notes"]:
        print(f"         note: {n}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AVO hardware capability probe (advisory only).")
    parser.add_argument("--json", action="store_true", help="Emit the JSON report only.")
    parser.add_argument("--disk-path", default="", help="Volume to check free space on (default: cwd).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = gather(Path(args.disk_path) if args.disk_path else None)
    if args.json:
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    else:
        print_summary(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

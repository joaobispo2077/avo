"""Host capability probing must tolerate missing or malformed platform tools."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from avo import hardware


def test_probe_runner_missing_success_and_os_failure(monkeypatch):
    monkeypatch.setattr(hardware.shutil, "which", lambda name: None)
    assert hardware._run(["tool"]) == ""
    monkeypatch.setattr(hardware.shutil, "which", lambda name: "/resolved/tool")
    run = Mock(return_value=SimpleNamespace(stdout="answer"))
    monkeypatch.setattr(hardware.subprocess, "run", run)
    assert hardware._run(["tool", "arg"], timeout=2) == "answer"
    assert run.call_args.args[0] == ["/resolved/tool", "arg"]
    assert run.call_args.kwargs["timeout"] == 2
    for error in [OSError("missing"), subprocess.TimeoutExpired("tool", 2)]:
        run.side_effect = error
        assert hardware._run(["tool"]) == ""


@pytest.mark.parametrize(
    "system,outputs,model,cores",
    [
        ("Darwin", ["Apple CPU", "8"], "Apple CPU", 8),
        ("Darwin", ["", "invalid"], "fallback", None),
        ("Windows", ["Name=CPU\nNumberOfCores=6"], "CPU", 6),
        ("Windows", ["", "Name=Fallback CPU\nNumberOfCores=4"], "Fallback CPU", 4),
    ],
)
def test_cpu_native_and_fallback_commands(monkeypatch, system, outputs, model, cores):
    monkeypatch.setattr(hardware.platform, "system", lambda: system)
    monkeypatch.setattr(hardware.platform, "processor", lambda: "fallback")
    monkeypatch.setattr(hardware.os, "cpu_count", lambda: 12)
    run = Mock(side_effect=outputs)
    monkeypatch.setattr(hardware, "_run", run)
    assert hardware.probe_cpu() == {
        "model": model,
        "logicalCores": 12,
        "physicalCores": cores,
    }
    if system == "Windows" and len(outputs) == 2:
        assert run.call_args.args[0][0] == "powershell"


def test_linux_cpu_topology_and_missing_proc(monkeypatch):
    monkeypatch.setattr(hardware.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hardware.platform, "processor", lambda: "fallback")
    monkeypatch.setattr(hardware.os, "cpu_count", lambda: None)
    read = Mock(
        return_value="model name : Linux CPU\nphysical id : 0\ncore id : 0\ncore id : 1\nphysical id : 1"
    )
    monkeypatch.setattr(Path, "read_text", read)
    assert hardware.probe_cpu() == {
        "model": "Linux CPU",
        "logicalCores": 0,
        "physicalCores": 4,
    }
    read.side_effect = OSError("no proc")
    assert hardware.probe_cpu()["model"] == "fallback"


@pytest.mark.parametrize(
    "system,outputs,expected",
    [
        ("Darwin", ["17179869184"], 16 * hardware.GB),
        ("Darwin", ["invalid"], -1),
        ("Windows", ["TotalPhysicalMemory=8589934592"], 8 * hardware.GB),
        ("Windows", ["", "17179869184"], 16 * hardware.GB),
        ("Windows", ["", "unknown"], -1),
        ("Other", [], -1),
    ],
)
def test_ram_without_psutil(monkeypatch, system, outputs, expected):
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(hardware.platform, "system", lambda: system)
    monkeypatch.setattr(hardware, "_run", Mock(side_effect=outputs))
    assert hardware.probe_ram_bytes() == expected


def test_ram_psutil_and_linux_sysconf(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(virtual_memory=lambda: SimpleNamespace(total=12345)),
    )
    assert hardware.probe_ram_bytes() == 12345
    monkeypatch.setitem(sys.modules, "psutil", None)
    monkeypatch.setattr(hardware.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        hardware.os,
        "sysconf",
        lambda key: {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 100}[key],
        raising=False,
    )
    assert hardware.probe_ram_bytes() == 409600
    monkeypatch.setattr(
        hardware.os, "sysconf", Mock(side_effect=OSError("unavailable"))
    )
    assert hardware.probe_ram_bytes() == -1


@pytest.mark.parametrize(
    "system,outputs,expected",
    [
        (
            "Linux",
            ["GPU A, 8192\nGPU B, unknown\nignored"],
            [
                {"name": "GPU A", "vendor": "nvidia", "vramMB": 8192},
                {"name": "GPU B", "vendor": "nvidia", "vramMB": None},
            ],
        ),
        (
            "Windows",
            ["", "noise\n|123\nAMD|4294967296\nIntel|unknown"],
            [
                {"name": "AMD", "vendor": "unknown", "vramMB": 4096},
                {"name": "Intel", "vendor": "unknown", "vramMB": None},
            ],
        ),
        (
            "Darwin",
            [
                "",
                "Chipset Model: GPU A\nVRAM (Total): 8 GB\nChipset Model: GPU B\nVRAM: 512 MB",
            ],
            [
                {"name": "GPU A", "vendor": "apple", "vramMB": 8192},
                {"name": "GPU B", "vendor": "apple", "vramMB": 512},
            ],
        ),
    ],
)
def test_gpu_formats(monkeypatch, system, outputs, expected):
    monkeypatch.setattr(hardware.platform, "system", lambda: system)
    monkeypatch.setattr(hardware, "_run", Mock(side_effect=outputs))
    assert hardware.probe_gpu() == expected


def test_disk_failure_and_success(tmp_path, monkeypatch):
    usage = Mock(return_value=SimpleNamespace(total=100, free=50))
    monkeypatch.setattr(hardware.shutil, "disk_usage", usage)
    assert hardware.probe_disk(tmp_path) == {
        "path": str(tmp_path),
        "totalBytes": 100,
        "freeBytes": 50,
    }
    usage.side_effect = OSError("unknown")
    missing = tmp_path / "missing"
    assert hardware.probe_disk(missing) == {
        "path": str(missing),
        "totalBytes": -1,
        "freeBytes": -1,
    }


@pytest.mark.parametrize(
    "gpus", [[], [{"name": "GPU", "vramMB": None}], [{"name": "GPU", "vramMB": 8192}]]
)
def test_hardware_cli_json_and_summary(tmp_path, monkeypatch, capsys, gpus):
    monkeypatch.setattr(
        hardware,
        "probe_cpu",
        lambda: {"model": "CPU", "logicalCores": 8, "physicalCores": 4},
    )
    monkeypatch.setattr(hardware, "probe_ram_bytes", lambda: 16 * hardware.GB)
    monkeypatch.setattr(hardware, "probe_gpu", lambda: gpus)
    disk = Mock(
        return_value={"path": str(tmp_path), "freeBytes": 500, "totalBytes": 1000}
    )
    monkeypatch.setattr(hardware, "probe_disk", disk)
    assert hardware.main(["--json", "--disk-path", str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["gpu"] == gpus and report["suggestedTier"]["advisory"] is True
    disk.assert_called_with(tmp_path)
    assert hardware.main([]) == 0
    output = capsys.readouterr().out
    assert "CPU" in output and "Tier" in output and "16.0GB" in output
    assert ("none detected" in output) == (not gpus)
    assert hardware._fmt_bytes(-1) == "unknown"
    assert hardware._fmt_bytes(1024**6) == "1024.0PB"

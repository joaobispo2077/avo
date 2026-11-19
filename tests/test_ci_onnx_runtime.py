"""CPU workflow installs must not attempt optional ONNX CUDA provisioning."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    "ci.yml",
    "size-signal.yml",
    "orchestrator-smoke.yml",
    "mutation-full.yml",
    "quality-toolchain-smoke.yml",
    "release.yml",
)


@pytest.mark.parametrize("workflow", WORKFLOWS)
def test_cpu_install_skips_cuda_with_the_actual_pinned_node_installer(workflow):
    node = shutil.which("node")
    installer = ROOT / "node_modules/onnxruntime-node/script/install.js"
    if not node or not installer.is_file():
        pytest.skip("Node dependencies required for the actual installer smoke")
    document = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())
    selected = document["env"].get("ONNXRUNTIME_NODE_INSTALL_CUDA")
    # Run the shipped installer against a Linux/x64 host without CUDA. Network,
    # GPU probing and filesystem mutations are deliberately unavailable.
    script = r"""
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const file = process.argv[1];
const selected = JSON.parse(process.argv[2]);
const exit = {};
const forbidden = () => { throw new Error('CPU CI attempted CUDA provisioning'); };
const modules = {
  os: { platform: () => 'linux', arch: () => 'x64' },
  fs: { existsSync: p => !p.endsWith('libonnxruntime_providers_cuda.so') },
  https: { get: forbidden },
  tar: {},
  'child_process': { execFileSync: forbidden },
  'global-agent': { bootstrap: () => {} },
  '../package.json': JSON.parse(fs.readFileSync(path.resolve(path.dirname(file), '../package.json'))),
};
let stopped = false;
try {
  vm.runInNewContext(fs.readFileSync(file, 'utf8'), {
    __dirname: path.dirname(file),
    require: name => Object.hasOwn(modules, name) ? modules[name] : require(name),
    process: {
      argv: [], env: selected ? { ONNXRUNTIME_NODE_INSTALL_CUDA: selected } : {},
      exit: code => { if (code !== 0) forbidden(); throw exit; },
    },
    console: { log: () => {}, warn: () => {} },
  });
} catch (error) { if (error !== exit) throw error; stopped = true; }
if (!stopped) forbidden();
"""
    result = subprocess.run(
        [node, "-e", script, str(installer), json.dumps(selected)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr

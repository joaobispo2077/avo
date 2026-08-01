---
applyTo: "**"
---

# RTK Instructions

RTK means Rust Token Killer from `rtk-ai/rtk`, not Rust Type Kit.

Use RTK for shell commands with noisy output:

```bash
rtk git status
rtk git diff
rtk git log -10
rtk npm test
rtk pnpm list
rtk pytest -q
rtk docker ps
```

Meta commands:

```bash
rtk gain
rtk gain --history
rtk discover
rtk proxy <cmd>
```

Rules:

- Verify with `rtk --version` and `rtk gain` when troubleshooting RTK setup.
- If `rtk gain` fails, do not assume the installed binary is Rust Token Killer.
- Use `rtk proxy <cmd>` when raw output is needed but usage should be tracked.
- Do not use RTK when a specialized IDE/repository file tool is more appropriate.

# Research: AVO consume modes

## Summary

AVO already has one coherent product: an **agent with three registry skills**, a **cloned local toolchain**, a **provider**, and a **footage folder**. Skills, CLI, and MCP are layers of the same stack, not competing products. The current pain is packaging copy that sells extra front doors — especially a PyPI install using the `avo` distribution name, which installs a **different** project.

**Research mode:** Deep
**Confidence:** High on PyPI collision, layering, and “how to use it today.” Medium on future PyPI name and whether to add a local `avo` console script.

**Last verified:** 2026-09-17

## Codebase Analysis

### Existing Patterns

| Pattern | Location | Relevance |
| --- | --- | --- |
| Two-tier install | `docs/install/README.md`, README § Install | Tier 1 = skills (~30s). Tier 2 = clone + ffmpeg/whisper/watch-skill/HyperFrames. |
| Three registry skills | `skills.json`, `agent-skills/` | Product install ships `avo`, `avo-pipeline`, `avo-provider` only (`docs/software-foundation.md`). |
| Cursor slash as skin | `commands/avo/*.md` (~51 files) | Same playbooks as `avo-pipeline/references/*`. Other agents paste intent. |
| Agent routes stages | `docs/avo-workflow.md`, `AGENTS.md` | Python is subprocess, not the conversation product. |
| Timeline CLI | `src/avo/cli.py` (`prog="avo"`) | State machine: pipeline/timeline/sync/animation/… **No** `[project.scripts]`. |
| MCP adapter | `src/avo/mcp/` | 1:1 `avo_<group>_<subcommand>` → `avo.cli.main`. Extra `[mcp]`. Not Gate 1. |
| Stage engines | `python -m avo.transcribe`, `avo.render`, `avo.shorts`, … | Not MCP-bridged. No package-root `__main__.py` (`python -m avo` does not exist). |
| Fat clone-local skill | root `SKILL.md` (~347 lines of constitution) | For agents opened **in this repo**. Not in `skills.json`. |
| Rejected editor MCP | `docs/why-not-editor-mcp.md` | Orchestrator, not NLE timeline MCP. |
| Cloud MCP backlog | `specs/backlog/avo-mcp-cloud.md` | Must never gate local skills/CLI/MCP. |

`scripts/scan-patterns.sh` is referenced by the SDD research skill but **does not exist** in this repo. Stack is already documented: Python 3.10+ (`src/avo/`), Node ≥18 (install + HyperFrames), pytest, uv/npm wrappers.

### Reusable Components

- Skills + `commands/avo/` — user-facing orchestration.
- `python -m avo.cli` — machine API for timeline/review/deliver/cleanup; MCP reuses it.
- Stage modules — power-user / agent subprocesses.
- `bin/install.cjs` + `scripts/install/install.sh|ps1` — Tier 1/2 installer.
- Provider scaffold + `init_project` — required before stages.

### Conventions

- Work in `<rawDir>/edit/`, never this repo.
- Provider + footage path blocking before stages.
- MCP additive; skills and clone remain first-class (`docs/avo-mcp.md`).
- Windows PowerShell is a first-class install path.

## External Solutions

Industry 2026 consensus: **Skills + CLI + MCP are layers, not alternatives.**

### Option 1: Skills (knowledge / orchestration)

- **Pros**: Progressive disclosure (metadata always, body on trigger, references on demand). Transport-agnostic. Cheap idle context. Encodes “how” (flags, gates, when to ask).
- **Cons**: Without a runtime, skills are docs in the agent’s head. Fat `SKILL.md` (>500 lines) burns context (Anthropic / Microsoft guidance: keep body short, push detail to `references/`).
- **Effort**: Already shipped (three skills + reference tree).
- **Source**: [Anthropic Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills); [Microsoft Agent Skills](https://learn.microsoft.com/en-us/agent-framework/agents/skills)
- **Last verified:** 2026-09-04 — High

### Option 2: CLI (execution)

- **Pros**: Token-efficient vs large MCP tool schemas. Same tools humans debug. Exit codes, `--help`, JSON. Playwright’s coding-agent path: **CLI first**, skills optional, MCP only when persistent session helps.
- **Cons**: Weak at harness discovery (`tools/list`). No typed schemas unless the agent reads `--help`. Needs PATH / venv.
- **Effort**: Module CLI exists; console script and `python -m avo` do not.
- **Source**: [Playwright coding-agent CLI](https://playwright.dev/docs/getting-started-cli); [ddewhurst: Skills, CLI, MCP](https://ddewhurst.com/blog/skills-cli-and-mcp-picking-the-right-tool-layer-for-your-ai-agent/)
- **Last verified:** 2026-09-04 — High

### Option 3: MCP (integration / harness discovery)

- **Pros**: `tools/list` for IDEs that want a tool palette. Typed args. MRTR for gated/destructive calls. 2026-07-28 stateless core fits **local stdio** without sessions (cloud remains optional).
- **Cons**: Schema tax. Blocking round-trips vs shell background jobs. Easy to over-promote as “the product.” AVO MCP covers `avo.cli` groups only — not transcribe/shorts/init.
- **Effort**: Shipped as optional extra.
- **Source**: [MCP 2026-07-28 / Claude](https://claude.com/blog/bringing-mcp-2026-07-28-to-claude); AVO `docs/avo-mcp.md`
- **Last verified:** 2026-09-04 — High

### Option 4: PyPI distribution named `avo`

- **Pros**: Familiar Python install if the name were ours.
- **Cons**: **Name taken.** [pypi.org/project/avo](https://pypi.org/project/avo/) is FaqihHakim’s agent runtime (v0.1.6, verified 2026-09-17). It has its own `avo` CLI, `import avo`, `AVO_*` env, and an `[mcp]` extra. Installing the `avo` distribution from PyPI installs **that** package.
- **Effort:** Do not fight for the name. If a public wheel is ever needed, pick a distinct distribution name and keep git+editable as the default.
- **Source**: PyPI `avo` 0.1.0–0.1.6 (2026-09-01 through 2026-09-16)
- **Last verified:** 2026-09-17 — High

### Closest analogue: Playwright CLI + skills

Playwright **inverts** AVO’s on-ramp: install `@playwright/cli`, then optional `playwright-cli install --skills`. Skills-less still works via `--help`. MCP is a **different** fit (persistent browser), not the default for coding agents.

AVO cannot copy “CLI first” as the *product* — the product is conversation (strategy confirm, watch LOOP judgment, approval gates). AVO **can** copy Playwright’s honesty: skills without the engine are incomplete, and MCP is not the start.

## Comparison Matrix

Weights are for *this* repo’s direction (local-first agent orchestrator), not generic tooling.

| Criteria | Weight | Skills + toolchain (primary) | Skills-only Tier 1 | `python -m avo.*` | `avo.mcp` | PyPI `avo` |
| --- | ---: | --- | --- | --- | --- | --- |
| Matches “talk to agent, drop footage” | 5 | 5 | 2 | 1 | 2 | 0 |
| Can cut/transcribe/render | 5 | 5 | 0 | 4 (mechanical) | 1 (`cli` subset) | 0 (wrong pkg) |
| Token / context cost | 3 | 4 (progressive refs) | 4 | 5 | 2 | n/a |
| Harness tool discovery | 2 | 2 | 2 | 1 | 5 | n/a |
| Name / install safety | 5 | 5 (git + skills.sh) | 5 | 5 (from clone) | 3 (docs lie) | 0 |
| Windows first-class | 3 | 5 | 5 | 4 | 4 | n/a |
| **Weighted** |  | **strong** | on-ramp only | power-user | adapter | **forbid** |

## Answers (open questions from consume-mode exploration)

### 1. PyPI `avo` — ever, or docs-only clone?

**Do not publish or advertise an install from the PyPI distribution named `avo`.**

The name is taken by another 2026 AI-agent runtime with an `avo` CLI and `[mcp]` extra. Our error strings in `src/avo/mcp/server.py` and `src/avo/mcp/__init__.py` currently tell users to install the wrong package.

**Use instead:** clone / existing checkout + `pip install -e ".[mcp]"` or `uv sync --extra mcp`.

A future public wheel needs a **new distribution name** (candidates to spike: `avo-orchestrator`, `avo-video` — confirm on PyPI before claiming). Even then, keep git+editable as the documented default: ffmpeg, whisper weights, watch-skill, HyperFrames, and `tools/` clones are not a wheel.

### 2. Real `avo` console script, or always `python -m avo.cli`?

**Canonical docs form: `python -m avo.cli` and `python -m avo.mcp`.**

Reasons: no `[project.scripts]` today; no package-root `__main__.py`; Soteria already owns the `avo` command on PyPI/PATH; argparse `prog="avo"` is cosmetic.

**Optional later (venv-local only):** `[project.scripts]` alias after editable install, documented as “inside the AVO venv,” never as a global `pip install`. Do not tell users to type `avo` on an arbitrary shell.

Packaging guide still recommends `[project.scripts]` *and* `python -m` together. For AVO, `python -m` is the unambiguous half.

### 3. Tier 1 without clone — teaser, or refuse “ready” until Gate 1?

**Keep the 30s on-ramp. Stop calling it ready to mass-produce.**

Industry (skills.sh / `npx skills add`) is *meant* to copy playbooks without the engine. Playwright is honest that skills enrich a CLI you already installed. AVO inverted that; the install is valid **if labeled**.

Do **not** block Tier 1 until Gate 1 — that kills “paste this into your agent” and non-video tasks (`/avo.help`, `/avo.guidelines`, `/avo.provider` copy). Do **yes** put the incompleteness in the same heading as “One command”: agent brain only; ffmpeg/whisper need `--full` from a clone.

README Quickstart already says “Ask before full toolchain setup” — good. Hero “One command” + “mass-produce” still oversells.

### 4. Drop MCP from README hero nav?

**Yes. Move `docs/avo-mcp.md` under Documentation, not peer to Quickstart.**

Matches written invariant (MCP additive) and 2026 layering (skills+CLI default; MCP when the harness should `tools/list`). Keep the “why not editor MCP” row — that is positioning, not a consume mode.

`specs/backlog/readme-hero-nav.md` already wanted a compact nav; MCP as a hero cell fights that.

### 5. Wave 2–4 slash forest vs fold under `/avo.motion`?

**Keep the Cursor `/avo.*` catalog. Do not add more registry skills. Do not delete satellites.**

`avo-pipeline` is already a gateway skill with a router table and `references/*.md` (progressive disclosure L2/L3). Slash files are Cursor command-palette skins. Other agents never see 51 skills — they load three.

Folding `/avo.figma` into `/avo.motion` only hides discoverability in Cursor. Cost of the forest is README/docs implying 51 engines. Fix with `/avo.help` grouping (core pipeline vs HyperFrames routers vs channel chrome), not deletion.

### 6. Fat root `SKILL.md` vs registry `agent-skills/avo`?

**Canonical for users who never clone: the three registry skills.**

`docs/software-foundation.md` already says product install ships those three. Root `SKILL.md` is the clone-local constitution (Hard Rules + worked examples) for agents opened **on this repo** (“Install broke?”). Anthropic: keep triggered `SKILL.md` short; push depth to references. Registry `agent-skills/avo/SKILL.md` is the right L2. Do not put the fat file on `npx skills add`.

`avo-pipeline/SKILL.md` still links `../../SKILL.md` — that path is broken for registry-only installs. Point never-clone users at GitHub blob URLs / `docs/avo-workflow.md` on GitHub, not a relative repo file.

### 7. Rename CLI `pipeline` vs `/avo.pipeline`?

**Rename the CLI group (recommended: `lifecycle` or `run-state`). Keep `/avo.pipeline` as the user word.**

CLI `pipeline` is a JSON state machine (`tests/test_pipeline_cli.py`). Slash `/avo.pipeline` is stages 0–7 including whisper + HyperFrames + watch. MCP currently exposes the CLI group as `avo_pipeline_*`. A rename is a small breaking change for anyone scripting `python -m avo.cli pipeline`; almost no humans should be doing that yet. Cheaper than teaching two “pipelines” forever.

## How to use AVO today

### The one path (creators)

1. **Tier 1** — paste the README agent prompt, or `npx skills add joaobispo2077/avo -a <agent>`, or curl/irm installer. You get playbooks. Cursor also gets `/avo.*`.
2. **Tier 2** — clone this repo, `bash scripts/install/install.sh --full --lang en` (or `pwsh … -Full`). ffmpeg, whisper, watch-skill, HyperFrames.
3. **Session** — declare **provider** + **footage folder**. Open the agent in the footage folder or paste the path. Outputs go to `<folder>/edit/` only.
4. **Run** — Cursor: `/avo.pipeline`. Other agents: “Load skill `avo-pipeline`. Run the full pipeline. Provider: … Footage is at …”
5. **Approve** — after watch-skill + transcript analysis, review `edit/preview/` and `edit/review/`. Say approve. Repeat until deliver.

That is the product. Everything below is a door into the same loop.

### Power-user doors (optional)

| Want | Run |
| --- | --- |
| One mechanical stage | `python -m avo.transcribe` / `avo.render` / `avo.shorts` / … from the clone venv |
| Timeline / review / cleanup JSON | `python -m avo.cli … --project <rawDir>/avo.project.json` |
| IDE tool list over that CLI | `pip install -e ".[mcp]"` then `python -m avo.mcp` (stdio). Not transcribe. |
| Motion engine | HyperFrames CLI (`npm run hf:*` in the clone) as the agent already does |
| Verify proofs | watch-skill (own CLI/MCP/REST) — required engine, not AVO UX |
| Channel setup | `/avo.provider` or `python -m avo.provider_scaffold` then `init_project` |

### Do not use as a start

- Skills-only and expect a master.
- The unrelated `avo` distribution from PyPI.
- MCP as “install AVO.”
- CapCut/DaVinci/Premiere MCP instead of this orchestrator (wrong product).
- Cloud/remote MCP (backlog; never required).
- Opening this git repo as the footage project (setup/recovery only).

### Layer diagram

```text
User talk  →  skills + /avo.* (orchestration, gates, judgment)
                 │
                 ├─ python -m avo.<stage>     (engines)
                 ├─ python -m avo.cli         (timeline machine API)
                 │         └─ python -m avo.mcp   (optional adapter)
                 ├─ hyperframes CLI
                 └─ watch-skill
                        │
                        ▼
                 <rawDir>/edit/
```

## Recommendation

**Preferred:** One advertised consume mode — **agent skills + local toolchain + provider + footage**. Document CLI and MCP as adapters. Relabel Tier 1. Remove instructions that install the unrelated PyPI `avo` distribution (docs **and** stderr). Canonical invoke `python -m avo.cli` / `python -m avo.mcp`. Drop MCP from README hero. Keep three registry skills + Cursor slash skins. Treat root `SKILL.md` as clone-local.

**Alternative:** Same, plus a venv-local `[project.scripts]` alias with a name that is not global PyPI `avo` (or clearly scoped “AVO venv only”).

**Avoid:** Publishing `name = "avo"` to PyPI. Selling MCP or skills-alone as full products. Blocking Tier 1 on Gate 1. Deleting the slash catalog. Fighting Soteria for the `avo` command.

**Confidence:** High — PyPI collision is primary-source; in-repo layering matches 2026 Skills/CLI/MCP writeups; AVO docs already state MCP is additive. Remaining work is copy + a few error strings, not architecture.

## Risks & Unknowns

- **Wrong-package install (now):** anyone following MCP docs gets Soteria. Mitigation: rewrite install strings immediately.
- **`import avo` / PATH `avo` collision** if a user mixes the unrelated package and this clone in one env. Mitigation: dedicated venv; install AVO only from its checkout.
- **Future wheel name:** `avo-orchestrator` / `avo-cli` not confirmed free (PyPI fetch inconclusive). Spike before any publish plan.
- **CLI `pipeline` rename** breaks MCP tool names `avo_pipeline_*` and any scripts. Mitigate with a deprecated alias for one minor version.
- **Registry skill still points at repo-relative `SKILL.md` / `AGENTS.md`.** Never-clone sessions may miss Hard Rules. Mitigate with GitHub URLs in registry skills.
- **Did not smoke** a fresh Windows Tier 1+2 or MCP stdio harness in this pass.

## Sources

| # | URL | Type | Reliability | Key finding |
| --- | --- | --- | --- | --- |
| 1 | https://pypi.org/project/avo/ | Official package | High | Name taken; unrelated agent runtime; `[mcp]` extra; `avo` CLI; v0.1.6 on 2026-09-16 |
| 2 | https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills | Official | High | Skills = progressive disclosure; short SKILL.md + references |
| 3 | https://learn.microsoft.com/en-us/agent-framework/agents/skills | Official | High | Same three-level load; fat SKILL.md is an anti-pattern |
| 4 | https://playwright.dev/docs/getting-started-cli | Official | High | Coding agents: CLI + optional skills; MCP is a different fit |
| 5 | https://claude.com/blog/bringing-mcp-2026-07-28-to-claude | Official | High | Stateless core; stdio local still valid; cloud not required |
| 6 | https://ddewhurst.com/blog/skills-cli-and-mcp-picking-the-right-tool-layer-for-your-ai-agent/ | Blog | Medium | Start Skills+CLI; add MCP where discovery/state/auth need it |
| 7 | https://www.getmaxim.ai/blog/the-skills-vs-mcp-debate-understanding-two-layers-of-the-same-stack/ | Blog | Medium | Skills did not kill MCP; MCP moved down the stack |
| 8 | https://www.npmjs.com/package/skills | Official CLI | High | `npx skills add owner/repo` from GitHub; AVO already uses this |
| 9 | https://packaging.python.org/en/latest/guides/writing-pyproject-toml/ | Official | High | `[project.scripts]` is the installable binary; `python -m` still valid |
| 10 | In-repo: `docs/avo-mcp.md`, `docs/install/README.md`, `docs/agent-skills.md`, `docs/software-foundation.md`, `pyproject.toml`, `skills.json` | Primary | High | Additive MCP; two-tier install; no console_scripts; three shipped skills |

## Confidence Assessment

**Overall confidence:** High

**Reasoning:** The blocking product question (PyPI `avo`) is a primary-source collision dated this week. Consume-mode layering is independently described by Anthropic, Playwright, and multiple 2026 tooling writeups, and already written in AVO’s own MCP/install docs. Remaining choices (console-script alias, CLI group rename, hero-nav edit) are copy/packaging, low reversal cost.

**Gaps:** No live `npx skills add` / Gate 1 smoke on a clean Windows box in this pass. Alternate PyPI names not locked. Soteria `avo` may keep shipping extras that worsen the footgun.

---

This pass answers the consume-mode exploration’s open questions with external
sources; it does not re-litigate editor MCP or avo.cloud.

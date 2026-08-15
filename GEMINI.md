# AVO — Gemini orientation

Follow **[`AGENTS.md`](AGENTS.md)** as the canonical source of truth for all AI
agents in this repository. Do not contradict or weaken it.

Software foundation rules live in `AGENTS.md` (always-on — **not** optional
skills): branch policy, behavior preservation, TDD / Test Trophy, KISS / DRY /
YAGNI / SOLID, SemVer + `CHANGELOG.md` + annotated tags, and documentation under
`./docs`.

On-demand design skills `design-pattern-selection` and `architecture-selection`
may exist under local `.claude/` / `.cursor/` / `.agents/` trees for
**development**. They are **not** shipped as AVO product skills via
`skills.json` / `npx skills add`.

For editing and pipeline workflows, see `AGENTS.md` and
[`docs/install/README.md`](docs/install/README.md).

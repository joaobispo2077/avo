# /avo.media reference

**Motion engine gate:** Apply [shared arguments](arguments.md) and inspect native
`animation engine-show` with available context before motion-specific skill/setup.
HyperFrames remains the built-in default. For selected code-drawn, follow the
[advanced workflow](code-drawn.md) and common canonical source/review gates.
HyperFrames-only loaders and recipes below apply only to selected HyperFrames.
Unavailable Remotion or incompatible treatments block; never silently substitute.

Asset lookup, rights and freezing remain common. HyperFrames registry/paste-block installation is engine-specific; code-drawn declares local assets and dependencies in its manifest.

## Step/state mapping

**Durable state:** pipeline-run.json plus the current canonical timeline revision

**Workflow steps:** Validate media prerequisites → Run media → Verify and report the media result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified media completion

**Valid next commands:** /avo.motion

Thin router to **`media-use`** — resolve BGM, SFX, stock images, and brand logos before HyperFrames renders.

## Required args

| Arg | Required | Notes |
| --- | -------- | ----- |
| `Provider` | yes | Brand scope for logo resolution |
| `ProjectDir` or `rawDir` | yes | Workflow root |

## Load skill

- [`.agents/skills/media-use/SKILL.md`](../../../.agents/skills/media-use/SKILL.md)

Run **`--adopt`** first when project already has local assets to register.

## When to invoke

- Before [`motion.md`](motion.md) when using HeyGen catalog or official logo sources
- Content routers (`/avo.launch`, `/avo.music-video`, …) when skill references media-use

## Related

- SOURCE-LOG: log resolved assets in footage projects

## Canonical track integration

Inspect videoTracks before render: source/generator fingerprint, regions, z-order, fit/crop, compositing, captions/evidence safe zones, and face avoidance. Every contribution links to BMap intent; unresolved or changed sources block.

## Selected artistic guidance

Before style-dependent authoring, run the shared native pipeline status for this project (checkout: `python -m avo.cli pipeline status --project <project> --json`; installed: `avo cli pipeline status --project <project> --json`). Read `briefing.stageContexts.bmap` and its exact selected brief, treatment, constraints, exclusions and current canonical-head identities. Treat this context as offered guidance, never proof that a choice was applied, an approval, or permission to change protected content. Current creator instructions and integrity/accessibility/rights rules take precedence. A bypassed or unselected brief adds no creative gate. Do not discover provider history or select a latest profile independently. See [briefstart](briefstart.md).

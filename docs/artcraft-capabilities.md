# ArtCraft capability coverage for provider components

This is the evidence and scope register for ArtCraft in AVO. Run
`avo cli artcraft catalog --json` to read the bundled knowledge and filter it by
app or behavior. The baseline references were inspected on **2026-11-15**.
The AniCraft bridge documentation was also reviewed on **2026-11-19**.
Local application, connection and output qualification are tracked separately.

ArtCraft apps and their compatible CLIs are separately user-installed tools.
AVO distributes its own integration logic, knowledge metadata and guides only;
it does not bundle, download, install or update ArtCraft runtimes, CLI binaries,
installers or third-party plugins. Only the selected task's app/CLI is required.
If absent, readiness reports official separate-installation guidance rather
than performing setup or asking for the whole suite.

The product goal is to author an otherwise unsupported creative component,
preserve its editable source and reuse a versioned definition for a provider.
AVO retains timeline authority and review/admission responsibilities. Existing
boundaries are documented in [providers](providers.md), [adapters](adapters.md)
and [code-drawn motion](code-drawn-motion.md); ArtCraft is an additional explicit
authoring route, not a change to existing default motion engines.

**Selection constraint (2026-11-15)**: select this route only for a direct user
request or a documented unmet creative requirement after existing AVO/reuse
options have been checked. Installation problems, permissions, bugs and transient
failures are not creative gaps. Ordinary workflows must not probe apps, connect
MCP servers, fetch these references or load app-specific guides. Eligible jobs
load only their selected app/operation; an unchanged qualified reusable output
does not require reopening its authoring tool when canonical reuse checks pass.

## Capability families in initial scope

The user's requested capability families form the coverage baseline below.
Product-overview descriptions and agent guides establish discovery candidates;
they do not prove a command, codec, format conversion or render works locally.
Each family's individual operations must acquire an explicit support disposition.

| Application | Capability families to discover and classify | Representative provider use and qualification task | Official references |
| --- | --- | --- | --- |
| SoundCraft | Audio editing/tools and playlists; mixing/routing; parameter automation; built-in/external effects; instruments/MIDI editing and exchange; recording; video reference; measured audio bounce | Editable branded sound cue: arrange, process, automate, save/reopen, inspect and export audio | [Overview](https://craft.wiki/apps/soundcraft/overview/), [agents](https://craft.wiki/apps/soundcraft/ai-agents/) |
| AniCraft | Vector drawing and stage tools; keyframes and classic/shape tween easing; symbols/nested scenes; masks/guides; native/Adobe document input; SVG input; frame, sprite, Lottie and video exports | Editable animated badge or social lower third, with inspected phases and exported transparent frames | [Overview](https://craft.wiki/apps/anicraft/overview/), [agents](https://craft.wiki/apps/anicraft/ai-agents/) |
| EffectCraft | Layered compositions/parenting/mattes/blending; animated properties/expressions; shape/mask/text treatment; effects/styles; cameras/lights/3D; tracking/stabilization/roto; render queue | Editable masked lower third with declared easing and qualified transparent export | [Overview](https://craft.wiki/apps/effectcraft/overview/), [agents](https://craft.wiki/apps/effectcraft/ai-agents/) |
| FilmCraft | Timeline editing, nesting and multicam; color/scopes; clip effects/motion; audio effects/mix/automation; titles/captions; export; timeline interchange | Save/reopen a bounded edited segment; inspect exchange fidelity and return through existing AVO import rules | [Overview](https://craft.wiki/apps/filmcraft/overview/), [agents](https://craft.wiki/apps/filmcraft/ai-agents/) |
| VectorCraft | Drawing/brushes/width; path reshape/edit/combine; paint/color/materials; live/3D effects; type/spelling; artboards/layout/perspective; reusable symbols; data/graphs/variables; slices/tracing; screen/print/package output; commands/scripts | Parameterized brand emblem or label artwork with editable paths and inspected SVG/PNG exchange | [Agents](https://craft.wiki/apps/vectorcraft/ai-agents/), [command steps](https://craft.wiki/apps/vectorcraft/write-command-steps/) |
| PhotoCraft | Layers/masks/smart objects; nondestructive adjustments; selection; layer styles; type/shapes/paths; painting/retouching; filters; color/depth/profile handling | Layered image card with an editable Curves adjustment and a verified composite for review | [Overview](https://craft.wiki/apps/photocraft/overview/), [automation](https://craft.wiki/apps/photocraft/automation/) |
| LightCraft | Photo organization/search; culling; development/color/detail; masking; retouching; crop/geometry; presets/profiles; merge; photo/contact-sheet/print/slideshow output | Apply a reusable provider photo treatment in an isolated library and inspect the exported image | [Overview](https://craft.wiki/apps/lightcraft/overview/), [agents](https://craft.wiki/apps/lightcraft/ai-agents/) |
| FigCraft | Frames/layout/constraints; components/variants/properties; styles/variables; vectors; paints/effects; rich text; prototype behavior; developer handoff; boards | Brand card with editable layout, content variants and inspected static output; record interactivity lost in export | [Overview](https://craft.wiki/apps/figcraft/overview/), [agents](https://craft.wiki/apps/figcraft/ai-agents/) |
| TextureCraft | 3D/UV painting; per-channel layers/masks; reusable materials; mesh-map baking; texture/channel-packed exports; preview rendering | Reusable textured object/material with native project, dependency mesh and inspected texture/preview output | [Overview](https://craft.wiki/apps/texturecraft/overview/), [agents](https://craft.wiki/apps/texturecraft/ai-agents/) |
| DeckCraft | Slide masters/layouts/themes; shapes/drawing; text; tables/charts/media; transitions/animation; presenter tools; comments/accessibility/review | Reusable branded explanation slide, save/reopen and inspect an exported frame; qualify motion separately | [Overview](https://craft.wiki/apps/deckcraft/overview/), [agents](https://craft.wiki/apps/deckcraft/ai-agents/) |

## Documented operation surfaces

Commands below are **reference examples**, not commands run during this task.
They must be checked against the installed release before execution. MCP is an
assistant connection; CLI is an invocation surface; headless/live describes
execution context. These are separate capabilities, not four interchangeable
protocols. Common naming does not imply common switches or permissions.

| Application | MCP/background entry | Standalone/batch surfaces documented | Live-session entry or limitation |
| --- | --- | --- | --- |
| SoundCraft | `soundcraft-cli mcp`; background operation without an audio device | `commands`, `--help`, `run --demo --cmd ... --bounce ...` | `soundcraft --control 7801`, then `soundcraft-cli mcp --connect 7801` |
| AniCraft | `anicraft-cli mcp` | `new`, `info`, `render`, `render-seq`, `gif`; verify the selected release's JSON-lines schema | App `--control`, CLI `mcp --bridge`; the documented bridge finds the running app's token. Local qualification remains pending. [MCP guide](https://github.com/storytold/anicraft/blob/main/docs/mcp.md) |
| EffectCraft | `effectcraft-cli mcp`; separate background instance | `--help`, `render main.ecproj --comp Main --out main.mp4` | App `--control 9877`, CLI `mcp --bridge 9877` |
| FilmCraft | `filmcraft-cli mcp --project <project.fcproj>` or empty/demo project | `commands` discovery; no standalone render syntax inferred from its MCP guide | App `--control 9876`, CLI `mcp --bridge 127.0.0.1:9876`; shared per-session control token |
| VectorCraft | `vectorcraft-cli mcp`; startup discovers an already running control session or uses background documents | Command-step files accept JSON arrays or JSON Lines; command listing/batching, document inspection and export | Start app with `--control 7979` before MCP startup; restart connection discovery if app started later |
| PhotoCraft | `photocraft-cli mcp` with explicit file roots | `convert`, `info`, `run`, `batch`, `droplet`, `commands`; recorded actions | Agent guide points to a separate live control protocol; do not invent flags from another app |
| LightCraft | `lightcraft-cli mcp --library <library>` or photo-folder/demo input | Command discovery through documented agent surfaces; a standalone export recipe still needs technical/local verification | App `--control 7980`, CLI `mcp --connect 127.0.0.1:7980`; library must have one owner |
| FigCraft | `figcraft-cli mcp` | `render`, `export`, `convert`, `commands --filter ...`; further scripting requires developer reference | App `--control 7979`, CLI `mcp --attach 7979` |
| TextureCraft | `texturecraft-cli mcp --read-root ... --write-root ...` | `new`, `info`, `bake`, `export`, `render`, `commands`, `run`, `batch`; `serve` accepts JSON lines | App `--control 7878`, CLI `mcp --bridge 7878`; authenticated bridge |
| DeckCraft | `deckcraft-cli mcp` | `convert`, `render`, `info`, `commands`, `render-transition`; inspect `help run` for scripting | App `--control 7990`, CLI `mcp --connect 7990` |

### Per-application constraints that affect route choice

- **SoundCraft**: Background MCP accepts separate repeatable
  `--automation-read-root` and `--automation-write-root` limits. Those limits do
  not protect a live connected app. Its overview identifies pre-alpha gaps,
  including MIDI-controller recording and AAF/OMF session exchange; menu presence
  is not implemented support. Audio exports still need independent AVO checks.
- **AniCraft**: The agent guide states that execution inherits the user's OS
  permissions and refers to external sandboxing for strict isolation. Native
  project, tween and export support is early-alpha evidence, not a guarantee
  of deterministic or format-identical output in a particular release.
- **EffectCraft**: Background MCP documents automation read/write roots; under
  those restrictions scripts are disabled. Expressions and native project
  imports must therefore be assessed against the actual execution mode. Alpha
  maturity and advertised effects do not qualify a specific renderer.
  The selected Windows 0.24.1 CLI profile retains editable Arial text and a
  closed backing mask. It renders the six-frame span beginning at index 3 and
  ending before index 9. Independent frame-index and seconds requests agree
  on the first transparent frame. The span is for standalone review.
- **FilmCraft**: Background and desktop copies must not write the same project;
  background work needs an explicit save. The live protocol requires an
  ephemeral shared token. The guide warns of broad filesystem access; it does
  not establish root-limiting flags equivalent to EffectCraft's.
- **VectorCraft**: Document tools and UI-only inspection are distinct. Inspect
  individual command availability rather than hard-coding a tool count. Its
  background/live auto-discovery means actual mode must be checked after
  connection. Command-step failure can follow successful earlier steps: undo or
  process exit is not proof that prior file exports were rolled back.
- **PhotoCraft**: Background MCP requires explicit read/write roots; without
  them it has no filesystem access. Imported document text is untrusted input.
  Live control has separate developer documentation and an app preference.
  Preserve native layers and validate color/depth conversion for each export.
  The selected `layered-image-card` profile was exercised on Windows 0.23.1
  through the CLI with synthetic files. It retains the original pixel layer
  and an editable fixed Curves adjustment in `.pcraft`. Its standalone PNG
  preserves the source's 8-bit RGBA geometry, alpha and embedded sRGB profile.
  The reviewed PNG flattens layers. Automatic execution requires an
  independently confined runner.
- **LightCraft**: App and CLI should match releases. A library cannot be open
  in both background and desktop processes. Live control is local but has no
  password per the guide, so a loopback address alone does not prove exclusive
  access. RAW decoding varies by camera and may use embedded previews.
  The selected Windows 0.21.1 CLI profile develops one original RGB JPEG in a
  fresh library. A retained catalog snapshot and its fingerprinted original
  reproduced the same exposure and sRGB image in a second library. This
  qualification covers JPEG and the standalone PNG review.
- **FigCraft**: Background automation roots are supplied to MCP. In attached
  mode, equivalent limits must instead be supplied when starting the app; they
  are not compatible CLI `--attach` options. Imports and live collaboration have
  early-alpha limitations. A prototype export must declare lost behavior.
  The selected Windows 0.18.1 CLI recipe uses a blank document to build a
  two-variant component set with auto layout and a prototype click-to-switch.
  The editable native file retains both variants and the interaction. The
  standalone PNG contains the compact variant. Batches also use the native
  root flags observed in that release.
- **TextureCraft**: Background roots use `--read-root`/`--write-root`, unlike
  the automation-prefixed switches elsewhere; without them filesystem work is
  unavailable. Live app file handling is separate and the bridge uses a token.
  `bake` writes in place. Colors expressed numerically and hex colors have
  different documented transfer assumptions; preserve that distinction.
- **DeckCraft**: Background automation roots do not constrain connected live
  work and cannot be combined with `--connect`. Slide render indexes start at
  zero; output scale uses points rather than assumed video pixels. Frame export
  is not evidence that a complete animated slide can be reconstructed.
  The selected Windows 0.18.1 CLI profile retains a custom master layout, its
  editable placeholder and a 600 ms fade into slide index 1. The 960 by 540
  point deck yields a verified 320 by 180 pixel midpoint for standalone review.
  The native deck keeps the complete transition.

## Qualification model and bounded scope

The required operation dispositions are **documented-only**, **locally verified**,
**unavailable** and **unsupported**. Availability and trust remain distinct from
artifact status: authoring/exported, reproducibility-qualified, canonically
admitted and creator-approved. A task may succeed in the app and still fail
AVO admission. Guidance must explain that gap without weakening existing rules.

For each task record the requested capability, evidence URL/date, observed app
and CLI identity/release/platform, selected mode, discovered command support,
file boundary, ownership, inputs/dependencies, editable output, exchange format,
inspection results and precise blockers. No execution readiness fields are
populated by this documentation task.

Full integration qualification requires a representative native
author/inspect/save/reopen/export task for every app in the first table. Each
mode advertised as executable needs its own evidence. Complete coverage of
the task families means explicit classification and focused guidance, not a
promise to implement every upstream menu action. A missing app is an unpassed
qualification gate, not a reason to mark its scope complete.

The motivating trial is a provider social lower third with editable artwork,
mask/easing/text choices, optional isolated sound, two declared aspect ratios,
five valid content variants and reuse in three external video projects. A
combined workflow may use VectorCraft for artwork, AniCraft or EffectCraft for
motion, and SoundCraft for sound **if local checks qualify that route**. This
is a candidate decomposition, not a mandatory engine or a validated result.

Reuse must remain source-based: preserve native projects, source assets,
fonts/plugins and their rights references, parameters and environment identity.
Any regenerable intermediate must satisfy existing canonical provenance rules.
Prior proofs/previews/masters remain review references. FilmCraft exchange must
respect existing timeline-import limitations rather than introducing a second
canonical timeline. Manual handoffs remain guided-only until their artifacts
pass the same reconstruction and review gates.

## Boundaries left for implementation planning

- Choose the smallest extension of existing provider kits, component instances,
  adapters, readiness and generated-media admission after tracing their current
  flow. This document chooses no new framework, dependency or registry layer.
- Resolve exact technical references and local command discovery for the selected
  release. No suite-wide flags, schemas, output guarantees or sandbox are assumed.
- Keep public integration guidance and reusable orchestration in AVO; provider
  media/native source and per-video jobs remain in declared external workspaces.
- Decide concrete per-app qualification fixtures and resource budgets; retain
  evidence for unsupported modes rather than installing the whole suite merely
  to write a specification.
- Preserve existing project defaults, approval gates, no-framework/explicit
  engine choices, audio behavior and provider boundaries.

## Evidence limitations

The AI-agent pages for all ten applications were read. The nine accessible app
overviews were also inspected; the VectorCraft overview URL could not be fetched,
so its broad capability inventory above retains the user's supplied baseline
and the retrieved agent/command-step references. Detailed support for every
listed brush, graph, effect, format and platform is intentionally unqualified.
PhotoCraft's automation page is `/automation/`, not the assumed `/ai-agents/`.

Project ai-memory was attempted through its current-project CLI because no MCP
memory tools were exposed, but the local server could not be reached in this
environment. Current repository sources and project instructions supplied the
compatibility baseline; no claim is made about unseen past architecture decisions.

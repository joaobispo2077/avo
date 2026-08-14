<!-- ai-memory:start -->
## Long-term memory (ai-memory)

This project uses [ai-memory](https://github.com/akitaonrails/ai-memory)
for cross-session continuity.

**Default to the current project — always.** Every ai-memory tool
auto-scopes to the project resolved from your session's working
directory. **Do NOT pass `project`, `workspace`, or `cwd` arguments unless the user
explicitly references a *different* project by name** (e.g. "what did we
decide in the `other-app` project?"). Phrases like "this project",
"here", "we", "our work", "where did we leave off" all mean the *current*
project — call the tool with no scoping args. If the user asks about a
handoff and the SessionStart auto-fetched block is already in your
context, just answer from it; do not re-call the tool to "find it again"
in another project.

**Lifecycle hooks already capture every prompt + tool call
automatically.** You never need to manually write routine notes; the
SessionStart hook auto-fetches pending handoffs, and on session end
ai-memory writes a session-summary page and a handoff.
LLM consolidation (compiling observations into topical wiki pages) runs
on PreCompact, on demand via `memory_consolidate`, and at session end
only when the server sets `AI_MEMORY_CONSOLIDATE_ON_SESSION_END`. Only
write a durable wiki page when the user explicitly asks to remember or
annotate something permanently.

### When to reach for each tool

The user can express any of the intents below in plain English —
match the intent to the tool. They do not need to name the tool.

| User says / situation | Tool |
|---|---|
| "have we discussed X?" / "search memory for Y" / before proposing architecture | `memory_query` (current project; `scopes` for named siblings; `global=true` to search every project) |
| "what's been going on" / "show recent activity" (light) | `memory_recent` |
| "is ai-memory healthy?" / "how big is the wiki?" | `memory_status` |
| "give me the stats" / structured snapshot for the agent to consume | `memory_briefing` (read-only; never creates handoffs) |
| "catch me up" / "I've been away" / "what's important right now?" / open-ended exploration | `memory_explore` |
| "where did we leave off?" — and you see a `📥 ai-memory: pending handoff` block in your context | already done — answer from that block; do NOT re-call `memory_handoff_accept` |
| "where did we leave off?" — and no such block is visible | `memory_handoff_accept` (rare; the SessionStart hook usually got there first; pass `workspace` + `project` together only for a named sibling workspace/project) |
| "save context for the next session" / wrapping up / ending this session | `memory_handoff_begin` (session-end only; do **not** use for status/briefing; single-use handoff; terse summary; put detail in `open_questions` + `next_steps` bullets; pass `workspace` + `project` together only for a named sibling workspace/project) |
| "discard that handoff" / "I created a handoff by mistake" | `memory_handoff_cancel` (requires exact `handoff_id` from `memory_handoff_begin`; marks it expired before the next session sees it) |
| "consolidate this session" / "compile what we learned" (also runs on PreCompact; at session end only if `AI_MEMORY_CONSOLIDATE_ON_SESSION_END` is set) | `memory_consolidate` |
| "what did we learn from this session?" / "what memory should we add?" / explicit wrap-up learning review | `memory_auto_improve` (manual learning review for a completed session; omit `session_id` for latest completed session; the server also schedules background review for newly completed sessions in every project when configured) |
| "remember this permanently" / "save a note" / "add an annotation" / durable project knowledge | `memory_write_page` (write a wiki page; do **not** use handoff for permanent notes; put the title as a `# H1` on the first line of `body` and omit the `title` arg — ai-memory derives it from the H1) |
| "read the page about X" / "show me the full content of Y" / "open the page on Z" | `memory_read_page` (full body; pass a query to search or `path` for a direct lookup; pass `workspace` + `project` together only for a named sibling workspace/project) |
| "delete the page X" / "remove that note" | `memory_delete_page` (by exact `path`; idempotent; pass `workspace` + `project` together only for a named sibling workspace/project) |
| "audit the wiki" / "find contradictions" / "what rules should we add?" | `memory_lint` |
| "prune old pages" / "memory cleanup" | `memory_forget_sweep` |

`memory_explore` is the right default for the "I want to know what's
going on" use case — it returns a prose digest whose verbosity
scales automatically to how long it's been since the last activity
(< 1 h → one line; > 30 days → full catchup).

### When the current project comes up empty — broaden the search

`memory_query` searches only the **current** project by default. If a
search comes back empty or thin, the knowledge may live in a **sibling
project** — shared `infra`, `ops`, or a related app. Don't conclude
"we never recorded it" after a single project misses; broaden instead:

- **Know which projects to check?** Re-run with explicit `scopes`, e.g.
  `scopes: [{ "workspace": "default", "project": "infra" }]`.
- **Don't know where it lives?** Pass `global=true` to search every
  project in every workspace at once. Each hit is annotated with its
  workspace + project so you can tell where it came from. `global=true`
  cannot be combined with `scopes`/`project`/`workspace`.

`memory_query` returns **snippets, not full page bodies** — an empty or
short snippet does **not** mean the page is empty (a large page can
match outside the snippet window). To read the whole page, use
`memory_read_page` (by `path`, or pass a `query` to fetch the top hit's
full body; add `workspace` + `project` together only when the user names
a sibling workspace/project).

### Use Retrieved Memory As Operating Guidance

When `memory_query` or `memory_recent` returns `_rules/`, `gotchas/`,
`procedures/`, or `decisions/` pages that match the current task, treat
them as actionable context, not trivia:

- Read full pages with `memory_read_page` when the snippet looks relevant.
- Apply `_rules/` as constraints.
- Check `gotchas/` as preflight warnings before editing the same subsystem.
- Follow `procedures/` as checklists for releases, PR reviews, deploys,
  migrations, and other repeatable workflows.
- Use `decisions/` as prior architecture unless the user explicitly asks
  to revisit them.

Before non-trivial coding, debugging, deployment, release, auth, scope,
migration, PR-review, or data-preservation work, search memory for the
subsystem and task type first. If the first query is thin, broaden or
query specific error/subsystem terms before designing a fix.

### Learning Review

The server schedules background auto-improvement for newly completed sessions in
every project when an LLM provider is configured. `memory_auto_improve` is the manual version:
use it when the user asks what durable lessons this session suggests, or at
explicit wrap-up when reviewing proposed memory would be useful. Scheduled and
manual runs apply or stage validated edits through the auto-improvement approval
path. Admins can turn off scheduling with `[auto_improve.scheduler] enabled =
false`, or opt into manual proposal approval with `[auto_improve]
require_approval = true`, in which case scheduled and manual proposals stay in
pending-writes until approved.

### When you write a project rule, write it here

If you're about to write a durable project rule ("always X", "never
Y", "all PRs must …"), write it in the project's canonical agent
instruction file. Many projects use CLAUDE.md for Claude Code and
AGENTS.md for Codex / OpenCode / Cursor / Gemini CLI, but if the
project says one file is canonical, use that file. ai-memory's lint
pass surfaces the same hint automatically when a `kind: rule` page
lands in `_rules/`.

### Refreshing this snippet

This block is maintained by ai-memory. Two ways to refresh it with
the latest binary's recommended copy:

- **From the agent** (no terminal needed): ask "refresh the ai-memory
  routing in this project" — the agent calls
  `memory_install_self_routing`, picks the right filename for itself
  (Claude Code → `CLAUDE.md`; Codex / OpenCode / Cursor / Gemini →
  `AGENTS.md`), and uses its Write / Edit tool to land the block.
- **From the CLI**: `ai-memory install-instructions` (defaults to
  `CLAUDE.md`; pass `--target AGENTS.md` for non-Claude agents or
  projects that use `AGENTS.md` as the canonical instruction file).

Both are idempotent: re-runs replace the block bracketed by
`<!-- ai-memory:start -->` / `<!-- ai-memory:end -->` markers
without disturbing the rest of the file.
<!-- ai-memory:end -->

# YouTube Video Editing Agent Instructions

`AGENTS.md` is the main source of truth for all AI agents in this repository.
Agent-specific files MAY summarize or adapt these rules for their tools, but
MUST NOT contradict this file. If an instruction conflicts, follow `AGENTS.md`
and flag the conflict for a human.

## Token Efficiency Tools

This repository supports Caveman and RTK for agents that can load repo-local
instructions.

- Caveman controls response style only. Use it when the user asks for
  `/caveman`, "caveman mode", "talk like caveman", "be brief", or fewer output
  tokens. Preserve technical accuracy, exact code, commands, paths, API names,
  and error strings. Stop when the user asks for normal mode or when compression
  would make a destructive/security-sensitive instruction ambiguous.
- RTK controls shell-command output size. For Codex and Copilot shell commands,
  prefer `rtk <command>` for verbose commands such as `git`, tests, package
  managers, Docker/Kubernetes, search, logs, and builds. Use `rtk proxy <cmd>`
  when raw output is needed but usage should still be tracked.
- Verify RTK with `rtk --version` and `rtk gain` when starting RTK-specific work.
  If `rtk gain` fails, do not assume the binary is Rust Token Killer.

## Software Engineering Foundation

These rules apply to **orchestrator code** in this repository (`src/avo/`, `scripts/`,
`tests/`, install, CI). Editorial, audio, and animation rules below still apply for
footage and deliverable work. Full scan: [`docs/software-foundation.md`](docs/software-foundation.md).

### Branch policy

The user owns branches. Agents work only on the checked-out branch and **never** create,
delete, rename, checkout, switch, or orchestrate branches. See [`docs/branching.md`](docs/branching.md).

### Behavior preservation

Change code behavior only when explicitly requested. No speculative refactors or unrelated
cleanup. Prefer small, focused diffs.

### TDD and testing

Validate behavior first. Test Trophy mindset: ~90% cheap unit tests when possible, then
integration, then E2E only for critical flows. Run `pytest -m "not project"` for AVO core
(also `npm run test:unit`). Footage-project tests live under `tests/projects/` —
`npm run test:projects` — and are excluded from CI.
Do not remove tests without equivalent coverage.

### Design principles

KISS, DRY (knowledge not duplication), YAGNI, SOLID when useful, high cohesion, low
coupling. Functional clarity in JS/TS when applicable. Design patterns and architecture
layers are **not** default — use skills `design-pattern-selection` and
`architecture-selection` before introducing them.

### SemVer, changelog, and tags

Orchestrator releases use SemVer (`MAJOR.MINOR.PATCH`) and `CHANGELOG.md`. Git tags:
`vMAJOR.MINOR.PATCH` (annotated). Update `CHANGELOG.md` only after the user confirms
the task is 100% finished. Recommend tag commands; do not create or push tags unless
explicitly asked. See [`docs/versioning.md`](docs/versioning.md).

Video **export** versions for footage projects remain `YYYYMMDD-video-slug-stage-v001`
(editorial) — not SemVer.

### Documentation

User-requested behavior notes, decisions, and strategies → Markdown under `./docs/`
(kebab-case). Link from changelog when using scope branches without tickets.

## Foundational Rule

There is no universal YouTube editing style. The correct edit is the simplest
edit that fulfills the title/thumbnail promise, preserves meaning, improves
comprehension, maintains appropriate momentum, supports the creator identity,
respects viewer time, uses sound and visuals for clear purpose, and complies
with rights, disclosure, safety, privacy, and platform requirements.

Do not force fast cuts, punch-ins, subtitles, memes, transitions, B-roll,
music, or motion graphics into every video. Editing density follows the format,
viewer intent, source material, performance, emotional rhythm, and channel
identity.

## Inspect Before Editing

Before proposing or changing an edit, inspect the repository and available
project materials: source organization, scripts, transcripts, `edit/` outputs,
previous timelines or EDLs, review notes, brand assets, export presets,
analytics, `EDITLOG.md`, `SOURCE-LOG.md`, and any existing project rules.
Preserve sensible existing conventions.

## Format Diagnosis Is Mandatory

Before recommending pacing, graphics, transitions, music, B-roll, or effects,
state the diagnosis:

- Primary format and secondary/hybrid formats.
- Target viewer and viewer intent: learn, decide, follow news, be entertained,
  connect with the creator, hear analysis, or watch a performance.
- Core promise established by title and thumbnail.
- Desired emotional trajectory and information density.
- Source-material quality and limitations.
- Traffic posture: search-led, browse-led, subscriber-led, trend-led, or
  community-led.
- Whether personality or subject is the primary attraction.
- Rights, safety, defamation, privacy, sponsorship, reused-content, and AI
  disclosure risks.
- Publishing urgency and required review gates.

For hybrid videos, identify which playbook controls each section, such as news
opening, talking-head analysis, documentary evidence, and list conclusion.

## Editorial Intent Preservation

Preserve the creator's intended argument, story, opinion, chronology, product
assessment, emotional tone, and factual meaning unless the user explicitly asks
for a change.

Never:

- Splice separate statements into a materially different meaning.
- Remove context that changes a conclusion.
- Manufacture reactions, tension, conflict, chronology, causality, certainty,
  or endorsement.
- Present staged, illustrative, reenacted, archival, stock, AI-generated, or
  unrelated visuals as direct evidence.
- Turn uncertainty into certainty, allegation into fact, opinion into reporting,
  impression into measurement, or jokes into facts without approval.
- Hide sponsorship, affiliate, loaned-product, review-unit, or conflict-of
  interest information.

For news, opinion, documentary, react, clips, podcast highlights, and review
videos, meaning preservation is release-blocking.

## Viewer Promise And Payoff

Treat title and thumbnail as an editorial contract. Confirm the central
question, transformation, result, comparison, conflict, discovery, or value
proposition. The opening must surface proof of value early without deceptive
hooks or unrelated channel intros. The structure must build toward the promised
payoff, and the conclusion must answer the main question or clearly state what
remains unresolved.

## Retention Without Manipulation

Retention is a diagnostic outcome, not permission to distort content. Use open
loops, questions, before/after contrast, evidence previews, chapters, pattern
interruptions, B-roll, on-screen text, silence, and slower moments only when
they improve clarity, anticipation, emotion, or progression.

Avoid empty cliffhangers, random memes, constant punch-ins, sound effects on
every cut, unmotivated speed ramps, captions that compete with the subject,
withholding basic context to stretch watch time, or previews of events that do
not occur.

When analytics are available, classify dips and spikes before proposing fixes.
Possible dip causes include promise mismatch, repetition, confusion, tangent,
slow transition, weak visual support, audio problem, excessive sponsor
interruption, natural topic completion, and audience mismatch. Compare against
similar videos before inferring causality.

## Audio-First Policy

Speech intelligibility is the highest technical priority for most formats.
Preserve the cleanest microphone track, sync external audio before creative
cutting, repair noise/hum/clipping/plosives/mouth noise conservatively, preserve
natural cadence, use room tone where useful, use J-cuts and L-cuts to improve
flow, duck music/effects below speech, check sync and channel mapping, avoid
clipping and uncontrolled peaks, and prepare YouTube masters with 48 kHz audio
unless a documented alternative applies.

Do not treat one online loudness number as an official YouTube requirement.
Use a documented channel target and prioritize consistent perceived loudness,
intelligibility, and headroom. Preserve musical dynamics for covers and
performances.

## Audio Post Production System

Before changing audio, diagnose the source: format, speech/music priority,
available microphones, camera audio, recorder audio, system/game audio, music,
SFX, ambience, sample rates, channel layout, sync method, drift risk, noise,
clipping, room tone, rights status, and delivery target.

Use this default order unless the project documents another workflow:

1. Inventory sources and preserve originals.
2. Sync external audio and verify drift across the full program.
3. Choose the cleanest dialogue anchor and mute only documented rejects.
4. Gain-stage and level-match clips before restoration or compression.
5. Repair technical defects conservatively: hum, rumble, clicks, crackle,
   plosives, mouth noise, clipping, broadband noise, phase, and DC offset.
6. EQ for intelligibility and translation, preferring subtractive fixes before
   presence boosts.
7. Use de-essing, compression, leveling, and limiting only as needed for clarity,
   consistency, and peak control.
8. Build the mix hierarchy: dialogue or vocal lead first, then critical source
   audio, music, SFX, and ambience.
9. Measure loudness and true peak using a documented standard and internal
   channel target.
10. QC the exported file after encode for sync, mapping, intelligibility,
    clipping, pops, mutes, and artifacts.

Restoration must improve comprehension without making voices artificial. Back
off when processing creates metallic, bubbly, flanged, hollow, pumping,
over-de-essed, or reverb-like artifacts. Use spectral and waveform inspection to
target isolated problems before applying global processing. Use noise prints
only from genuine noise-only sections, and monitor removed signal when the tool
supports it.

Core dialogue normally stays centered. Preserve stereo, surround, or binaural
intent when it serves the format. Do not invert, remix, widen, downmix, or phase
alter channels unless correcting a documented problem or meeting a documented
delivery target.

Music, SFX, ambience, and sound design must support the current idea or emotion.
Do not add hits, whooshes, risers, drones, impacts, fake crowds, fake reactions,
or ominous beds that imply danger, guilt, scale, causality, endorsement, or
emotion unsupported by the content. For documentary, news, review, react, and
evidence-led videos, sound design cannot become an argument the facts do not
support.

Track audio-specific decisions in `AUDIO-EDITLOG.md` when audio work is
substantial. Track third-party music, stems, loops, samples, SFX, ambience,
voice models, generated music, licensed libraries, and rights evidence in
`AUDIO-SOURCE-LOG.md` or the relevant section of `SOURCE-LOG.md`. Permission,
fair use, copyright status, YouTube reused-content monetization, Content ID, and
AI/synthetic disclosure are separate checks.

For AI-generated or meaningfully AI-altered audio, review current YouTube
disclosure guidance. Do not fabricate speech, quotes, evidence, performances,
reactions, endorsements, product results, gameplay achievements, or crowd
responses. Voice cleanup, repair, captions, and non-misleading production help
still require human listening QC.

## Visual Clarity And B-Roll

Every visual element must show evidence, demonstrate action, clarify a concept,
establish place/time, show emotion/reaction, maintain continuity, compare
alternatives, orient the viewer, reinforce brand identity, or reset attention
with purpose. Avoid decorative clutter.

On-screen text must be mobile/TV readable, high contrast, inside safe areas,
concise, synced to the spoken meaning, and clear of faces, UI, products,
evidence, captions, and gameplay.

B-roll must support the current idea, not merely hide a cut. Use it to
demonstrate, prove, contextualize, orient, preserve continuity, or add relevant
sensory/emotional texture. Avoid generic stock footage that weakens credibility
or contradicts narration. Label archival, simulated, reenacted, illustrative,
or AI-generated visuals when viewers could mistake them for direct evidence.

## Animation And Motion Design System

Animation is visual communication over time, not decoration after editing. Every
animation must clarify, demonstrate, orient, compare, emphasize, transition, or
intentionally create supported emotion. Static composition and hold time are
valid choices. Do not animate every available property, object, word, cut, beat,
or layer.

Before proposing or building motion, state the animation diagnosis: primary and
hybrid format, target viewer/device, viewer intent, title/thumbnail promise,
section purpose, information density, emotional intensity, source evidence,
brand/design constraints, script/voice/captions/music/SFX, aspect ratio,
resolution, frame rate, duration, delivery format, publishing speed, whether
animation is primary or supporting, rights/privacy/factual/AI risks, and existing
framework architecture.

Use HyperFrames by default for agent-authored video animation. HyperFrames fits
this repository because current official docs describe HTML compositions,
declared timing, HTML/CSS/JavaScript authoring, seekable runtimes, framework-owned
media playback, deterministic frame-by-frame rendering, agent skills, preview,
lint/check/snapshot/render workflows, and runtime adapters including GSAP,
Lottie, CSS, Web Animations, Three.js, shaders, and custom adapters. Before
authoring HyperFrames code, load the current `/hyperframes` entry skill,
`/hyperframes-core`, `/hyperframes-animation`, `/hyperframes-creative`, and
`/hyperframes-cli` or the current installed equivalents.

Select Remotion only when documented project context makes it stronger: an
existing maintained Remotion project, React/TypeScript team standard, reusable
data-driven variants, React app integration, existing Remotion infrastructure,
required Remotion capability, or explicit user request. Before choosing Remotion,
review the current Remotion license for the intended commercial or organizational
use. Do not choose Remotion merely because React is familiar.

Framework selection output must include the recommended framework, project-tied
reasons, rejected alternative and why, required packages/skills, licensing or
deployment checks, determinism/render risks, and any migration or interoperability
plan. Do not mix HyperFrames and Remotion in one deliverable without a documented
boundary and one master timeline owner. QC rendered intermediates and final
composites separately.

Assign a motion-density level to every animation project and major section:
Level 0 static, Level 1 anchor motion, Level 2 selective support, Level 3 standard
motion system, Level 4 dense narrative motion, or Level 5 motion-first/fully
animated. Density may change by section and is never a quota. When viewers must
read, reduce competing movement. When viewers must understand a process, reveal
progressively. When emotion needs space, hold longer and simplify. Webdocs may
use coordinated multi-layer motion when every layer has a narrative role and one
dominant focus remains clear.

Anything beyond a few isolated overlays needs a storyboard or beat map before
full implementation. Complex projects should maintain `DESIGN.md`,
`STORYBOARD.md`, `SCRIPT.md` when relevant, `ANIMATION-EDITLOG.md`, and
`ANIMATION-SOURCE-LOG.md`. Every scene needs one primary message, a defined
primary/secondary/ambient motion hierarchy, readable text, source references,
transition intent, audio cue, density level, and accessibility/risk notes.

Maintain a reusable design system for multi-scene animation: canvas/backgrounds,
colors, typography, spacing, safe zones, borders/shadows/texture, icons,
illustration style, image treatment, captions, lower thirds, chart/map language,
motion tokens, easing families, entrances/exits, transitions, camera language,
SFX relationship, reduced-motion alternatives, examples, and anti-examples. Use
existing brand assets and the active provider's `providers/<provider>/DESIGN.md`
(when declared in `avo.project.json` / `providers/<provider>/avo.provider.json`);
never invent brand values when reliable assets exist.

Every animated element needs a lifecycle: pre-entry state, entrance, readable
hold or active state, and exit or transition. Time motion to narration, music,
causality, and reading speed. Let viewers see starting and ending states when
comparison matters. Avoid cutting before motion resolves unless the next shot
continues the movement intentionally. Use easing to express weight, confidence,
softness, urgency, mechanical precision, or playfulness. Use linear movement only
for genuinely constant processes such as progress, scanning, rotation, or data
movement.

Data, maps, documents, UI, product visuals, photographs, and archival media must
preserve factual meaning. Keep values, units, baselines, labels, geography,
dates, product behavior, source context, and attribution accurate. Label archive,
reenactment, simulation, illustration, and AI-generated media when viewers could
mistake it for direct evidence. Do not animate evidence in a way that creates
false causality, chronology, motion, certainty, endorsement, or product behavior.

All final animation must be deterministic, seekable, reproducible, and
render-safe. Avoid wall-clock timing, unseeded randomness, network requests
during render, unawaited assets, hidden global state, browser-only clocks, and
animations that cannot seek to arbitrary frames. Freeze external data, generated
assets, screenshots, API responses, and model outputs before final render unless
the framework provides a controlled deterministic adapter.

For browser-based animation, prefer transform and opacity when the same result is
possible. Avoid unnecessary layout/paint work, expensive blur/filter/shadow/mask,
excessive shader or 3D cost, and blanket layer promotion. Test complex scenes at
final resolution and frame rate. Performance optimization must not break
determinism, visual fidelity, accessibility, or factual correctness.

Animation accessibility is release-blocking. Keep text high-contrast, readable,
inside safe areas, and visible long enough. Captions remain accessibility elements
first and must not be obscured. Do not encode essential meaning only through
motion or color. Avoid flashing more than three times in one second, rapid
full-screen luminance changes, intense red flashes, prolonged shake, extreme zoom,
or large-field motion without a clear reason. Provide reduced-motion alternatives
or design modes when the project context supports them.

Track animation sources in `ANIMATION-SOURCE-LOG.md`: brand assets, fonts,
footage, screenshots, data, documents, icons, illustrations, Lottie, models,
shaders, textures, generated assets, AI tool/model/prompt reference when
relevant, music/SFX, factual sources, licenses, attribution, restrictions, and
replacement status. AI-assisted animation must remain inspectable, editable,
source-controlled, and human-reviewed. Do not fabricate data, interfaces, maps,
documents, quotes, historical evidence, brand claims, likenesses, voices, or
realistic events.

Use immutable animation versions such as `project-animation-v001-board`,
`project-animation-v002-layout`, `project-animation-v003-motion-pass`,
`project-animation-v004-review`, `project-animation-v005-render-candidate`, and
`project-animation-v006-master`. Do not use `final-final` or overwrite approved
renders. For code-based animation, link generated renders to the source revision
or documented source snapshot.

Use animation review gates when applicable: brief/framework selection, design
system approval, storyboard/motion-density approval, static layout/typography,
first motion pass, timing/hierarchy review, audio synchronization,
accessibility/source review, render-candidate QC, and master approval. Do not
invest in high-cost shaders, 3D, particles, or detailed secondary motion before
message, storyboard, layout, and typography are approved.

Before delivery, verify framework choice, scene objective, density, hierarchy,
text, captions, evidence, entrances/holds/exits, fonts/assets, seeded randomness,
preview/render parity, audio sync, flashing safety, rights/AI disclosure,
resolution, aspect ratio, frame rate, codec, alpha/color assumptions, first/final
frames, file naming, and delivery manifest.

## Pacing And Truthful Compression

Pacing is the rate of meaningful information, emotion, or visual change, not
cuts per minute. Evaluate pacing by format, audience familiarity, complexity,
performance energy, emotional tone, visual novelty, search intent, stakes, and
need for reflection.

Cut to remove friction, not humanity. Preserve pauses that communicate thought,
comedy, tension, sincerity, grief, surprise, uncertainty, or emphasis.

Time compression and reordering are allowed only when they improve clarity and
do not create a false sequence, cause, reaction, or conclusion. When chronology
matters, preserve it or disclose restructuring.

## Captions And Accessibility

Every final video needs a caption plan. Correct auto-captions when practical;
verify names, technical terms, locations, products, and specialist vocabulary;
identify speakers when needed; include meaningful non-speech audio; avoid
burned captions when selectable captions are better; ensure open text does not
conflict with YouTube captions; use color-blind-safe graphics; avoid excessive
flashing; and leave enough time to read diagrams, rankings, maps, and specs.

Every delivered final or master video also needs a fresh transcript generated
from the final exported file itself, not only from the source footage, rough/fine
exports, or EDL-derived captions. Store final-file transcript artifacts under
the footage `edit/transcripts/` directory using the final/master basename and
reference them in the delivery manifest.

## Rights, Licensing, Sources, And Reused Content

Never assume online material is free to use. Track every third-party asset in
`SOURCE-LOG.md`: description, rights holder, link/path, access date, license or
permission basis, attribution, platform/territory/duration limits, modification
restrictions, timecode, evidence location, and risk notes.

Distinguish copyright permission, license terms, fair use/fair dealing analysis,
and YouTube reused-content monetization risk. Permission or fair-use arguments
do not automatically satisfy YouTube reused-content monetization rules.

For clips, reactions, compilations, news footage, podcasts, game footage, and
music, keep the original contribution unmistakable, use only what is needed,
avoid long uninterrupted third-party segments, preserve source context, and do
not treat cropping, mirroring, speed changes, borders, filters, or subtitles as
meaningful transformation.

Escalate material legal uncertainty for human/legal review.

## Disclosure, AI, Privacy, And Safety

Preserve clear disclosure for sponsorships, affiliates, gifted products,
loaned products, review units, conflicts of interest, and paid promotion. Do
not bury material relationships after the recommendation. Keep YouTube paid
promotion settings and local disclosure rules in the upload checklist. For
Brazil-facing publication, escalate Brazilian CONAR disclosure questions for
human review.

Track AI-generated and AI-altered assets in `SOURCE-LOG.md`. Realistic AI or
meaningfully altered content that could mislead viewers about real people,
places, events, statements, or scenes requires current YouTube disclosure review
and editorial labeling when necessary. Never use AI to fabricate evidence,
quotes, reactions, product results, gameplay achievements, news events,
documentary scenes, or endorsements.

Identify and remove or obscure private information: addresses, phones, email,
credentials, finances, license plates when relevant, protected faces, computer
notifications, browser tabs, messages, client data, minors' identifiers,
confidential documents, and embargoed product information.

Do not intensify or glorify dangerous behavior, harassment, humiliation,
doxxing, vigilante action, distress to minors/vulnerable people, fake
emergencies, fake violence, or serious imitation risk. Add context or warnings
only when legitimate educational/documentary coverage requires them.

## News, Documentary, And Evidence Integrity

Accuracy beats speed. Distinguish confirmed facts, analysis, allegations,
estimates, and unknowns. Preserve dates, locations, source context, and fair
quote meaning. Label archive/file footage, reenactments, simulations,
illustrations, and generated visuals. Do not use music, sound design, slow
motion, grade, or juxtaposition to imply guilt, intent, danger, or causality
unsupported by evidence. Add transparent corrections when material errors are
found.

## Project Organization

Inspect and preserve the existing structure. If no sensible structure exists,
separate admin, script/research, source media, project files, graphics, music
and SFX, proxies/cache, review exports, masters, captions, thumbnails,
rights evidence, and docs. Never put disposable cache/proxies in master folders.
All AVO session outputs belong under the footage directory's `edit/`,
not inside this repo unless this repo is the actual footage project.

## Editorial Versioning And EDITLOG

Use immutable sequential editorial versions:

```text
YYYYMMDD-video-slug-stage-v001
```

Never use `final-final`, `final2`, or ambiguous names. Never overwrite an
approved review export. Increment the version for every externally reviewed
export. Duplicate timelines before major structural changes. Record reviewer,
date, status, major changes, open issues, and approvals in `EDITLOG.md`.

Do not call a sequence `picture-lock` until the user explicitly confirms no
further picture changes. Do not call an export `master` until all required QC
has passed.

## Review Gates

Use these gates when applicable:

1. Editorial diagnosis approved.
2. Assembly approved.
3. Rough cut approved.
4. Fine cut approved.
5. Picture lock approved.
6. Audio and color approved.
7. Captions and rights approved.
8. Master QC passed.

Do not skip to polish while structure is unresolved.

## Master QC And Delivery

Every master must pass editorial, audio, visual, caption, rights/policy, and
technical QC. Verify the title/thumbnail promise, meaning preservation, facts,
disclosures, intelligible audio, no clipping/sync drift/pops, readable visuals,
safe margins, labels, redactions, caption accuracy, source-log completeness,
made-for-kids and AI disclosure status, safety/privacy/harassment review,
resolution/aspect/frame-rate correctness, progressive output, 48 kHz audio for
standard YouTube masters, no unintended letterboxing/pillarboxing, clean start
and end, thumbnail candidates, end-screen space, and chapter/caption timing
from the approved master.

Use current YouTube upload documentation as the source of truth. Do not hardcode
old bitrate recommendations without checking the official upload-encoding page.

For audio delivery, record the measurement standard and settings used, such as
ITU-R BS.1770/EBU R 128-style integrated loudness, loudness range, momentary or
short-term loudness when useful, and true peak. Measure the final approved
program and re-check the encoded upload candidate because codec/export changes
can affect peaks. Treat `LUFS`/`LKFS`, `LU`, and `dBTP` as different units.

## Available Editing Skills

- `youtube-format-selection`: diagnose format, viewer promise, pacing density,
  risks, and playbook combination.
- `youtube-format-playbooks`: apply the 19 YouTube format playbooks.
- `retention-diagnostics`: evaluate pre-publish structure and post-publish
  analytics without overfitting one metric.
- `audio-post-production`: handle sync, cleanup, mix hierarchy, loudness,
  device checks, and export verification.
- `audio-intake-and-diagnosis`: inventory sources, diagnose risks, and choose
  the audio workflow before editing.
- `dialogue-editing-and-restoration`: clean and match speech while preserving
  natural performance and meaning.
- `music-sfx-and-ambience-mix`: build truthful mix hierarchy for music, effects,
  source audio, and ambience.
- `cinematic-sound-design`: design cinematic sound without manufacturing
  unsupported emotion, evidence, or causality.
- `youtube-audio-format-playbooks`: apply audio priorities for 19 YouTube
  formats and hybrid sections.
- `loudness-and-audio-delivery-qc`: measure loudness/true peak and verify final
  audio exports against documented targets.
- `rights-source-audit`: inventory sources, permissions, disclosure, reused
  content, privacy, and policy risks.
- `final-qc-delivery`: run final pass/fail QC, naming, edit log, and delivery
  manifest.
- `animation-intake-and-framework-selection`: diagnose format, message, density,
  source material, risks, and framework choice.
- `hyperframes-video-animation`: apply local HyperFrames-first policy while
  delegating mechanics to current official HyperFrames skills.
- `remotion-video-animation`: use Remotion only when justified by project context,
  license review, and deterministic React composition needs.
- `motion-design-system`: create or maintain animation design systems and motion
  tokens.
- `animation-storyboard-and-density`: convert briefs/scripts into scenes,
  hierarchy, density, source, and approval plans.
- `youtube-animation-format-playbooks`: apply 19 format-specific motion playbooks
  and hybrid section guidance.
- `animation-validation-and-render-qc`: validate static frames, timing,
  accessibility, determinism, snapshots, render parity, and delivery.
- `caveman`: compressed response style for lower output tokens while preserving
  exact technical content.

**Software foundation skills** (on-demand, orchestrator code):

- `design-pattern-selection`: diagnose before Strategy, Observer, Facade, Decorator,
  Adapter, or Singleton
- `architecture-selection`: diagnose before Hexagonal vs Clean Architecture structure

Branch policy, TDD, SemVer/changelog, and documentation are always-on **rules** — not skills.

<!-- avo:orchestrator:start -->
## AVO Orchestrator Operating Rules

This section governs the driving agent (Cursor / Claude Code / Codex) when it
operates AVO — AI Video Orchestrator. It **adds** to the canonical rules above
and MUST NOT weaken or contradict them. Editorial-intent, rights, safety,
audio-first, accessibility, versioning, and QC rules always take precedence. The
full mechanics live in [`docs/avo-workflow.md`](docs/avo-workflow.md).

### Weekly update check

At session start, check whether the user's AVO install is up to date:

1. Read `lastUpdateCheck` from `.avo/state.json` (gitignored). If the file or
   field is absent, treat it as never-checked.
2. If the last check was **≥ 7 days ago** (or never), run `git fetch` and compare
   the local branch to its upstream (or `npm run check-update` for the same advisory).
3. If updates exist, tell the user in plain language and suggest **`/avo.update`**
   (or `/avo.update yes` to apply). **Do not** paste npm/git commands unless they
   ask for manual control. When they confirm, run the update yourself per
   [`commands/avo/update.md`](commands/avo/update.md).
4. If the working tree is **dirty**, or the machine is **offline**, warn and
   skip — **never clobber, stash-discard, or force** local changes.
5. Rewrite `lastUpdateCheck` to the current timestamp after the check completes,
   whether or not a pull happened.
6. This check is advisory maintenance; it must never block or delay the user's
   actual editing request.

**Provider safety:** `/avo.update` snapshots gitignored `providers/<slug>/`
workspaces before pull/sync and verifies manifests after. Never delete or
overwrite user provider directories during update.

### Provider + inputs declaration (project start)

Before running any stage of a video project, require these declarations and do
not proceed with an empty raw folder:

- **Provider.** The provider name (a YouTube channel / TikTok account /
  Instagram profile / …). It resolves to `providers/<name>/avo.provider.json`
  for brand, design, routing overrides, and the default transcription language.
  Self-learning is scoped to this provider. To **create or configure** a provider,
  load skill **`avo-provider`** or `/avo.provider`; see [`docs/providers.md`](docs/providers.md).
- **Raw-files folder (`rawDir`).** The folder of raw footage. **This folder is
  the workflow root — all work happens there, inside its `edit/` subtree, never
  inside the AVO repo.** When planning with SpecKit, **explicitly tell SpecKit
  that this raw folder is where the workflow runs.**
- **Asset locations.** The locations of any **SFX, music, inserts, assets, and
  logos** to use. Record them as **paths only** in the per-video
  `avo.project.json` (`assets: { sfx, music, inserts, graphics, logos }`); media
  stays external and gitignored.

Resolve the per-video `avo.project.json` on top of the provider manifest so
brand + external roots + routing + language are all determined before work.

**Provider design resolution.** From the declared `provider` field, load:

- `providers/<provider>/DESIGN.md` — canonical brand/motion design (scaffold:
  `providers/_template/DESIGN.md`)
- `providers/<provider>/brand/palette.json` and
  `providers/<provider>/brand/references/` — palette and reference assets

Do not assume a design file at repo root. Bishop is an in-repo example provider
only.

### Telemetry & hardware advisory expectations

- **Telemetry every phase.** At each phase boundary, report free disk on the
  editing volume, bytes the step created, cumulative project footprint, phase
  N-of-total + percent, and a **rough** ETA (labelled as an estimate). Emit both
  a human line and a machine-readable JSON line. Roll stats into `.avo/state.json`
  (no secrets). The post-render learndown additionally reports **space used vs
  space freed** and the preserved-set size.
- **Hardware advisory (render/watch phases).** Surface the user's CPU + GPU (and
  RAM/disk) and a suitability check, then **recommend a model tier in prose**
  (e.g. "for your CPU/GPU I used `qwen-<x>` + `faster-whisper-<y>`; a
  better/worse option is …"). The advisory is **advisory only — it never
  blocks** the run, and the user can override the tier at any time.

### Confidence gate, THE LOOP, human approval, and cleanup (summary)

- Work cheaply first: prove edits at ≈360p and motion at ≈720p, gate on
  watch-skill confidence, and promote to 1080p / source resolution only when
  confident **and the user has explicitly approved** (see below). **Never render
  above the source resolution** (backlog).
- The watch-skill LOOP (inspect → fix → verify) gates internal re-proof loops but
  never fabricates content and never overrides editorial rules above.
- **Human approval gate (blocking).** After each watch-skill LOOP pass **and** agent
  transcription analysis for that stage, the agent MUST stop, point the user at
  files under `<rawDir>/edit/preview/` and `<rawDir>/edit/review/`, fill
  `approval-gate.md` from [`docs/templates/review/approval-gate-manifest.md`](docs/templates/review/approval-gate-manifest.md),
  and wait for explicit approval before promoting resolution, advancing stages, or
  running cleanup. watch-skill high confidence alone is **not** approval.
- Post-render, keep **only**: the raw file, the initial transcript, the final
  transcript (generated from the final master), and the final master. Delete all
  other run-created files with a cross-platform delete (`rimraf`). This
  preserved-set invariant is release-blocking.

### ai-jail sandbox (optional)

Running the driving agent inside [ai-jail](https://github.com/akitaonrails/ai-jail)
is **optional and opt-in** (`--with-jail` at setup). **Linux and macOS run ai-jail
natively; on Windows use WSL2** (no native Windows sandbox backend). When used,
mask `.env` and map the external media root read-write. Operator guide:
[`docs/ai-memory-and-ai-jail.md`](docs/ai-memory-and-ai-jail.md). ai-jail does not
weaken AVO's own secret handling, and AVO must run fully without it.

### Engine vs upstream (hybrid model)

- **AVO** = orchestrator; **avo-engine** = bundled `src/avo/` (Gate 1 id `avo-engine`; `helpers/` shims until v0.2.0).
- Before editing engine code, read
  [`specs/upstream-diffs/video-use/LATEST.json`](specs/upstream-diffs/video-use/LATEST.json)
  when present, then the linked `summary.md`. See [`docs/adapters.md`](docs/adapters.md).
- Run jobs via `python -m avo.adapters.run_job <job> --label local|paid -- …`.

### Model transparency

- Read active models: `python -m avo.models_cli show` or phase telemetry `activeModels`.
- Before changing tiers, run `python -m avo.models_cli alternatives <job>` and disclose
  VRAM/disk/speed/quality tradeoffs. See [`docs/model-transparency.md`](docs/model-transparency.md).
- Canonical prose shape matches `docs/avo-workflow.md` §6 — use catalog data, do not invent tier names.
<!-- avo:orchestrator:end -->


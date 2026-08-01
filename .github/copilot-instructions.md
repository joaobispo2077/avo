# Copilot Instructions

Follow `AGENTS.md` as the canonical rulebook. Agent-specific files must not
contradict it.

## Software foundation (orchestrator code)

- **Branches:** User owns branches. Never checkout/switch/create/delete branches.
- **Behavior:** Change behavior only when explicitly requested. Small focused diffs.
- **Testing:** TDD / Test Trophy — unit tests first (`pytest`; `pip install -e ".[dev]"`).
- **Principles:** KISS, DRY, YAGNI, SOLID when useful, low coupling, high cohesion.
- **SemVer:** `CHANGELOG.md` + `v*` tags — update changelog only when user confirms done;
  recommend tag commands; never push tags unless asked. See `docs/versioning.md`.
- **Docs:** User-requested notes under `./docs/` (Markdown, kebab-case).
- **Patterns/architecture:** Only when needed — skills `design-pattern-selection`,
  `architecture-selection`.

## Token tools

- Use Caveman mode when the user explicitly asks for `/caveman`, "caveman mode",
  "talk like caveman", "less tokens", or "be brief". Keep technical content,
  code, commands, paths, API names, and quoted errors exact.
- Use RTK for noisy shell commands when possible: `rtk git status`,
  `rtk git diff`, `rtk npm test`, `rtk pytest -q`. Use `rtk proxy <cmd>` when
  raw output is needed. Verify with `rtk gain` if RTK setup is in doubt.

## AVO / video editorial (footage work)

- Diagnose the video format, viewer intent, title/thumbnail promise, emotional
  arc, information density, traffic context, and rights/policy risks before
  recommending pacing, graphics, transitions, music, B-roll, or effects.
- Preserve creator meaning, chronology, context, tone, factual claims, and
  commercial disclosures. Do not manufacture reactions, certainty, causality, or
  conflict.
- Improve retention through clarity, curiosity, progression, and value; never
  through misleading hooks or empty stimulation.
- Prioritize intelligible audio, purposeful visuals, mobile/TV-readable text,
  accurate captions, and accessibility.
- For animation work, diagnose format, viewer intent, section purpose,
  motion-density level, source evidence, brand constraints, delivery specs, and
  framework context before implementation.
- Prefer HyperFrames for agent-authored animation. Use Remotion only for
  documented React/data-driven/existing-stack advantages or explicit user
  request, and review the current Remotion license first.
- Every animation must communicate a purpose, preserve factual meaning, stay
  deterministic/seekable, use seeded randomness, await fonts/assets, and pass
  snapshot/render QC.
- Maintain `DESIGN.md`, `STORYBOARD.md`, `ANIMATION-EDITLOG.md`, and
  `ANIMATION-SOURCE-LOG.md` for multi-scene or reviewed animation work.
- For audio work, diagnose sources first, sync before creative cutting,
  gain-stage before restoration/compression, clean conservatively, document the
  channel loudness target, and QC after encode.
- Maintain `SOURCE-LOG.md`, disclosure review, AI disclosure review,
  made-for-kids review, privacy/consent review, and safety/platform-policy
  escalation.
- Track substantial audio work in `AUDIO-EDITLOG.md` and third-party/generated
  music, SFX, samples, loops, stems, ambience, and voice assets in
  `AUDIO-SOURCE-LOG.md` or `SOURCE-LOG.md`.
- Use immutable version naming for **video exports**, `EDITLOG.md`, review gates,
  and full master QC. Orchestrator **software** uses SemVer — see `CHANGELOG.md`.
- Use editing skills listed in `AGENTS.md` for footage workflows.

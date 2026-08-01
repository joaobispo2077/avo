---
applyTo: "**"
---

# HyperFrames Authoring Instructions

- HyperFrames is the default framework for agent-authored animation in this repo.
- Before writing composition HTML, load the current official HyperFrames entry,
  core, animation, creative, and CLI skills or their installed equivalents.
- Use current upstream docs for commands. At research time, common commands
  included `npx hyperframes skills update`, `npx hyperframes lint`,
  `npx hyperframes check`, `npx hyperframes snapshot --at <times>`, and
  `npx hyperframes render --output <file>.mp4`.
- Treat compositions as timed HTML documents. Use declared composition IDs,
  dimensions, clip timing, tracks, nested composition boundaries, and stable IDs.
- Let HyperFrames own media playback. Do not manually play, pause, seek, or time
  media outside the framework contract.
- Use seekable GSAP timelines or supported runtime adapters. Avoid hidden global
  state, wall-clock timing, unseeded randomness, and async timeline setup.
- Keep CSS layout as the resting-state source of truth; use from-to animation
  only when nested state or ambiguity requires it.
- Run lint, check, important-time snapshots, draft/review/final renders, and
  `doctor` when environment issues are suspected.

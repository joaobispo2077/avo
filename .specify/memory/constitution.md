<!--
Sync Impact Report
Version change: template -> 1.0.0
Modified principles:
- Template principle 1 -> I. Editorial Truth And Viewer Promise
- Template principle 2 -> II. Format Diagnosis Before Style
- Template principle 3 -> III. Audio, Visual, And Accessibility Quality
- Template principle 4 -> IV. Rights, Disclosure, Safety, And Privacy
- Template principle 5 -> V. Versioning, Review Gates, And QC
Added sections:
- Operational Standards
- Development Workflow And Review Gates
Removed sections:
- Placeholder SECTION_2_NAME and SECTION_3_NAME content
Templates requiring updates:
- ✅ .specify/templates/plan-template.md
- ✅ .specify/templates/spec-template.md
- ✅ .specify/templates/tasks-template.md
- ✅ .opencode/commands/speckit.*.md checked; no updates required
- ✅ .agents/skills/speckit-*/SKILL.md checked; no updates required
- ✅ .chatgpt/commands/speckit.*.md checked; no updates required
Follow-up TODOs:
- None
-->

# AVO Constitution

## Core Principles

### I. Editorial Truth And Viewer Promise

Every edit MUST preserve the creator's intended meaning, chronology, tone,
factual claims, product assessment, and material disclosures unless the user
explicitly approves a change. The title and thumbnail are an editorial contract:
the opening, structure, and conclusion MUST honestly pay off their promise.

Rationale: Retention, style, and speed have no value if they mislead the viewer
or distort the creator's message.

### II. Format Diagnosis Before Style

Every video workflow MUST diagnose the primary format, secondary/hybrid formats,
viewer intent, traffic posture, source limitations, emotional arc, information
density, and rights/policy risks before recommending pacing, graphics, music,
transitions, B-roll, subtitles, or effects.

Rationale: There is no universal YouTube editing style; the right density and
visual language depend on format, promise, audience, and material.

### III. Audio, Visual, And Accessibility Quality

Speech intelligibility MUST be protected for speech-led formats. Visuals,
B-roll, graphics, captions, color, and motion MUST improve evidence,
comprehension, orientation, accessibility, emotion, or brand clarity. Decorative
clutter, unreadable text, hidden captions, and audio that masks speech are
constitution violations.

Rationale: Viewers cannot value an edit they cannot understand, read, hear, or
trust.

### IV. Rights, Disclosure, Safety, And Privacy

Every third-party source, AI-generated or AI-altered asset, sponsorship,
affiliate relationship, review unit, license, permission, and unresolved rights
question MUST be tracked in `SOURCE-LOG.md` before final delivery. Privacy,
consent, minors, harmful/dangerous content, harassment, made-for-kids status,
advertiser-friendly risks, reused-content risks, and required disclosures MUST
be reviewed and escalated when uncertain.

Rationale: A technically strong edit is not publishable if it violates rights,
misleads about commercial relationships, endangers people, or exposes private
information.

### V. Versioning, Review Gates, And QC

Editorial exports MUST use immutable sequential version names and meaningful
changes MUST be recorded in `EDITLOG.md`. Picture lock requires explicit user
approval. A master may be named or delivered only after editorial, audio,
visual, caption, rights/policy, and technical QC pass.

Rationale: Video work is iterative and review-driven; clear versioning and QC
prevent accidental overwrites, premature delivery, and ambiguous approvals.

## Operational Standards

- `AGENTS.md` is the canonical runtime rulebook for all agents.
- Agent-specific guidance files MAY summarize these rules but MUST NOT
  contradict them.
- The six editing skills are repeatable workflows, not optional replacements for
  always-on rules: `youtube-format-selection`, `youtube-format-playbooks`,
  `retention-diagnostics`, `audio-post-production`, `rights-source-audit`, and
  `final-qc-delivery`.
- Generated AVO editing outputs belong under the footage directory's
  `edit/` folder unless this repository is itself the footage project.
- Current YouTube documentation is the source of truth for upload specifications,
  captions, end screens, made-for-kids features, AI disclosure, paid promotion,
  advertiser-friendly guidance, and platform policy.

## Development Workflow And Review Gates

All feature specs, plans, tasks, and editing sessions MUST account for the
following when relevant:

- Format diagnosis and viewer promise.
- Source preservation and non-destructive workflow.
- Transcript/story map before detailed polish.
- Audio-first edit and technical verification.
- Visual clarity, B-roll purpose, caption/accessibility plan.
- Rights/source audit and disclosure review.
- Privacy, consent, safety, and policy review.
- Review gates: diagnosis, assembly, rough cut, fine cut, picture lock,
  audio/color, captions/rights, and master QC.
- Immutable version naming and `EDITLOG.md` updates.

The workflow MUST stop for human review when legal, policy, safety, privacy,
defamation, sponsorship, or factual uncertainty is material.

## Governance

This constitution supersedes conflicting repository practice for AI-assisted
YouTube video editing work. Amendments MUST update this file, include a Sync
Impact Report, and propagate any principle changes to `AGENTS.md`, agent rule
files, Spec Kit templates, skills, and documentation when affected.

Versioning follows semantic versioning:

- MAJOR for removed or redefined principles that change governance expectations.
- MINOR for added principles, new mandatory sections, or materially expanded
  governance.
- PATCH for clarifications and non-semantic wording changes.

Compliance review is required at every Spec Kit plan, task, implementation,
analysis, convergence, and final delivery step. Constitution violations are
blocking until fixed or explicitly amended through this governance process.

**Version**: 1.0.0 | **Ratified**: 2026-07-19 | **Last Amended**: 2026-07-19

# /avo.sound create reference

## Step/state mapping

**Durable state:** pipeline-run.json plus the current canonical timeline revision

**Workflow steps:** Validate sound prerequisites → Run sound → Verify and report the sound result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified sound completion

**Valid next commands:** /avo.watch or /avo.audio-qc

Creative sound design brief. Follow [`cinematic-sound-design`](../../../.claude/skills/cinematic-sound-design/SKILL.md) doctrine when available: support comprehension, never manufacture false emotion or evidence.

## Usage pattern

```text
/avo.sound create
Provider: my-channel
rawDir: /path/to/footage
destination: /path/to/out/hit.wav
NS2-style whoosh for scene transition at 2:14, subtle, no horror implication
```

## Rules

1. Describe effect in plain language (duration, intensity, purpose).
2. Prefer licensed libraries or synthesized SFX; log sources in `AUDIO-SOURCE-LOG.md`.
3. Do not imply danger, guilt, or scale the footage does not support (documentary/news restraint).
4. Export to `destination`; user approves before inserting into mix.

## NS2 note

“NS2-style” means cinematic, velocity-matched, purposeful SFX per project sound-design vocabulary, not a specific proprietary plugin requirement.

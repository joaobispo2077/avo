# /avo.sound create reference

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

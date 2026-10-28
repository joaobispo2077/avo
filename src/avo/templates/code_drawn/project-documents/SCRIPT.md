# Script and measured cues

**Status:** Draft. Generic starter; narration/music are not implied.

## Purpose and audio scope

- Viewer and promised payoff: {{describe}}
- Scene message / format: {{describe}}
- Audio mode: {{silent / narration-led / music-led / source-sound-led}}
- Narration: {{local asset/reference or N/A: intentionally silent}}
- Music / effects: {{local asset references or N/A}}
- Caption language and terminology: {{declare or N/A}}
- Canonical timing owner: {{BMap/Tracks/Sync Map references or standalone plan}}

Keep factual claims and source quotations faithful. Do not invent dialogue,
product behavior, metrics, performance or evidence to fit a motion cue.
An empty transcript is an observed result/scope decision, not a fabricated pass.

## Spoken or displayed content

| Scene / canonical cue | Exact approved wording or N/A | Source / claim reference | Readable hold / rationale | Caption treatment |
| --- | --- | --- | --- | --- |
| {{id}} | {{text or N/A}} | {{reference}} | {{declared range and reading intent}} | {{treatment or N/A}} |

CMap/BMap own editorial/cue timing and Tracks own resolved placement/audio in a
footage pipeline. This document records the intent; it does not move approved
cuts, replace canonical cue ranges or create a second audio timeline.

## Measured cue log

| Cue | Audio asset path + SHA-256 | Asset-local sample/time | Program frame / canonical mapping | Event and confidence | Uncertainty / confirmation evidence |
| --- | --- | --- | --- | --- | --- |
| {{id or N/A}} | {{actual frozen file}} | {{actual location/rate}} | {{actual mapping}} | {{phrase/onset/beat/verified downbeat; measured/estimated}} | {{tolerance, listening/waveform evidence or unresolved issue}} |

Do not assume every fourth detected beat is a downbeat. Confirm meter and bar
position or mark uncertainty. Preserve speech and necessary reading holds
instead of forcing a visual-change or sound-effect quota.

## Optional generated narration or synthesized sound

- Requested purpose and authorization/reference: {{reference or N/A}}
- Tool/model/version, prompt or synthesis parameters and seed: {{actual or N/A}}
- Frozen output, SHA-256, rate/channels/duration: {{actual or not generated}}
- Source rights, consent and disclosure decision: {{source-log reference or pending}}
- Listening / intelligibility review: {{evidence and status or pending}}
- Existing media/Tracks placement: {{reference or not placed}}

Generate sound to an ordinary local asset before use. Browser drawing capture
stays silent; canonical mix, source synchronization, levels and channel intent
remain owned by the existing audio pipeline.

## Open questions and revisions

| Item | Owner | Impact on timing/meaning | Resolution reference |
| --- | --- | --- | --- |
| {{question or none assessed}} | {{owner}} | {{impact}} | {{pending / evidence}} |

Record decisions in ANIMATION-EDITLOG.md and source/license details in
ANIMATION-SOURCE-LOG.md. Human review remains pending until the existing gate
records the user's explicit decision.

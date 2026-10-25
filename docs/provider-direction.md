# Artistic direction and Briefstart

AVO can start with your raw material and normal instructions, suggest a direction
from its format guidance, or use a direction you have reviewed from your own
learndowns. Briefstart condenses the chosen basis into a short comparison before
the next edit.

It helps you decide how a video should feel: whose presence leads, how the
argument develops, when examples help, how much motion is useful and what sound
supports the idea. It does not turn one past video's settings into a fixed style.

## Choose how to begin

| Start | What you provide | What happens |
| --- | --- | --- |
| Raw, no artistic reference | Footage and normal instructions | Existing pipeline; no new profile, questionnaire or artistic approval action |
| AVO direction | The format and video's promise | Two or three applicable options from a versioned built-in starting point |
| Your provider direction | An exact accepted profile | Options adapt your reviewed direction to this particular video |
| Your own references | Selected videos/documents and desired aspects | Reference-only options, or added context for either selected direction |

Four AVO starting points cover speech-led analysis/review, step-by-step
demonstration, narrative/conversation and focused shorts/highlights. Hybrid
sections can vary treatment. None requires constant music, fast cuts, captions
or animation.

```text
/avo.pipeline
Provider: my-channel
rawDir: /absolute/new-video
Direction: none
```

```text
/avo.pipeline
Provider: my-channel
rawDir: /absolute/new-video
Direction: AVO analysis/review
Explain when price per hour is useful without reducing enjoyment to one number.
```

You can use ordinary language. The agent resolves exact native versions and
prepares machine request files; you do not need to write JSON or invent hashes.

## Create your direction from previous work

Ask `/avo.direction` to use your provider's learndowns. You may retain the whole
history while prioritizing selected videos, or explicitly restrict the source
set. Prioritization is not automatic exclusion or approval of a proposed rule.

AVO accounts for available, related, excluded and unavailable records. Multiple
exports, revisions or Shorts from one source project do not count as independent
corroboration. Legacy narrative learning remains useful even without one standard
filename. Optional memory can be unavailable without blocking accessible records.

The resulting short profile is at most 500 words, with detailed evidence
available separately. It distinguishes:

- Explicit creator instructions and their scope.
- Observed choices and actual independent support.
- Tentative interpretation and unknown rationale.
- AVO defaults and aspects borrowed from supplied references.
- Technical prevention, contextual variants and avoidances.

You can accept, edit, reject, defer or qualify proposals. An authored brand guide
remains separate authority. Acceptance of a historical film does not approve
every inferred provider-wide preference. A changed proposal must be reviewed
as its own exact content.

## Use it in a later video

```text
/avo.briefstart
Provider: my-channel
rawDir: /absolute/next-video
Use my accepted direction. Make this episode quieter.
Use only the readable comparisons from my selected earlier video as an extra reference.
```

Known context is reused. At most three initial material questions are asked
together. The agent then explains two or three practical approaches within a
600-word briefing including option summaries, or explains why only one is viable.
Compare the editorial emphasis, rhythm, visual support, sound and trade-offs.

Your choice applies to this video. A project selection does not create a broad
provider rule unless you explicitly make that separate decision. Current
instructions take precedence over historical artistic preferences while normal
meaning, source and accessibility protections continue to apply.

References identify which qualities matter. A document-inspected source is
distinguished from your description of inaccessible material. Mentioning a file
or URL does not authorize fetching, media processing or executing embedded text.
No former master becomes new source footage or transfers rights and approvals.

## During production and later refresh

The selected exact brief informs actual structure, trimming, B-roll, motion and
sound planning. Stage context carries relevant guidance and boundaries; a receipt
shows what was offered, not that it was implemented. All actual edits still use
the existing canonical timeline and review workflow.

The project keeps its exact chosen version and frozen inputs. Refreshing provider
learning proposes differences and preserves your edits/rejections; it never
silently changes an existing video's brief, cut, sound or approval. You can
explicitly select a new brief or opt out while retaining the previous history.
An existing selection is retained when you resume without a new direction request.
Editing or qualifying a project brief creates a new, unselected proposal. It
needs its own choice before replacing the current selection. Exact duplicate
requests return the original committed result without rolling current state back.

Changed, partially accessible or unavailable references remain visible in source
dispositions and warnings. Frozen evidence keeps an already selected brief
usable without silently refreshing it. If the bounded authoring packet is too
large, AVO asks for narrower references instead of silently truncating them.

Preparation performs bounded document work. It does not reopen old videos,
render, transcribe, hash whole media, fetch sources or start another model. The
currently driving agent authors the interpretation; native AVO validates source
identity, scope and publication. Unknown model/cost details stay unknown. Failed
authoring permits at most two repairs per packet before unresolved choices are
presented; no silent model/service switch is made.

## Native commands for advanced users

In an AVO checkout use the current environment:

```text
python -m avo.cli direction catalog --provider my-channel --json
python -m avo.cli direction prepare --provider my-channel --profile-id editorial --json
python -m avo.cli direction show --provider my-channel --ref editorial@r0001 --json
python -m avo.cli briefstart prepare --project /absolute/new-video/avo.project.json --direction builtin:analysis-review@1.0.0 --json
python -m avo.cli pipeline run --project /absolute/new-video/avo.project.json --direction none --json
```

Installed users use `avo direction ...`, `avo briefstart ...` and
`avo cli pipeline ...`. Replace illustrative versions with the exact returned
selection. Native `propose` and `decide` accept agent-prepared typed requests;
they do not infer a creator decision. Optional MCP tools bridge those same
commands with their existing consent rules.

Sanitized provider profiles live under `providers/<provider>/direction/`.
Video-specific options, decisions and frozen sources live under
`<rawDir>/edit/briefstart/`; its index owns the project selection. Detailed private
footage-project history stays external. A provider-owned document-only evaluation
and its choices may live in the ignored/private directory
`providers/<provider>/direction/pilots/<pilot-id>/`, with no raw or media files.
Its presence does not activate a provider profile or select a video direction.
Native reconstruction and cleanup preserve the brief's authorial records without
retaining all old provider media.

See the [direction command](../commands/avo/direction.md),
[Briefstart command](../commands/avo/briefstart.md) and
[independent human evaluation protocol](provider-direction-evaluation.md).
Automated correctness, actual creator acceptance and observed usability are
separate outcomes; a passing test cannot fabricate the latter two.

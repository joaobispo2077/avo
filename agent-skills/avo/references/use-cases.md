# Use case → skill / command map

Load **`avo`** for every session. Add **`avo-pipeline`** for pipeline work.
Add **`avo-provider`** when setting up a channel before the first video.

## Cursor slash commands

| Goal | Command |
| ---- | ------- |
| Full folder → master | `/avo.pipeline` |
| Cut + transcribe, no motion | `/avo.trim` |
| Transcribe only | `/avo.transcribe` |
| Audio sync diagnosis | `/avo.sync` |
| Mix / noise reduction | `/avo.sound` |
| HyperFrames overlays | `/avo.motion` |
| Talking-head graphic overlays | `/avo.talking-head` |
| watch-skill LOOP | `/avo.watch` |
| Scoped QC window | `/avo.audit` |
| YouTube format rules | `/avo.guidelines --youtube` |
| Shorts / TikTok | `/avo.shorts` or `/avo.guidelines --shorts` / `--tiktok` |
| Podcast clip from long-form | `/avo.podcast-clip` |
| Program trailer | `/avo.trailer` |
| YouTube chapters | `/avo.chapters` |
| Thumbnail candidates | `/avo.thumbnail` |
| End-screen checklist | `/avo.end-screen` |
| Color / evidence QC | `/avo.color` |
| Captions burn-in | `/avo.captions` + `identity:` |
| Rights audit before deliver | `/avo.rights` (optional `--early` post-trim) |
| Master loudness / true peak | `/avo.audio-qc` |
| Retention diagnosis | `/avo.retention` |
| Motion render QC | `/avo.animation-qc` |
| Master QC + manifest | `/avo.deliver` (after rights + audio-qc recommended) |
| Vertical from master | `/avo.reframe` or `/avo.shorts --from-master` |
| PR → video | `/avo.pr-video` + `ProjectDir` + `Source` |
| Changelog → video | `/avo.changelog-video` |
| Product launch video | `/avo.launch` |
| Music → video | `/avo.music-video` |
| Figma import | `/avo.figma` |
| Media catalog (BGM/SFX/logos) | `/avo.media` |
| Format diagnosis (pre-edit) | `/avo.format` |
| Framework intake (HF vs Remotion) | `/avo.framework` |
| Short motion graphic | `/avo.motion-graphics` |
| Custom HyperFrames composition | `/avo.general` |
| Remotion → HyperFrames port | `/avo.remotion-port` |
| Screencast oversized cursor | `/avo.screencast` |
| Creative grade during edit | `/avo.grade` |
| Article → explainer | `/avo.explainer` |
| Slideshow | `/avo.slideshow` |
| Create provider | `/avo.provider` |
| After master approved | `/avo.learndown` then `/avo.cleanup` |
| Command index | `/avo.help` |

## All use cases ([README § Use cases](../../../README.md#use-cases))

| Use case | Skills | Cursor |
| -------- | ------ | ------ |
| Product review + spec cards | `avo`, `avo-pipeline` | `/avo.pipeline` |
| Pet promo + logo + CTA | `avo`, `avo-pipeline`, `avo-provider` if new | `/avo.pipeline` |
| Dealer walkthrough | `avo`, `avo-pipeline` | `/avo.trim` + `/avo.motion`; Shorts: `/avo.shorts` or `/avo.reframe` |
| Game review | `avo`, `avo-pipeline` | `/avo.pipeline` |
| Tech first impression | `avo`, `avo-pipeline` | `/avo.pipeline` |
| Live pipeline demo + deep motion | `avo`, `avo-pipeline` | `/avo.pipeline` + animation-direction spec |
| Health / physio comparison | `avo`, `avo-pipeline` | `/avo.trim` or `/avo.pipeline` |
| Podcast highlight clip | `avo`, `avo-pipeline` | `/avo.podcast-clip` |
| Program trailer | `avo`, `avo-pipeline` | `/avo.trailer` |
| Interview with graphic cards | `avo`, `avo-pipeline` | `/avo.talking-head` |
| Product launch promo | `avo`, `avo-pipeline` | `/avo.launch` |
| Music visualizer | `avo`, `avo-pipeline` | `/avo.music-video` |
| Screencast tutorial | `avo`, `avo-pipeline` | `/avo.screencast` |
| Custom motion beat | `avo`, `avo-pipeline` | `/avo.general` |
| Remotion migration | `avo`, `avo-pipeline` | `/avo.remotion-port` |
| Going global (backlog) | `avo`, `avo-pipeline` | locale stub — BL-003–005 |

Install full toolchain for motion: `bash scripts/install/install.sh --full --lang en`.

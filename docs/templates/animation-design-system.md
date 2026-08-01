# Animation Design System

> **Template only.** Copy and adapt for each video project. Provider brand authority
> lives at `providers/<name>/DESIGN.md` — resolve from `avo.project.json` / the
> provider manifest.

This file defines reusable visual and motion rules for multi-scene animation.
When a project has a provider design system, `providers/<name>/DESIGN.md` is the
stronger brand authority; this file supplies production structure and motion tokens.

## Status

- Project:
- Version:
- Owner:
- Approved by:
- Last updated:
- Related files (in footage `edit/`): `STORYBOARD.md`, `ANIMATION-EDITLOG.md`,
  `ANIMATION-SOURCE-LOG.md`

## Canvas And Backgrounds

- Aspect ratios: TBD per deliverable.
- Safe zones: keep titles, captions, UI callouts, and evidence inside platform
  safe areas.
- Background system: use the provider/brief visual language; avoid decorative
  clutter behind text and evidence.

## Colors

| Role | Value | Usage |
|---|---|---|
| Primary | TBD | Main identity and dominant shapes |
| Secondary | TBD | Supporting panels and accents |
| Accent | TBD | Limited emphasis, transitions, highlights |
| Semantic success | TBD | Confirmed/positive states |
| Semantic warning | TBD | Warnings only when content supports it |
| Semantic danger | TBD | Serious risk/error states only |
| Muted | TBD | Background context and inactive states |

Use high contrast for text. Do not introduce permanent brand colors without
approved brand evidence from `providers/<name>/DESIGN.md` and `brand/palette.json`.

## Typography

- Families: TBD by project and font license (see provider design).
- Scale: title, section, body, caption, label, data label.
- Weights: use contrast deliberately; avoid too many weights in one scene.
- Line height: keep long text readable on mobile and TV.
- Casing: define title, label, caption, and data conventions.
- Font readiness: load and verify fonts before text measurement or render.

## Spacing And Grid

- Define margins, gutters, card padding, baseline rhythm, and diagram spacing per
  aspect ratio.
- Preserve enough negative space for reading and evidence inspection.
- Avoid placing important text near edges, captions, faces, UI controls, or
  product details.

## Shape, Texture, And Image Treatment

- Corner radii: TBD.
- Borders: TBD.
- Shadows: use sparingly; avoid muddy contrast after compression.
- Texture: only when it supports identity or evidence separation.
- Image treatment: preserve aspect ratio, source context, color meaning, and
  document/UI readability.

## Icons And Illustration

- Icon style: TBD by project.
- Illustration style: match approved brand assets; do not imitate named studios,
  artists, or copyrighted characters.
- States: normal, active, warning, disabled, source/evidence.

## Captions And Lower Thirds

- Captions are accessibility elements first.
- Keep captions readable, high contrast, inside safe areas, and clear of faces,
  UI, evidence, products, and gameplay.
- Lower thirds should identify people, sources, dates, places, or chapters
  without competing with the subject.

## Charts, Maps, Documents, And UI

- Charts: preserve values, units, baselines, labels, ordering, and source.
- Maps: preserve geography, north/orientation, route, chronology, scale, and
  labels.
- Documents: preserve context; highlight without hiding evidence.
- UI/product: use real capture, approved assets, or documented mockups. Do not
  invent product behavior.

## Motion Tokens

| Token | Default | Notes |
|---|---|---|
| motion.duration.micro | TBD | Small feedback or cursor/action emphasis |
| motion.duration.short | TBD | Simple entrances, exits, and highlights |
| motion.duration.standard | TBD | Cards, diagrams, and callouts |
| motion.duration.emphasis | TBD | Major reveals or camera moves |
| motion.ease.enter | TBD | Entrances and reveals |
| motion.ease.exit | TBD | Exits and clearing attention |
| motion.ease.emphasis | TBD | Important moments |
| motion.distance.small | TBD | Label/callout movement |
| motion.distance.medium | TBD | Card/object movement |
| motion.distance.large | TBD | Camera/layout movement |
| motion.stagger.tight | TBD | Related small elements |
| motion.stagger.standard | TBD | Lists or grouped reveals |
| motion.blur.enter | TBD | Use only when readability remains intact |
| motion.scale.emphasis | TBD | Use sparingly and avoid nausea |

Tokens are starting constraints, not rigid values. Adjust to content, frame rate,
object size, and scene intent.

## Motion Language

- Entrances: reveal from off-screen, scale, opacity, mask, draw-on, or focus
  state toward the resting layout.
- Holds: keep final states readable long enough to understand.
- Exits: clear attention, motivate the next scene, or continue motion.
- Transitions: use a small recurring family tied to chapter, time, location,
  concept transform, or editorial cut.
- Camera: use only to reveal, connect, establish scale, reframe, or support
  emotion.
- SFX: support major motion and interaction cues; do not add a sound to every
  animation.

## Reduced Motion

- Provide a reduced-motion mode when context supports it.
- Replace large spatial movement, parallax, shake, looping backgrounds, and
  intense zooms with static states, cuts, or short opacity transitions.
- Preserve meaning through text, icons, layout, or narration, not motion alone.

## Examples

- TBD: approved title card.
- TBD: approved lower third.
- TBD: approved chart reveal.
- TBD: approved document highlight.

## Anti-Examples

- Motion added only to fill time.
- Multiple equal-intensity animations competing with a readable text block.
- Generic templates that ignore the channel promise or brand assets.
- Effects that imply false causality, urgency, danger, or product behavior.

# <Provider> — Design System

> **Status:** template — replace every placeholder before using.
> **Provider kind:** youtube | tiktok | instagram | x | podcast | shorts | generic

This is the provider design language AVO reads when editing videos for this
provider. Keep it self-contained: an agent should be able to produce on-brand
thumbnails, lower-thirds, captions and motion from this file plus the palette in
`brand/palette.json`.

## 1. Brand essence

One sentence that defines the channel/account voice and look.

## 2. Palette

Canonical colors live in `brand/palette.json` (machine-readable). Summarize the
hierarchy here (primary, secondary, accent, background, text) and any contrast
rules.

## 3. Typography

- Display / wordmark: <family> (fallback: <stack>)
- Headings / UI: <family>
- Body: <family>

## 4. Logo

Logo assets live in `logo/` (SVG source + PNG exports). Note clear-space and
minimum-size rules.

## 5. Captions & lower-thirds

Describe the caption style (font, weight, safe zones) and lower-third layout so
the editing workflow stays consistent across this provider's videos.

## 6. Motion language

Entrance/hold/exit conventions, easing character, and any density preferences.

### Boil insert (optional)

Timed wiggly/boiling overlays use presets from `brand/palette.json` → `boil`:

| Preset | Character |
|--------|-----------|
| subtle | Restrained hand-drawn edge |
| standard | Default callout boil |
| wild | High-energy displacement |

Boil applies to **insert layers only** — not full-frame ambient wobble. See
`docs/exemplars/hyperframes-boil-insert/`.

### Audio restoration (optional)

Default noise-reduction strength for speech-led videos:

- `restoration_default_pct` in `avo.provider.json` (optional, 0–100)
- **Standard 35%** if omitted — matches legacy conservative denoise
- Per-segment overrides live in each video's `edit/edl.json` → `audio.restoration_segments[]`

See `agent-skills/avo-pipeline/references/noise-reduction-knowledge.md`.

## 7. Do / Do not

- Do: …
- Do not: …

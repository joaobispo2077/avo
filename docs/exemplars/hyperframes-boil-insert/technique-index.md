# Technique index — boil insert

## DaVinci Fusion → HyperFrames mapping

| Fusion | HyperFrames / web |
|--------|-------------------|
| Text node | HTML text in `#boil-target` wrapper |
| Background α = 0 | Transparent `#root` |
| Displace | `feDisplacementMap` |
| Fast Noise | `feTurbulence` (`fractalNoise`) |
| Seed Rate | `BoilInsert.applyBoil` stepped seed (~9 fps) |
| Displace XY | `xChannelSelector="R"`, `yChannelSelector="G"` |
| Time Stretcher (rhythmic) | `applyBoil({ rhythmicLoop: true, loopSeeds: [...] })` |
| Shadow (Shading) | CSS `text-shadow` on callout |
| Displace Offset | `BoilLifecycle.applyCenterOffset()` |
| Image / video | Same filter on wrapper around `<img>` / `<video>` |

## Presets

| Name | Use case | scale | fps |
|------|----------|-------|-----|
| subtle | Restrained / corporate | 4 | 8 |
| standard | Default callouts | 10 | 9 |
| wild | Hype / hand-drawn emphasis | 22 | 12 |

Resolve from `BoilPresets.getPreset(name)` or provider `palette.json` → `boil.defaultPreset`.

## Doctrine precedence

| Student-kit / generic | AVO boil insert |
|-----------------------|-----------------|
| Constant ambient motion | Boil **only during hold** on timed insert |
| Full-scene shake | **Forbidden** — insert bounds only |
| Idle wobble between beats | **Forbidden** — use entrance/hold/exit lifecycle |

Boil is **insert styling**, not scene breathing.

## Content types

| Type | Starter | Notes |
|------|---------|-------|
| Text callout | `starter/` | Kinetic type, lower-thirds |
| Image sticker | `starter-image/` | PNG/SVG in boil wrapper |
| Video clip | Same as image | HF-owned `<video>` in wrapper; no manual seek |

## Skill routes

| Intent | Skill / command |
|--------|-----------------|
| Short wiggly callout | `motion-graphics` → kinetic-type |
| Lower-third | `motion-graphics` → lower-thirds |
| Card on talking head | `talking-head-recut` (boil on text layer) |
| Pipeline slot | `/avo.motion` |

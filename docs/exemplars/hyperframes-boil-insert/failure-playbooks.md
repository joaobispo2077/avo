# Failure playbooks — boil insert

## Lint: timeline shorter than data-duration

**Symptom:** Black flash or early clip end.  
**Fix:** Add `tl.to({}, { duration: SLOT }, 0)` where `SLOT` = root `data-duration`.

## Boil runs before text visible

**Symptom:** Noise animates during entrance.  
**Fix:** Pass `startTime` / `duration` from `BoilLifecycle.boilHoldWindow(phases)` to `applyBoil`.

## Text drifts off center

**Symptom:** Displacement shifts callout away from safe zone.  
**Fix:** `BoilLifecycle.applyCenterOffset(el, { x, y })` or reduce `scale` preset.

## Alpha fringe on composite

**Symptom:** Halos on dark/light footage after FFmpeg overlay.  
**Fix:** Confirm WebM export; check `format=yuva420p` in compositor; snapshot on both backgrounds.

## Render slow / GPU stress

**Symptom:** Draft render timeouts at 1080p.  
**Fix:** Use `subtle` preset; shrink insert bounds; proof at 720p first. Glyph-jitter fallback deferred.

## prefers-reduced-motion ignored

**Symptom:** Jitter in accessibility mode.  
**Fix:** Ensure `applyBoil` not called when `BoilInsert.prefersReducedMotion()` is true.

## Duplicate motion_brief_id

**Symptom:** EDL validation failure.  
**Fix:** One unique `motion_brief_id` per overlay+SFX pair.

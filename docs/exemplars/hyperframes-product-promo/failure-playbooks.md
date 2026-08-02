# Failure playbooks (product promo)

Symptom → fix reference for HyperFrames product-promo work. Cross-check [`render-contract.md`](render-contract.md) and `npx hyperframes docs troubleshooting`.

---

## Lint errors

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| Overlapping clips on same track | Two clips share `data-track-index` with overlapping time | Assign different track indices or adjust `data-start` / `data-duration` |
| `missing_gsap_script` | Sub-composition HTML missing GSAP `<script>` | Add GSAP before sub-comp IIFE — does not inherit from parent |
| Duplicate composition id | Host `data-composition-id` ≠ inner template id | Match host, template root, and `window.__timelines` key exactly |
| Timeline shorter than slot | No duration anchor | Add `tl.to({}, { duration: SLOT }, 0)` — see render-contract §1 |

---

## Preview / render

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| Black frame mid-scene | Timeline duration < `data-duration` | Slot-fill anchor (render-contract §1) |
| Video frozen, audio continues | Animated `<video>` directly | Wrap in `<div>`, animate wrapper only |
| White flash between scenes | Transparent root or seam overlap | `seam-craft` — opaque `#root`, wrapper overlap |
| Content piled top-left | Root/c ancestor height collapsed | Explicit px width/height on root chain |
| Studio stuck at 0s | Stale preview | Hard refresh; try `?comp=<id>` URL |
| Render fails mid-way | Missing toolchain | `npx hyperframes doctor` |

---

## Motion quality (doctrine)

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| Cuts feel like slides | Independent scene entrances | Apply vector law — exit axis = entry axis (`motion-doctrine`) |
| Scene wobbles in place | Idle ambient tweens | Remove breathe/wobble; motion must **perform** toward exit |
| Mirrored Z entrance | grow-from-small after receding exit | Match scale-sign across seam (`cut-the-curve`) |
| Cheap hard cuts | No transition energy | Whip streak only with matched vector |

---

## Brand / assets

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| Wrong colors vs channel | Student-kit defaults used | Reload `providers/<name>/DESIGN.md` |
| Blank UI screenshot | Duplicate `id` across comps | Prefix ids with composition id |
| Registry block mis-timed | Block duration ≠ host slot | Re-trim or adjust `data-duration` |

---

## CLI commands

```bash
npx hyperframes lint
npx hyperframes check
npx hyperframes doctor
npx hyperframes docs troubleshooting
npx hyperframes docs data-attributes
```

---

## Escalation

- Impossible seam after ledger stamp → re-read `motion-doctrine` + `cut-the-curve` catalog
- Preview/render parity mismatch → snapshot at beat midpoints; compare to draft render stills
- Upstream student-kit pattern unclear → clone repo locally; do not commit `final.mp4`

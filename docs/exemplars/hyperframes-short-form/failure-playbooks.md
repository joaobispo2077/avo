# Failure playbooks (short-form)

Symptom → fix for 9:16 HyperFrames shorts. See also [`../hyperframes-product-promo/failure-playbooks.md`](../hyperframes-product-promo/failure-playbooks.md).

---

## Sync / timing

| Symptom | Fix |
| ------- | --- |
| Overlays fire 1–2s late | Scene starts in original-time — re-anchor to edited-time |
| Captions drift from VO | Transcribe `-edit.mp4`; add/fix `shift()` in captions comp |
| Face mode wrong for scene | Face-mode array times must be edited-time; check t - 0.15 offset |
| Scene internal anims wrong after retime | Parent `data-start` fixed but straddled cut — adjust local offsets |

---

## Face / video

| Symptom | Fix |
| ------- | --- |
| Frozen face mid-render | Animating `<video>` directly — move tweens to `#face-wrapper` |
| Face cropped in bottom mode | Check BOTTOM scale/position constants; verify 1920×1080 source |
| Jarring mode snap | Add 0.32s `expo.inOut` transition 0.15s before scene |
| Razor cut at y=960 | Add seam-treatment gradient on track 5 |

---

## Visual / pacing

| Symptom | Fix |
| ------- | --- |
| Flat navy background | Add ambient stack — gradient, grain, particles ([`technique-index.md`](technique-index.md)) |
| "AI slide deck" feel | Add one jaw-dropper per ~5s; vary eases; check payoff holds |
| Idle wobble between beats | Remove decorative drift — motion must **perform** (`motion-doctrine`) |
| Captions unreadable | Stroke via text-shadow; reduce pill; check contrast on face |

---

## Lint / structure

| Symptom | Fix |
| ------- | --- |
| Overlapping clips same track | Separate track indices or adjust durations |
| Black flash mid-scene | Slot-fill anchor missing |
| `class="clip"` on video | Move clip class to wrapper div |

---

## Pipeline (`/avo.shorts`)

| Symptom | Fix |
| ------- | --- |
| Master >60s blocked | Structural trim approval + EDITLOG override |
| Captions before motion burned wrong | Re-order: motion → captions → deliver |
| Motion too busy over text | Cap density Level 2–3; simplify overlays |

---

## CLI

```bash
bash scripts/ci/lint-hyperframes-exemplars.sh
npx hyperframes lint
npx hyperframes doctor
```

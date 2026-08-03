# Pre-flight checklist — boil insert

Before `hyperframes preview` or `render`:

- [ ] Loaded `motion-doctrine` — boil is insert styling, not idle wobble
- [ ] Root background **transparent** for overlay slots
- [ ] `BoilInsert.createBoilFilter` + `wrapBoilContent` on hold target only
- [ ] `applyBoil` window matches lifecycle hold (`startTime`, `duration`)
- [ ] Master timeline has `tl.to({}, { duration: SLOT }, 0)` slot fill
- [ ] `window.__timelines["main"]` registered synchronously
- [ ] Preset documented in slot `spec.md` (subtle / standard / wild)
- [ ] Reduced-motion path tested (boil skipped)
- [ ] Snapshot: first frame, mid-boil, hold, final frame
- [ ] Export `--format webm` for alpha overlay
- [ ] EDL entry has `anchor_in_source` + unique `motion_brief_id`

# /avo.rights reference

Rights and source audit stage. Distinct from `/avo.deliver` rights row — this command runs **before** deliver with a dedicated artifact.

## Preconditions

- [ ] `provider` + `rawDir` declared
- [ ] For standard mode: picture lock or approved master path known (or user declares pre-deliver audit)
- [ ] For `--early`: trim proof approved optional; emphasize clip context and transformation

## Parse args

| Arg | Required | Notes |
| --- | -------- | ----- |
| `Provider` | yes | Resolves `providers/<name>/` |
| `rawDir` | yes | Workflow root |
| `Footage:` | optional | Primary program file if not inferable |
| `--early` | optional | Post-trim pass for react, news, documentary, clip-heavy formats |

## Load skill

- **`rights-source-audit`** — inventory, disclosure, reused-content, privacy, AI tracking

## Inventory checklist

1. **SOURCE-LOG.md** — every third-party asset used: music, SFX, clips, fonts, screenshots, research, sponsorship evidence.
2. **Music / SFX / ambience** — license basis, attribution, modification limits.
3. **Clips / react / news / documentary** — context preserved; transformation and original contribution clear.
4. **Sponsorship / affiliate / gifted product / review unit** — disclosure placement near endorsement.
5. **Privacy** — redaction plan for addresses, credentials, minors, confidential UI.
6. **AI-generated or altered media** — tool/model notes; YouTube disclosure review when viewers could be misled.

## Disclosure

- Verify paid promotion, affiliate, and gifted-product disclosure **near** the relevant endorsement — not buried after the recommendation.
- Note YouTube paid promotion settings when applicable.
- **Brazil-facing publication:** add CONAR escalation note in audit output; human review for uncertain CONAR posture.

## Output

1. **Rights audit** from template:
   - Template: [`docs/templates/review/rights-audit.md`](../../../docs/templates/review/rights-audit.md)
   - Write to: `<rawDir>/edit/review/rights-audit.md`
2. Update `SOURCE-LOG.md` for any gaps found during audit.
3. **Result:** **PASS** only when no release-blocking gaps; else **FAIL** with numbered blockers.

## Workflow

1. Confirm program scope and format (clip-heavy → consider `--early`).
2. Load `rights-source-audit`; walk inventory tables in template.
3. Cross-check SOURCE-LOG against actual program content.
4. Record PASS/FAIL; list blockers explicitly.
5. Hand off to `/avo.audio-qc` on master, then `/avo.deliver`.

## Handoff

- `/avo.audio-qc` — loudness/true peak on approved master
- `/avo.deliver` — deliver should **warn** if rights-audit missing; rights category **FAIL** if SOURCE-LOG incomplete

## Related

- Deliver stage: [`deliver.md`](deliver.md)
- Window QC: [`audit.md`](audit.md)
- Editorial skill source: `.claude/skills/rights-source-audit/SKILL.md`

# /avo.supporters Command

**Timeline integration:** Admin

## Workflow guidance

**Workflow steps:** Validate supporters prerequisites → Run supporters → Verify and report the supporters result
**Step state source:** the observed invocation result and any command-owned manifest
**Stopping conditions:** Missing required input, a failed or stale gate, a required human decision, or verified supporters completion
**Valid next commands:** /avo.issues or /avo.help

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Sponsorship links and roadmap prioritization policy.

**Skill:** [`agent-skills/avo-pipeline/references/supporters.md`](../../agent-skills/avo-pipeline/references/supporters.md)

---

## Usage

```
/avo.supporters
```

---

## Role

Read-only. Prints sponsor CTAs and how manual queue prioritization works. No paywall on core AVO features.

---

## Instructions

1. Print GitHub Sponsors and Buy Me a Coffee links (from `.github/FUNDING.yml` / README).
2. Explain sponsor-friendly roadmap: funding helps move **roadmap** items up the maintainer queue — not exclusive access to core pipeline commands.
3. Link to [`docs/ROADMAP.md`](../../docs/ROADMAP.md) for BL-001+ items.
4. Suggest `/avo.issues` with sponsor checkbox when reporting bugs tied to roadmap interest.

---

## Example

```text
/avo.supporters
```

## Shared timeline gateway

Resolves provider/video context but performs no editorial timeline mutation. Reports and configuration reference canonical artifact/revision identities.

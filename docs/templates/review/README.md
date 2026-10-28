# Review templates

Copy into `<rawDir>/edit/review/<checkpoint>/` when opening a human approval gate.

- [`approval-gate-manifest.md`](approval-gate-manifest.md) — per-checkpoint checklist the agent fills and the user approves


Code-drawn motion can add an immutable `code-drawn-review.json` package from
`avo cli animation code-drawn-review`. It provides exact-candidate contact
sheets, sampled full/small frames and requested transition/loop strips, with
source and artifact fingerprints. Link it from the existing review's
`reviewContext.codeDrawnReview`; keep prepared/decoded/inspected coverage
distinct. Preparation remains pending human judgment and grants no approval.
Use the scaffold's REVIEW.md and DELIVERY.md companions for the full identity
inventory. The existing review.json and explicit creator decision remain the
promotion authority.

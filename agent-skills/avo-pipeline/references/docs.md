# /avo.docs reference

## Step/state mapping

**Durable state:** the observed invocation result and any command-owned manifest

**Workflow steps:** Validate docs prerequisites → Run docs → Verify and report the docs result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified docs completion

**Valid next commands:** /avo.help

Topic router for AVO documentation. Read-only.

## Topic table

| topic | Path |
| ----- | ---- |
| `index` | [`docs/README.md`](../../README.md) |
| `workflow` | [`docs/avo-workflow.md`](../../avo-workflow.md) |
| `commands` | [`docs/avo-commands.md`](../../avo-commands.md) |
| `install` | [`docs/install/README.md`](../../../docs/install/README.md) (Tier 1 + Tier 2) |
| `audio` | [`docs/audio-post-production-system.md`](../../audio-post-production-system.md) |
| `animation` | [`docs/animation-system.md`](../../animation-system.md) + [`docs/hyperframes-workflow.md`](../../hyperframes-workflow.md) |
| `delivery` | [`docs/delivery-specifications.md`](../../delivery-specifications.md) |
| `use-cases` | [README § Use cases](../../../README.md#use-cases) |
| `rights` | [`AGENTS.md`](../../../AGENTS.md) (Rights section) |
| `backlog` | [`docs/ROADMAP.md`](../../ROADMAP.md) |

## Usage

Default `topic: index` when omitted. Summarize doc in bullets; suggest next `/avo.*` command.

# /avo.creators reference

## Step/state mapping

**Durable state:** the observed invocation result and any command-owned manifest

**Workflow steps:** Validate creators prerequisites → Run creators → Verify and report the creators result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified creators completion

**Valid next commands:** /avo.help

Maintainer-curated showcase of channels and sites using AVO.

## When to use

- Prospective user asks "who uses AVO?"
- Creator wants to be listed (opt-in only)

## Source of truth

[`docs/creators.md`](../../docs/creators.md) — edit via PR or maintainer after issue review.

## Agent output

1. Summarize current entries (name, platform, link).
2. For new submissions: direct to GitHub **Other request** → category **Creator showcase** with:
   - Public channel/site name
   - Platform (YouTube, TikTok, site, …)
   - URL
   - Explicit opt-in: "I confirm this listing may appear in AVO docs"
3. **No scraping** — never invent or crawl creator lists.

## Related

- [`supporters.md`](supporters.md) — sponsorship (separate from showcase)

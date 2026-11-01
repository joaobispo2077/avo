"""Frozen source semantics and explicit, version-specific collector qualification."""

from __future__ import annotations

from copy import deepcopy

from avo.timeline.contracts import content_hash

_REVIEWED_AT = "2026-10-31"
_FALLBACK_MODES = ("context", "typed-packet", "normalized-import", "manual", "estimate")
_SURFACES = (
    {
        "environment": "codex-cli",
        "agent": "codex",
        "surface": "cli",
        "capability": "candidate",
        "sourceFormat": "Codex exec/SDK/app-server metadata",
        "nativeFields": [
            "thread",
            "turn",
            "cumulative-tokens",
            "cacheRead",
            "reasoning",
        ],
        "limitations": [
            "Reviewed exec usage is cumulative, not universally per-turn; resume needs an explicit baseline and native epoch. Context counts are not necessarily measured usage.",
            "No built-in native profile is qualified. Generic Codex import is denied rather than inventing turn IDs, epochs, zero baselines or terminal flush. Supply a versioned normalized packet.",
        ],
        "references": [
            "https://learn.chatgpt.com/docs/non-interactive-mode",
            "https://learn.chatgpt.com/docs/app-server",
        ],
    },
    {
        "environment": "codex-desktop",
        "agent": "codex",
        "surface": "desktop",
        "capability": "candidate",
        "sourceFormat": "authorized Desktop source/export",
        "nativeFields": ["conditional-thread-usage"],
        "limitations": [
            "Desktop is separate from CLI qualification. No universal passive observer endpoint or Desktop OTel setting support is assumed.",
            "Use only an explicitly authorized compatible app-server/source or supplied export; SDK control of a new client does not attach to an existing Desktop session.",
        ],
        "references": [
            "https://learn.chatgpt.com/docs/app-server",
            "https://learn.chatgpt.com/docs/config-file/config-advanced",
        ],
    },
    {
        "environment": "chatgpt",
        "agent": "chatgpt",
        "surface": "app-browser",
        "capability": "manual-only",
        "sourceFormat": None,
        "nativeFields": [],
        "limitations": [
            "App/MCP client metadata is not a global token, served-model or subscription-cost feed. Visible replies do not measure hidden context or research operations.",
            "A supplied export contributes only fields actually present and attributable. Administrative exports need explicit authority and are never polled by this registry.",
        ],
        "references": [
            "https://developers.openai.com/plugins/reference#_meta-fields-the-client-provides",
            "https://learn.chatgpt.com/docs/enterprise/usage-insights",
        ],
    },
    {
        "environment": "cursor",
        "agent": "cursor",
        "surface": "ide-sdk",
        "capability": "candidate",
        "sourceFormat": "authorized SDK/hook/export metadata",
        "nativeFields": ["run", "turn", "tokens", "optional-money", "selected-model"],
        "limitations": [
            "SDK availability depends on version, local/cloud mode and account features; getUsage may be unavailable. Hooks do not universally expose response usage.",
            "Selected router/Auto model is not the served model/provider of each request. Preserve known usage/money with unknown served model; reasoning is included in output in the reviewed SDK contract.",
            "Context/compaction tokens are not spend. Missing or zero charge does not prove zero usage; admin exports need explicit authorization.",
        ],
        "references": [
            "https://cursor.com/docs/sdk/typescript",
            "https://cursor.com/docs/hooks",
            "https://cursor.com/docs/account/teams/admin-api",
        ],
    },
    {
        "environment": "claude-code",
        "agent": "claude",
        "surface": "cli-sdk",
        "capability": "candidate",
        "sourceFormat": "projected request telemetry or SDK results",
        "nativeFields": [
            "session",
            "request",
            "model",
            "cacheRead",
            "cacheWrite",
            "estimated-money",
            "tree-model-usage",
        ],
        "limitations": [
            "OTel/hook setup is opt-in; a skill/MCP server cannot observe all host usage. Legacy request projections remain unqualified; SDK results need their own versioned temporal profile.",
            "From reviewed v2.1.277 resume/fork restores prior cumulative cost; earlier versions differ. result.usage covers the main loop while modelUsage/total_cost_usd can include children.",
            "Shared message IDs, placeholder output, final revisions and subagent last-request counters are not independently additive. SDK/OTel money is an estimate, not an invoice.",
        ],
        "references": [
            "https://code.claude.com/docs/en/monitoring-usage",
            "https://code.claude.com/docs/en/agent-sdk/cost-tracking",
            "https://code.claude.com/docs/en/hooks",
        ],
    },
    {
        "environment": "opencode",
        "agent": "opencode",
        "surface": "cli-sdk",
        "capability": "candidate",
        "sourceFormat": "completed assistant-message export",
        "nativeFields": [
            "session",
            "message",
            "model",
            "provider",
            "tokens",
            "cacheRead",
            "cacheWrite",
            "estimated-money",
        ],
        "limitations": [
            "Reviewed v1.19.4 forks can copy historical usage under new IDs without parent metadata. Missing inheritance proof stays unallocated; IDs alone cannot establish new work.",
            "Message revisions and step-finish parts can duplicate usage. The legacy projection selects completed messages only and is not a qualified measured collector.",
            "Reasoning is disjoint from output in the reviewed normalization. Preserve model/provider changes and optional estimated cost without inferring an invoice.",
        ],
        "references": [
            "https://opencode.ai/docs/sdk/",
            "https://opencode.ai/docs/cli/",
            "https://github.com/anomalyco/opencode/blob/v1.19.4/packages/opencode/src/session/session.ts",
        ],
    },
    {
        "environment": "gemini-cli",
        "agent": "gemini",
        "surface": "cli",
        "capability": "candidate",
        "sourceFormat": "projected response telemetry/final stats",
        "nativeFields": [
            "session",
            "request",
            "model",
            "tokens",
            "per-model-final-stats",
        ],
        "limitations": [
            "Telemetry is opt-in and requires metadata-only projection; AVO does not change prompt logging or global configuration.",
            "Repeated AfterModel chunks are not independent requests. Final stats and session-end delivery need temporal/flush proof; end delivery can be best effort.",
            "Auth mode changes charging. Gemini Code Assist is a distinct surface, not inherited Gemini CLI support.",
        ],
        "references": [
            "https://geminicli.com/docs/cli/telemetry/",
            "https://geminicli.com/docs/cli/headless/",
            "https://geminicli.com/docs/hooks/reference/",
        ],
    },
    {
        "environment": "cline",
        "agent": "cline",
        "surface": "ide-cli-sdk",
        "capability": "candidate",
        "sourceFormat": "authorized SDK/CLI/OTel metadata",
        "nativeFields": [
            "task",
            "session",
            "model",
            "provider",
            "current-tokens",
            "total-tokens",
            "optional-money",
        ],
        "limitations": [
            "Current versus total counters, aggregate cache, revisions and subagent scope require representative versioned fixtures. Optional cost can remain unknown.",
            "IDE, CLI and SDK routes have separate prerequisites. AVO installs no vendor SDK and never overrides a user's OTel/global configuration.",
        ],
        "references": [
            "https://docs.cline.bot/sdk/reference/events",
            "https://docs.cline.bot/enterprise-solutions/monitoring/opentelemetry-events",
        ],
    },
    {
        "environment": "windsurf",
        "agent": "windsurf",
        "surface": "cascade",
        "capability": "manual-only",
        "sourceFormat": "authorized attributable analytics export",
        "nativeFields": ["conditional-account-native-units"],
        "limitations": [
            "Legacy Windsurf/Cascade and successor Devin Desktop have different keys, units and support. No universal local token source was verified.",
            "Reviewed successor token detail is restricted to DOLLARS billing and unavailable through a Windsurf key. ACU/CREDITS stay native units; account analytics need attributable scope and explicit authority.",
            "Missing instrumentation or historical zeros do not establish coverage. Successor hooks do not prove legacy hook support.",
        ],
        "references": [
            "https://docs.devin.ai/desktop/accounts/api-reference/get-consumption",
            "https://docs.devin.ai/desktop/accounts/api-reference/cascade-analytics",
        ],
    },
    {
        "environment": "unknown",
        "agent": "unknown",
        "surface": "unspecified",
        "capability": "manual-only",
        "sourceFormat": None,
        "nativeFields": [],
        "limitations": [
            "Keep the supplied agent identity. An unknown agent/version never inherits another product's parser, model, baseline or qualification.",
            "Supply explicit context and typed/manual evidence or a scoped estimate. Missing context creates unknown expected-host coverage rather than assuming human/CI execution.",
        ],
        "references": [],
    },
)


def surface_capabilities():
    """Public documentation candidates are separate from admitted source profiles."""
    rows = deepcopy(list(_SURFACES))
    for row in rows:
        row.update(
            modes=list(_FALLBACK_MODES),
            routes=list(_FALLBACK_MODES),
            versions=[],
            qualificationEvidence=[],
            qualificationScope="bundled-native-profiles",
            obtainableFields={
                "supplied": ["identity", "scope", "tokens", "money", "provenance"],
                "documentedNative": row.pop("nativeFields"),
            },
            requiredIntervention=[
                "Declare explicit metadata context; a skill or MCP connection alone is not a usage source.",
                "Bootstrap a manual-only profile with report-manual --participation-fact-id <factId> --operation-id <stableId> --file <metadata-json>; its response supplies profileId for typed manual observe packets.",
                "For measured usage, supply an authorized exact-version qualified profile and scoped packet. No native profile is bundled as qualified; unknown versions use fallback.",
            ],
            fallback={
                "commands": ["context", "report-manual", "observe", "estimate"],
                "reasonCode": "native-source-unqualified",
            },
        )
        row["references"] = [
            {"url": url, "date": _REVIEWED_AT} for url in row["references"]
        ]
    return rows


def profile_id(profile):
    """Hash source semantics without its self-referential identity field."""
    return content_hash(
        {key: value for key, value in profile.items() if key != "profileId"}
    )


def validate_profile(profile):
    from avo.cost_store import CostError, validate

    validate("profile", profile)
    if profile_id(profile) != profile["profileId"]:
        raise CostError("cost profile integrity verification failed")
    return profile


def _profile_status(profile, version, allow_synthetic):
    declared = profile["capability"]
    if declared != "qualified":
        return declared
    if version not in profile["versions"]:
        return "candidate"
    if profile["qualification"]["kind"] == "synthetic" and not allow_synthetic:
        return "candidate"
    return "qualified"


def profile_status(profile, *, version, allow_synthetic=False):
    """A frozen claim needs the exact runtime version and eligible evidence."""
    validate_profile(profile)
    return _profile_status(profile, version, allow_synthetic)


def resolve_profile(
    profiles,
    *,
    agent,
    surface,
    version,
    source_format,
    allow_synthetic=False,
):
    """Return the single eligible profile, never infer support from a brand."""
    from avo.cost_store import CostError

    matches = {}
    for profile in profiles:
        validate_profile(profile)
        if (
            profile["agent"] == agent
            and profile["surface"] == surface
            and profile["sourceFormat"] == source_format
            and _profile_status(profile, version, allow_synthetic) == "qualified"
        ):
            matches[profile["profileId"]] = profile
    if len(matches) > 1:
        raise CostError("ambiguous cost source profile; select an exact profile")
    return deepcopy(next(iter(matches.values()))) if matches else None

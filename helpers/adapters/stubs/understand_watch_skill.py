"""watch-skill understand job stub."""

from __future__ import annotations

from helpers.adapters.base import JobRequest, JobResult


class WatchSkillStubAdapter:
    routing_id = "watch-skill"

    def run(self, request: JobRequest) -> JobResult:
        from helpers.models import format_active_model, load_catalog, resolve_option_id

        path = request.root / "tools" / "watch-skill"
        catalog = load_catalog(request.root)
        model_id = resolve_option_id("understand", root=request.root)
        model_label = format_active_model(catalog, "understand", model_id)
        if not path.is_dir() or not any(path.iterdir()):
            return JobResult(
                exit_code=2,
                stderr=f"watch-skill not installed at {path} — run setup",
                models_used={"understand": model_label},
            )
        return JobResult(
            exit_code=2,
            stderr=(
                f"watch-skill stub: tool present; expected LLM tier {model_label}. "
                "Invoke watch-skill via subprocess/CLI boundary only — full adapter wiring is backlog."
            ),
            models_used={"understand": model_label},
        )

"""Compose configured semantic, acoustic and sampled visual take observations."""

from copy import deepcopy

from avo.timeline.contracts import content_hash
from avo.timeline.ports import ToolError

from .cutting_semantics import CuttingSemanticsAdapter


class CuttingTakeAnalysisAdapter:
    """Missing independent complete-unit evidence remains a review requirement."""

    def __init__(
        self,
        *,
        semantics=None,
        watch=None,
        evidence_port=None,
        watch_request=None,
        raw_dir=None,
    ):
        self.semantics = semantics
        self.watch = watch
        self.evidence_port = evidence_port
        self.watch_request = watch_request or {}
        self.raw_dir = raw_dir

    def analyze_group(
        self, source, group, analysis, *, sync_ref=None, analysis_ref=None
    ):
        result = {
            "sourceRef": deepcopy(analysis.get("sourceRef")),
            "syncRef": deepcopy(sync_ref),
            "routing": deepcopy(analysis.get("routing")),
            "groupHash": content_hash(group),
            "status": "needs-review",
            "verifiedAttempts": [],
            "perTake": {},
            "evidenceRefs": [analysis_ref] if analysis_ref else [],
            "semanticEquivalence": None,
            "restartConfirmed": None,
        }
        if self.evidence_port:
            independent = self.evidence_port.analyze_group(
                source, group, analysis, sync_ref=sync_ref, analysis_ref=analysis_ref
            )
            if self._bound(independent, result):
                result.update(independent)
        semantic_port = self.semantics
        if semantic_port is None and self._configured_watch():
            semantic_port = CuttingSemanticsAdapter(
                lambda request: self._watch_completion(source, group, result, request)
            )
        if semantic_port:
            semantics = semantic_port.compare(
                group, {"words": analysis.get("words", [])}
            )
            result.update(
                {
                    key: semantics[key]
                    for key in ("semanticEquivalence", "protectedDifferences")
                }
            )
            result["semanticObservation"] = semantics
            if result.get("visualObservation", {}).get("promptHash"):
                semantics["instructionHash"] = semantics["promptHash"]
                semantics["promptHash"] = result["visualObservation"]["promptHash"]
        if "visualObservation" not in result:
            self._visual(source, group, result)
        return result

    @staticmethod
    def _bound(observation, expected):
        return all(
            observation.get(key) == expected[key]
            for key in ("sourceRef", "syncRef", "routing", "groupHash")
        )

    def _visual(self, source, group, result):
        if not self._configured_watch():
            return
        observation = self._watch_observation(source, group, self.watch_request)
        result["visualObservation"] = observation
        for take_id, visual in observation.get("perTake", {}).items():
            target = result["perTake"].setdefault(take_id, {})
            target["visualUsability"] = visual.get("visualUsability")

    def _watch_observation(self, source, group, request):
        try:
            return self.watch.review_original_takes(
                source["locator"],
                source_sha256=source["fingerprint"]["sha256"],
                takes=group["attempts"],
                raw_dir=self.raw_dir,
                **request,
            )
        except ToolError as error:
            return {"status": "blocked", "reason": str(error), "perTake": {}}

    def _configured_watch(self):
        return bool(
            self.watch
            and self.raw_dir
            and self.watch_request.get("model_pin")
            and self.watch_request.get("policy")
        )

    def _watch_completion(self, source, group, result, request):
        context = deepcopy(self.watch_request.get("context") or {})
        context["takeSemantics"] = request
        context.setdefault("acceptanceCriteria", []).append(
            "Assess the declared takeSemantics instruction on quoted source text. Provide exactly one observed finding 'take-semantics-json=' followed by the requested JSON object equivalent (boolean/null), protectedDifferences (array), reason. Unknown intent or conflicting qualifiers must not be equivalent. This does not certify acoustic completeness."
        )
        observation = self._watch_observation(
            source, group, {**self.watch_request, "context": context}
        )
        result["visualObservation"] = observation
        for take_id, visual in observation.get("perTake", {}).items():
            result["perTake"].setdefault(take_id, {})["visualUsability"] = visual.get(
                "visualUsability"
            )
        valid = (
            observation.get("status") == "inferred"
            and observation.get("sourceSha256") == source["fingerprint"]["sha256"]
            and observation.get("promptHash")
        )
        return {
            "modelIdentity": observation.get("modelIdentity") if valid else None,
            "response": observation.get("semanticResponse"),
        }

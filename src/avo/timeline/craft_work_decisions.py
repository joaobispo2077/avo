"""Reversible requested-work dispositions, separate from canonical edit decisions."""

from copy import deepcopy

from .contracts import content_hash


class WorkDecisionError(ValueError):
    def to_dict(self):
        return {
            "code": "CRAFT_WORK_DECISION_INVALID",
            "message": str(self),
            "blocking": True,
        }


def work_identity(value):
    return value["kind"], value["operationId"]


def require_registered_work(run, value):
    entries = (run.get("extensions") or {}).get("editingCraftWork", [])
    if value not in entries:
        raise WorkDecisionError("Decision must name the exact original requested work")
    return value


def _validate_replacement(run, request, work):
    if request.get("replacement") is None:
        return
    replacement = require_registered_work(run, request["replacement"])
    if replacement["kind"] != work["kind"] or work_identity(
        replacement
    ) == work_identity(work):
        raise WorkDecisionError(
            "Supersession requires different requested work of the same kind"
        )


def validate_work_decision_history(run):
    heads, operations = {}, set()
    records = (run.get("extensions") or {}).get("editingCraftWorkDecisions", [])
    for record in records:
        request = record["request"]
        work = require_registered_work(run, request["work"])
        identity = work_identity(work)
        if (
            request["operationId"] in operations
            or content_hash(request) != record["requestHash"]
        ):
            raise WorkDecisionError(
                "Requested-work decision history changes an operation"
            )
        operations.add(request["operationId"])
        if request["expectedDecisionHash"] != heads.get(identity):
            raise WorkDecisionError(
                "Requested-work decision history changes its predecessor"
            )
        heads[identity] = record["requestHash"]
        scope = work["scope"]["eventIds" if work["kind"] == "sound" else "itemIds"]
        if set(request["ids"]) - set(scope):
            raise WorkDecisionError(
                "Decision IDs differ from the original requested scope"
            )
        _validate_replacement(run, request, work)


def _decisions_for(records, row):
    return [
        record
        for record in records
        if work_identity(record["request"]["work"]) == work_identity(row)
    ]


def _closed_status(row, closed, decisions):
    states = {decisions[identity]["status"] for identity in closed}
    if row["completedIds"]:
        return "resolved"
    return next(iter(states)) if len(states) == 1 else "resolved"


def _queue_status(row, active, closed, deferred, decisions):
    if row["status"] in {"unavailable", "recovery-needed"}:
        return row["status"]
    if not active and closed:
        return _closed_status(row, closed, decisions)
    if active and active == deferred:
        return "deferred"
    return "partial" if closed and active else row["status"]


def _latest_dispositions(selected):
    decisions = {}
    for record in selected:
        request = record["request"]
        value = {"status": request["status"], "decisionHash": record["requestHash"]}
        if "replacement" in request:
            value["replacement"] = deepcopy(request["replacement"])
        for identity in request["ids"]:
            decisions[identity] = value
    return decisions


def _partition_unapplied(row, decisions):
    original = row["scope"]["eventIds" if row["kind"] == "sound" else "itemIds"]
    completed = set(row["completedIds"])
    active, closed, deferred = [], [], []
    for identity in original:
        if identity in completed:
            continue
        status = decisions.get(identity, {}).get("status")
        if status in {"dismissed", "superseded"}:
            closed.append(identity)
        else:
            active.append(identity)
        if status == "deferred":
            deferred.append(identity)
    return active, closed, deferred


def apply_work_dispositions(row, records):
    result = deepcopy(row)
    selected = _decisions_for(records, row)
    decisions = _latest_dispositions(selected)
    active, closed, deferred = _partition_unapplied(row, decisions)
    result.update(
        decisionHead=selected[-1]["requestHash"] if selected else None,
        workDecisions=decisions,
        closedIds=closed,
        deferredIds=deferred,
        status=_queue_status(row, active, closed, deferred, decisions),
    )
    if row["status"] not in {"unavailable", "recovery-needed"}:
        result["pendingIds"] = active
    return result


def decorate_work_decisions(rows, records):
    return [apply_work_dispositions(row, records) for row in rows]


def find_work_decision(run, request):
    for record in (run.get("extensions") or {}).get("editingCraftWorkDecisions", []):
        if record["request"]["operationId"] == request["operationId"]:
            if record["request"] != request:
                raise WorkDecisionError("Decision operation records different inputs")
            return record
    return None


def require_decidable_work(rows, request):
    identity = work_identity(request["work"])
    row = next((row for row in rows if work_identity(row) == identity), None)
    if row is None or row["status"] in {"unavailable", "recovery-needed"}:
        raise WorkDecisionError(
            "Restore or reconcile this requested work before deciding it"
        )
    if set(request["ids"]) & set(row["completedIds"]):
        raise WorkDecisionError(
            "Applied choices require their normal canonical revision controls"
        )
    if request["expectedDecisionHash"] != row.get("decisionHead"):
        raise WorkDecisionError(
            "Requested-work decisions changed; inspect the current queue"
        )

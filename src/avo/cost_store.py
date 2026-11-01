"""Portable immutable cost evidence. No model calls or account access."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from avo.avo_state import now_iso
from avo.paths import schema_path
from avo.timeline.contracts import content_hash


class CostError(ValueError):
    """Invalid or inconsistent accounting evidence (safe for user output)."""


RECORD_TYPES = {
    "participations": ("participation", "factId"),
    "profiles": ("profile", "profileId"),
    "estimates": ("estimate", "estimateId"),
    "reconciliations": ("reconciliation", "reconciliationId"),
}
CAPTURE_FAMILIES = ("batches", "corrections", "prices", "bindings", *RECORD_TYPES)


_V2_DEFINITIONS = {
    "profile": "profile",
    "participation": "participationFact",
    "evidence": "evidence",
    "receipt": "receipt",
    "estimate": "estimateRecord",
    "reconciliation": "reconciliationRecord",
    "context": "contextRequest",
    "transition": "transitionRequest",
    "packet": "observePacket",
    "estimate-request": "estimateRequest",
    "manual-request": "manualRequest",
    "reconcile-request": "reconcileRequest",
}


@lru_cache(maxsize=1)
def _schema_registry():
    from referencing import Registry, Resource

    documents = []
    for path in schema_path("avo.cost-observation.schema.json").parent.glob(
        "avo.cost-*.schema.json"
    ):
        value = json.loads(path.read_text("utf-8"))
        documents.append((value["$id"], Resource.from_contents(value)))
    # No HTTP retrieval callback: only bundled schemas are resolvable.
    return Registry().with_resources(documents)


@lru_cache(maxsize=12)
def _validator(kind):
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads(schema_path(f"avo.cost-{kind}.schema.json").read_text("utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate(kind, value):
    if not _validator(kind).is_valid(value):
        raise CostError(f"invalid cost {kind}; check the documented metadata schema")
    _validate_integer_counts(kind, value)
    if kind == "snapshot":
        payload = {
            k: v for k, v in value.items() if k not in {"snapshotId", "recordedOrder"}
        }
        if content_hash(payload) != value["snapshotId"]:
            raise CostError("cost snapshot integrity verification failed")
    for field in ("occurredAt", "createdAt", "effectiveAt", "cutoff"):
        stamp = value.get(field)
        if stamp is not None:
            try:
                parsed = datetime.fromisoformat(stamp)
                if parsed.tzinfo is None:
                    raise ValueError("missing UTC offset")
            except (ValueError, TypeError, AttributeError) as exc:
                raise CostError(f"invalid cost {kind} timestamp") from exc
    return value


def _validate_timestamps(kind, value):
    for field in ("occurredAt", "createdAt", "effectiveAt", "cutoff"):
        stamp = value.get(field)
        if stamp is not None:
            try:
                parsed = datetime.fromisoformat(stamp)
                if parsed.tzinfo is None:
                    raise ValueError("missing UTC offset")
            except (ValueError, TypeError, AttributeError) as exc:
                raise CostError(f"invalid cost {kind} timestamp") from exc


def _validate_integer_counts(kind, value):
    if kind == "observation" and any(
        v is not None and type(v) is not int for v in value["tokens"].values()
    ):
        raise CostError("invalid cost count; tokens must be integers")
    if kind == "price" and type(value["denominator"]) is not int:
        raise CostError("invalid price denominator; expected an integer")


def _check_token_integers(value):
    if isinstance(value, list):
        for item in value:
            _check_token_integers(item)
    elif isinstance(value, dict):
        tokens = value.get("tokens")
        if isinstance(tokens, dict) and any(
            count is not None and type(count) is not int for count in tokens.values()
        ):
            raise CostError("invalid cost count; tokens must be integers")
        for item in value.values():
            _check_token_integers(item)


def read_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise CostError("cost input exceeds 32 MiB")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise CostError("invalid cost JSON input") from exc


class CostStore:
    """All paths are contained beneath one project's accounting directory."""

    def __init__(self, raw_dir, *, archive=False):
        self.raw_dir = Path(raw_dir).expanduser().resolve()
        self.root = self.raw_dir if archive else self.raw_dir / "edit" / "costs"

    digest = staticmethod(content_hash)

    def membership_digest(self, kind, value):
        """Return the accepted record identity used by a captured report."""
        from avo.cost_history import _portable_membership

        projected = _portable_membership(self, kind, value)
        if projected is not None:
            return projected
        return value["contentHash"] if kind == "batches" else self.digest(value)

    def membership(self, view=None):
        captured = self.capture() if view is None else view
        return {
            kind: sorted(self.membership_digest(kind, value) for value in records)
            for kind, records in captured.items()
        }

    def assert_writable(self):
        if self.path("portable.json").exists():
            raise CostError(
                "portable cost projection is read-only; reauthorize sources in a production ledger"
            )

    def portable_status(self):
        from avo.cost_history import _portable_manifest

        manifest = _portable_manifest(self)
        if manifest is None:
            return None
        keys = (
            "manifestId",
            "verification",
            "sourceReauthorizationRequired",
            "limitations",
        )
        return {key: deepcopy(manifest[key]) for key in keys}

    def read_snapshot(self, snapshot_id):
        from avo.cost_history import _portable_manifest, _portable_read_snapshot

        if not isinstance(snapshot_id, str) or not re.fullmatch(
            r"[a-f0-9]{64}", snapshot_id
        ):
            raise CostError("invalid cost snapshot identity")
        manifest = _portable_manifest(self)
        if manifest is not None:
            snapshot = _portable_read_snapshot(self, snapshot_id, manifest)
        else:
            if not self.path(f"snapshots/{snapshot_id}.json").is_file():
                raise CostError("unknown cost snapshot")
            snapshot = self._read_document("snapshots", snapshot_id + ".json")
        identity = self.identity()
        if (
            not identity
            or snapshot["accountingVideoId"] != identity["accountingVideoId"]
        ):
            raise CostError("cost snapshot belongs to another production")
        if snapshot["snapshotId"] != snapshot_id:
            raise CostError("cost snapshot identity mismatch")
        return snapshot

    def path(self, relative):
        candidate = Path(os.path.abspath(self.root / relative))
        if not candidate.is_relative_to(self.raw_dir):
            raise CostError("cost path leaves the project")
        # Junctions and symlink aliases are not accounting storage.
        for part in (candidate, *candidate.parents):
            if part == self.raw_dir:
                break
            if _is_storage_link(part):
                raise CostError("cost storage contains a link")
        return candidate

    def publish(self, relative, value):
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        lock = target.with_suffix(".lock")
        for _ in range(200):
            try:
                lock.mkdir()
                break
            except FileExistsError:
                time.sleep(0.01)
        else:
            raise CostError("cost write locked; retry or recover an interrupted writer")
        try:
            if target.exists():
                if read_json(target) != value:
                    raise CostError(
                        "immutable cost document conflicts with existing evidence"
                    )
                return value
            return self._publish_locked(target, value)
        finally:
            lock.rmdir()

    @staticmethod
    def _publish_locked(target, value):
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True, allow_nan=False
        ).encode()
        fd, temp = tempfile.mkstemp(prefix=".cost-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        finally:
            Path(temp).unlink(missing_ok=True)
        return value

    def identity(self):
        path = self.path("identity.json")
        return validate("identity", read_json(path)) if path.exists() else None

    def initialize(self, provider, video_id):
        existing = self.identity()
        if existing:
            if existing["provider"] != provider:
                raise CostError(
                    "video accounting belongs to another channel; use an explicit identity fork"
                )
            return existing
        value = {
            "schemaVersion": "1.0.0",
            "accountingVideoId": str(uuid4()),
            "provider": provider,
            "videoId": video_id,
            "createdAt": now_iso(),
        }
        validate("identity", value)
        try:
            return self.publish("identity.json", value)
        except CostError:
            existing = self.identity()
            if existing:
                return self.initialize(provider, video_id)
            raise

    @staticmethod
    def observation_id(row):
        keys = ("sourceInstanceId", "sourceSessionId", "counterEpoch", "requestId")
        return content_hash({k: row.get(k) for k in keys})

    def documents(self, kind):
        directory = self.path(kind)
        return [
            self._read_document(kind, p.name) for p in sorted(directory.glob("*.json"))
        ]

    def _read_document(self, kind, name):
        value = read_json(self.path(f"{kind}/{name}"))
        schema = {
            "bindings": "binding",
            "prices": "price",
            "corrections": "correction",
            "snapshots": "snapshot",
        }.get(kind)
        return validate(schema, value) if schema else value

    def ingest(self, rows):
        identity = self.identity()
        if not identity:
            raise CostError("initialize a video with costs bind or import first")
        if not isinstance(rows, list) or len(rows) > 100000:
            raise CostError("invalid cost observations or record limit exceeded")
        for row in rows:
            validate("observation", row)
        rows = _new_rows(rows, self.documents("batches"))
        if not rows:
            return {"status": "ok", "imported": 0, "batchId": None}
        value = {
            "schemaVersion": "1.0.0",
            "batchId": str(uuid4()),
            "accountingVideoId": identity["accountingVideoId"],
            "createdAt": now_iso(),
            "observations": rows,
            "observationKeys": self.keys_for(rows),
            "recordedOrder": time.time_ns(),
            "priceScheduleIds": sorted(
                content_hash(p) for p in self.documents("prices")
            ),
        }
        value["contentHash"] = content_hash(value)
        self.publish(f"batches/{value['batchId']}.json", value)
        self.amend_if_closed()
        return {"status": "ok", "imported": len(rows), "batchId": value["batchId"]}

    def _ingest_rows(self, rows, identity):
        rows = _new_rows(rows, self.documents("batches"))
        if not rows:
            self.amend_if_closed()
            return {"status": "ok", "imported": 0, "batchId": None}
        _assert_exclusive_claims(self, [(key, None) for key in self.keys_for(rows)])
        _remember_claim_store(self)
        value = {
            "schemaVersion": "1.0.0",
            "batchId": str(uuid4()),
            "accountingVideoId": identity["accountingVideoId"],
            "createdAt": now_iso(),
            "observations": rows,
            "observationKeys": self.keys_for(rows),
            "recordedOrder": time.time_ns(),
            "priceScheduleIds": sorted(
                content_hash(p) for p in self.documents("prices")
            ),
        }
        value["contentHash"] = content_hash(value)
        self.publish(f"batches/{value['batchId']}.json", value)
        self.amend_if_closed()
        return {"status": "ok", "imported": len(rows), "batchId": value["batchId"]}

    def _check_format(self):
        marker = self.path("format.json")
        if marker.is_file() and read_json(marker).get("schemaVersion") != "2.0.0":
            raise CostError("unsupported cost ledger format; use a compatible runtime")

    def _enable_v2(self):
        self._check_format()
        self.publish(
            "format.json", {"schemaVersion": "2.0.0", "minimumReader": "2.0.0"}
        )

    def append_record(self, kind, payload):
        self.assert_writable()
        if kind not in RECORD_TYPES or not isinstance(payload, dict):
            raise CostError("invalid cost record family or metadata")
        if kind == "reconciliations":
            with _cost_claim_lock():
                with _directory_lock(self.path("locks/reconciliation-family.lock")):
                    return self._append_operation(kind, payload)
        return self._append_operation(kind, payload)

    def _append_operation(self, kind, payload):
        operation = payload.get("operationId") or content_hash(payload)
        key = content_hash({"kind": kind, "operation": operation})
        with _directory_lock(self.path(f"locks/{key}.lock")):
            return self._append_record(kind, payload)

    def _append_record(self, kind, payload):
        """Publish one immutable fact; a repeated operation never changes content."""
        if kind not in RECORD_TYPES or not self.identity():
            raise CostError("initialize accounting before accepting cost records")
        value = deepcopy(payload)
        schema, id_field = RECORD_TYPES[kind]
        value.setdefault(id_field, _record_digest(value, id_field))
        validate(schema, value)
        _verify_record(kind, value)
        _record_owner(value, self.identity())
        view = self.capture()
        previous = _operation_record(view[kind], value.get("operationId"))
        if previous is not None:
            if previous != value:
                raise CostError("cost operation replay conflicts with accepted content")
            self.amend_if_closed()
            return previous
        self._validate_new_record(kind, value, view)
        self._enable_v2()
        result = self.publish(f"{kind}/{value[id_field]}.json", value)
        self.amend_if_closed()
        return result

    def _validate_new_record(self, kind, value, view):
        from avo.cost_participation import validate_fact_graph, validate_reconciliation

        if kind == "participations":
            validate_fact_graph([*view[kind], value])
        elif kind == "profiles":
            from avo.cost_profiles import validate_profile

            validate_profile(value)
        elif kind == "reconciliations":
            validate_reconciliation(value, known_refs=self.references(view))
            _validate_transfer_supersession(self, value, view)
        elif kind == "estimates" and value[
            "participationId"
        ] not in _declared_participations(view):
            raise CostError("cost estimate references an unknown participation")

    def references(self, view=None):
        """Exact evidence/estimate/decision identities for reviewed relationships."""
        from avo.cost_participation import legacy_evidence_id

        view = view if view is not None else self.capture()
        result = {}
        for kind, (_, id_field) in RECORD_TYPES.items():
            result.update({item[id_field]: item for item in view[kind]})
        for batch in view["batches"]:
            _verify_batch(batch, self.identity())
            keys = batch.get("observationKeys")
            if keys is None:
                keys = self.keys_for(batch["observations"])
            for key, row in zip(keys, batch["observations"]):
                identity = legacy_evidence_id(key)
                result.setdefault(
                    identity,
                    {
                        "evidenceId": identity,
                        "key": key,
                        "nature": "legacy-unknown",
                        "_accountingVideoId": batch["accountingVideoId"],
                    },
                )
                result.setdefault(
                    key["sourceDigest"],
                    {
                        "key": key,
                        "observation": row,
                        "accountingVideoId": batch["accountingVideoId"],
                    },
                )
            result.update(
                {
                    item["evidenceId"]: {
                        **item,
                        "_accountingVideoId": batch["accountingVideoId"],
                    }
                    for item in batch.get("evidence", [])
                }
            )
        return result

    def ingest_packet(self, packet, *, allow_synthetic=False):
        """Commit rows, metadata and the accepted frontier in the same file."""
        self.assert_writable()
        validate("packet", packet)
        if len(json.dumps(packet, allow_nan=False).encode()) > 32 * 1024 * 1024:
            raise CostError("cost input exceeds 32 MiB")
        with _cost_claim_lock():
            return self._ingest_packet(packet, allow_synthetic=allow_synthetic)

    def _ingest_packet(self, packet, *, allow_synthetic=False):
        identity = self.identity()
        _record_owner(packet, identity)
        view = self.capture()
        previous = _operation_record(view["batches"], packet["operationId"])
        if previous is not None:
            result = _packet_replay(previous, packet)
            self.amend_if_closed()
            return result
        _validate_packet(packet, view, allow_synthetic)
        _assert_exclusive_claims(self, _packet_claims(packet))
        _remember_claim_store(self)
        batch_id = content_hash({"domain": "cost-batch/v2", "packet": packet})
        value = {
            **deepcopy(packet),
            "batchId": batch_id,
            "createdAt": now_iso(),
            "recordedOrder": time.time_ns(),
            "observationKeys": self.keys_for(packet["observations"]),
            "priceScheduleIds": sorted(content_hash(p) for p in view["prices"]),
            "profileIds": [packet["profileId"]],
        }
        value["contentHash"] = content_hash(value)
        validate("batch", value)
        self._enable_v2()
        try:
            self.publish(f"batches/{batch_id}.json", value)
        except CostError:
            path = self.path(f"batches/{batch_id}.json")
            if not path.is_file():
                raise
            saved = read_json(path)
            _verify_batch(saved, identity)
            result = _packet_replay(saved, packet)
            self.amend_if_closed()
            return result
        imported = len(_new_rows(packet["observations"], view["batches"]))
        self.amend_if_closed()
        return {
            "status": "ok",
            "imported": imported,
            "batchId": batch_id,
            "replayed": False,
        }

    def capture(self):
        return {
            kind: self.documents(kind)
            for kind in ("batches", "corrections", "prices", "bindings")
        }

    def observations(self, view=None):
        view = view if view is not None else self.capture()
        variants = self._variants(view)
        decisions = _decisions(view["corrections"])
        return _resolve_variants(variants, decisions)

    def _variants(self, view):
        variants = {}
        identity = self.identity()
        prices = {content_hash(p): p for p in view["prices"]}
        for batch in sorted(view["batches"], key=lambda b: b.get("recordedOrder", 0)):
            _verify_batch(batch, identity)
            frozen = [
                prices[k] for k in batch.get("priceScheduleIds", []) if k in prices
            ]
            _add_variants(
                variants, batch["observations"], frozen, batch.get("observationKeys")
            )
        return variants

    @classmethod
    def keys_for(cls, rows):
        return [
            {
                "observationId": cls.observation_id(row),
                "sourceDigest": content_hash(row),
            }
            for row in rows
        ]

    def correct(self, observation_id, action, actor, reason, *, selected=None):
        _validate_correction_target(
            self._variants(self.capture()), observation_id, action, selected
        )
        if action == "select" and not selected:
            raise CostError("select correction requires a variant hash")
        if action == "exclude":
            selected = None
        value = {
            "schemaVersion": "1.0.0",
            "correctionId": str(uuid4()),
            "observationId": observation_id,
            "action": action,
            "actor": actor,
            "reason": reason,
            "selected": selected,
            "createdAt": now_iso(),
            "supersedes": [
                v["correctionId"]
                for v in self.documents("corrections")
                if v["observationId"] == observation_id
            ],
        }
        validate("correction", value)
        result = self.publish(f"corrections/{value['correctionId']}.json", value)
        self.amend_if_closed()
        return result



    def amend_if_closed(self):
        snapshots = self.documents("snapshots")
        if any(s.get("lifecycle") in {"final", "amendment"} for s in snapshots):
            from avo.costs import summarize

            self.snapshot(summarize(self), "amendment")

    def price(self, value):
        validate("price", value)
        identity = ("model", "serviceProvider", "effectiveAt", "dimensions")
        for previous in self.documents("prices"):
            if (
                all(previous.get(k) == value.get(k) for k in identity)
                and previous != value
            ):
                raise CostError(
                    "conflicting price schedule; use an explicit new effective date"
                )
        key = content_hash(value)
        self.publish(f"prices/{key}.json", value)
        return key

    def snapshot(self, report, stage, *, closure=None):
        if stage not in {"working", "draft", "final", "amendment"}:
            raise CostError("invalid cost snapshot stage")
        if stage == "final" and not closure:
            raise CostError("final cost snapshot requires verified cleanup evidence")
        membership = report["membership"]
        value = {
            **report,
            "lifecycle": stage,
            "membership": membership,
            "closureEvidence": closure,
        }
        value.pop("snapshotId", None)
        value.pop("recordedOrder", None)
        # Generation time does not create a new logical snapshot.
        key = content_hash(value)
        target = self.path(f"snapshots/{key}.json")
        if target.is_file():
            return validate("snapshot", read_json(target))
        value["snapshotId"] = key
        value["recordedOrder"] = time.time_ns()
        validate("snapshot", value)
        return self.publish(f"snapshots/{key}.json", value)


    def bind(
        self,
        *,
        source,
        agent,
        session_id,
        boundary,
        source_format="normalized",
        run_id=None,
        phase=None,
    ):
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise CostError("bound usage source is unavailable")
        from avo.cost_history import assert_binding_available, remember

        assert_binding_available(self, path, session_id, boundary)
        value = {
            "schemaVersion": "1.0.0",
            "bindingId": str(uuid4()),
            "source": str(path),
            "agent": agent,
            "sourceSessionId": session_id,
            "boundary": boundary,
            "format": source_format,
            "createdAt": now_iso(),
        }
        if run_id:
            value["runId"] = run_id
        if phase:
            value["phase"] = phase
        validate("binding", value)
        self.publish(f"bindings/{value['bindingId']}.json", value)
        remember(self)
        return value

    def _bind(
        self, *, source, agent, session_id, boundary, source_format, run_id, phase
    ):
        path = Path(source).expanduser().resolve()
        requested = {
            "source": str(path),
            "agent": agent,
            "sourceSessionId": session_id,
            "boundary": boundary,
            "format": source_format,
        }
        for previous in self.documents("bindings"):
            if all(previous.get(k) == v for k, v in requested.items()):
                return self.resolve_binding(previous["bindingId"])
        if not path.is_file():
            raise CostError("bound usage source is unavailable")
        from avo.cost_history import assert_binding_available, remember

        assert_binding_available(self, path, session_id, boundary)
        value = {
            "schemaVersion": "1.0.0",
            "bindingId": str(uuid4()),
            "source": str(path),
            "agent": agent,
            "sourceSessionId": session_id,
            "boundary": boundary,
            "format": source_format,
            "createdAt": now_iso(),
        }
        if run_id:
            value["runId"] = run_id
        if phase:
            value["phase"] = phase
        validate("binding", value)
        self.publish(f"bindings/{value['bindingId']}.json", value)
        remember(self)
        return value

    def resolve_binding(self, binding_id, *, bindings=None):
        records = self.documents("bindings") if bindings is None else bindings
        return _binding_projection(binding_id, records)

    def close_binding(self, binding_id, end_boundary):
        bindings = self.documents("bindings")
        binding = next((v for v in bindings if v["bindingId"] == binding_id), None)
        if not binding or binding.get("supersedesBindingId"):
            raise CostError("unknown cost binding")
        value = {
            **binding,
            "bindingId": str(uuid4()),
            "supersedesBindingId": binding_id,
            "endBoundary": end_boundary,
            "createdAt": now_iso(),
        }
        validate("binding", value)
        return self.publish(f"bindings/{value['bindingId']}.json", value)

    def _close_binding(self, binding_id, end_boundary):
        self.assert_writable()
        bindings = self.documents("bindings")
        resolved = self.resolve_binding(binding_id, bindings=bindings)
        if resolved.get("endBoundary"):
            if resolved["endBoundary"] != end_boundary:
                raise CostError(
                    "a closed cost binding cannot widen or change its recorded scope"
                )
            return _closed_binding_record(bindings, resolved["bindingId"], end_boundary)
        binding = next((v for v in bindings if v["bindingId"] == binding_id), None)
        if not binding or binding.get("supersedesBindingId"):
            raise CostError("unknown cost binding")
        value = {
            **binding,
            "bindingId": str(uuid4()),
            "supersedesBindingId": binding_id,
            "endBoundary": end_boundary,
            "createdAt": now_iso(),
        }
        validate("binding", value)
        return self.publish(f"bindings/{value['bindingId']}.json", value)

    def export(self, destination):
        target = CostStore(destination, archive=True)
        if not self.identity():
            return
        target.publish("identity.json", self.identity())
        for kind in ("bindings", "batches", "prices", "corrections", "snapshots"):
            for value in self.documents(kind):
                validate(
                    {
                        "bindings": "binding",
                        "batches": "batch",
                        "prices": "price",
                        "corrections": "correction",
                        "snapshots": "snapshot",
                    }[kind],
                    value,
                )
                key = value.get(
                    {
                        "bindings": "bindingId",
                        "batches": "batchId",
                        "corrections": "correctionId",
                        "snapshots": "snapshotId",
                        "prices": "priceId",
                    }[kind],
                    content_hash(value),
                )
                target.publish(f"{kind}/{key}.json", value)








def _cost_claim_lock():
    from avo import avo_state

    registry = CostStore(avo_state.state_dir() / "cost-locators", archive=True)
    return _directory_lock(registry.path("exclusive-claims.lock"), attempts=3000)


def _remember_claim_store(store):
    from avo.cost_history import remember

    remember(store)


def _packet_claims(packet):
    return [
        (item["key"], item["attribution"]["scope"])
        for item in packet["evidence"]
        if item["attribution"]["status"] == "assigned"
    ]


def _other_claim_stores(store):
    from avo.cost_history import _history_sources

    owner = store.identity()["accountingVideoId"]
    selected = {}
    for candidate in _history_sources(store, include_provider_exports=False):
        try:
            identity = candidate.identity()
        except (OSError, CostError, ValueError):
            continue
        if not identity or identity["accountingVideoId"] == owner:
            continue
        key = identity["accountingVideoId"]
        if _prefer_claim_copy(selected.get(key), candidate):
            selected[key] = (candidate, identity)
    yield from selected.values()


def _prefer_claim_copy(previous, candidate):
    return previous is None or (
        previous[0].portable_status() is not None
        and candidate.portable_status() is None
    )


def _batch_claim_keys(batch):
    if batch.get("schemaVersion", "1.0.0") == "1.0.0":
        return batch.get("observationKeys", CostStore.keys_for(batch["observations"]))
    return [
        item["key"]
        for item in batch.get("evidence", [])
        if item["attribution"]["status"] == "assigned"
    ]


def _prior_claims(candidate, identity, requested):
    result = []
    for batch in candidate.documents("batches"):
        keys = [
            key for key in _batch_claim_keys(batch) if key["observationId"] in requested
        ]
        if keys:
            _verify_batch(batch, identity)
            result.extend(keys)
    return result


def _active_allocations(decisions):
    superseded = {identity for item in decisions for identity in item["supersedes"]}
    return [
        allocation
        for item in decisions
        if item["relation"] == "allocation"
        and item["reconciliationId"] not in superseded
        for allocation in item.get("allocations", [])
    ]


def _allocated_key(reference, known):
    record = known.get(reference["id"], {})
    return reference.get("key", record.get("key"))


def _claim_destinations(candidate, key):
    if candidate.portable_status() is not None:
        return set()
    known = candidate.references()
    return {
        (item["accountingVideoId"], content_hash(item["scope"]))
        for item in _active_allocations(candidate.documents("reconciliations"))
        if _allocated_key(item["reference"], known) == key
    }


def _follow_claim_transfer(candidate, key, owner, scope_digest, stores, visited):
    while candidate.identity()["accountingVideoId"] not in visited:
        visited.add(candidate.identity()["accountingVideoId"])
        choices = _claim_destinations(candidate, key)
        if len(choices) != 1:
            return False
        destination, declared_scope = next(iter(choices))
        if destination == owner:
            return declared_scope == scope_digest
        candidate = stores.get(destination)
        if candidate is None:
            return False
    return False


def _registered_claim_store(owner):
    from avo import avo_state

    for path in (avo_state.state_dir() / "cost-locators").glob("*.json"):
        try:
            locator = read_json(path)
        except (OSError, ValueError):
            continue
        if locator.get("accountingVideoId") == owner:
            return CostStore(locator["rawDir"], archive=locator.get("archive", False))
    return None


def _allocation_unchanged(record, allocation, known):
    if record["relation"] != "allocation":
        return False
    key = _allocated_key(allocation["reference"], known)
    return any(
        _allocated_key(item["reference"], known) == key
        and item["accountingVideoId"] == allocation["accountingVideoId"]
        and item["scope"] == allocation["scope"]
        for item in record.get("allocations", [])
    )


def _transfer_returned(store, allocation, scope, known):
    owner = store.identity()["accountingVideoId"]
    destination = allocation["accountingVideoId"]
    if destination == owner:
        return True
    target = _registered_claim_store(destination)
    if target is None:
        return True
    if not target.identity():
        raise CostError(
            "consumed transfer authority is unavailable; retain its allocation"
        )
    key = _allocated_key(allocation["reference"], known)
    claims = _prior_claims(target, target.identity(), {key["observationId"]})
    if not claims:
        return True
    return _claim_destinations(target, key) == {(owner, content_hash(scope))}


def _validate_transfer_supersession(store, record, view):
    known = store.references(view)
    previous = {item["reconciliationId"]: item for item in view["reconciliations"]}
    for identity in record["supersedes"]:
        decision = previous[identity]
        for allocation in decision.get("allocations", []):
            if _allocation_unchanged(record, allocation, known):
                continue
            reference = known[allocation["reference"]["id"]]
            scope = reference.get("attribution", {}).get("scope", decision["scope"])
            if not _transfer_returned(store, allocation, scope, known):
                raise CostError(
                    "consumed cost transfer requires an exact audited reverse allocation"
                )


def _claim_transferred(candidate, old_key, incoming, owner):
    key, scope = incoming
    if key != old_key or scope is None:
        return False
    stores = {
        identity["accountingVideoId"]: item
        for item, identity in _other_claim_stores(candidate)
    }
    return _follow_claim_transfer(
        candidate, key, owner, content_hash(scope), stores, set()
    )


def _assert_exclusive_claims(store, claims):
    if not claims:
        return
    requested = {}
    for key, scope in claims:
        requested.setdefault(key["observationId"], []).append((key, scope))
    owner = store.identity()["accountingVideoId"]
    for candidate, identity in _other_claim_stores(store):
        for previous in _prior_claims(candidate, identity, requested):
            if not all(
                _claim_transferred(candidate, previous, current, owner)
                for current in requested[previous["observationId"]]
            ):
                raise CostError(
                    "native cost activity is already assigned to another production; "
                    "use an exact audited allocation or retain unallocated evidence"
                )


def _is_storage_link(path):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x400
    )


@contextmanager
def _directory_lock(lock, *, attempts=200):
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(attempts):
        try:
            lock.mkdir()
            break
        except (FileExistsError, PermissionError):
            time.sleep(0.01)
    else:
        raise CostError(
            "cost operation locked or unavailable; retry without changing its operation ID"
        )
    try:
        yield
    finally:
        lock.rmdir()


def _verify_batch(batch, identity):
    payload = {k: v for k, v in batch.items() if k != "contentHash"}
    if batch.get("contentHash") != content_hash(payload):
        raise CostError("cost batch integrity verification failed")
    if not identity or batch.get("accountingVideoId") != identity["accountingVideoId"]:
        raise CostError("cost batch belongs to another video")


def _new_rows(rows, batches):
    existing = {content_hash(row) for batch in batches for row in batch["observations"]}
    return [row for row in rows if content_hash(row) not in existing]


def _validate_correction_target(variants, key, action, selected):
    if key not in variants:
        raise CostError("correction references an unknown usage observation")
    if action == "select" and selected not in variants[key]:
        raise CostError("correction references an unknown source variant")


def _add_variants(variants, rows, prices, keys=None):
    keys = keys if keys is not None else CostStore.keys_for(rows)
    if len(keys) != len(rows):
        raise CostError("cost batch observation keys are incomplete")
    for row, metadata in zip(rows, keys):
        key = metadata["observationId"]
        versions = variants.setdefault(key, {})
        versions.setdefault(metadata["sourceDigest"], (row, prices))


def _decisions(corrections):
    decisions = {}
    superseded = {
        key for correction in corrections for key in correction.get("supersedes", [])
    }
    for correction in corrections:
        if correction["correctionId"] in superseded:
            continue
        decisions.setdefault(correction["observationId"], set()).add(
            correction.get("selected")
        )
    return decisions


def _resolve_variants(variants, decisions):
    result, diagnostics = [], []
    for key, versions in variants.items():
        selected = decisions.get(key)
        if selected:
            versions = {k: v for k, v in versions.items() if k in selected}
        if len(versions) == 1:
            row, prices = next(iter(versions.values()))
            result.append({**row, "observationId": key, "_prices": prices})
        elif versions or (selected and selected != {None}):
            diagnostics.append(
                {
                    "code": "conflicting-observation",
                    "observationId": key,
                    "variants": sorted(versions),
                }
            )
    return result, diagnostics


def _record_digest(value, field):
    return content_hash(
        {k: v for k, v in value.items() if k not in {field, "recordedOrder"}}
    )


def _binding_root(binding_id, records):
    visited = set()
    while binding_id in records:
        if binding_id in visited:
            raise CostError("cost binding lineage contains a cycle")
        visited.add(binding_id)
        value = records[binding_id]
        if not value.get("supersedesBindingId"):
            return value
        binding_id = value["supersedesBindingId"]
    raise CostError("unknown cost binding lineage")


def _binding_family(root, records):
    family = {root["bindingId"]: root}
    while True:
        added = {
            key: value
            for key, value in records.items()
            if value.get("supersedesBindingId") in family and key not in family
        }
        if not added:
            return family
        family.update(added)


def _closed_binding_record(bindings, root_id, end_boundary):
    records = {b["bindingId"]: b for b in bindings}
    family = _binding_family(records[root_id], records)
    closed = [b for b in family.values() if b.get("endBoundary") == end_boundary]
    return min(closed, key=lambda b: b["bindingId"])


def _binding_projection(binding_id, bindings):
    records = {b["bindingId"]: b for b in bindings}
    root = _binding_root(binding_id, records)
    family = _binding_family(root, records)
    _validate_binding_family(root, family)
    superseded = {v.get("supersedesBindingId") for v in family.values()}
    endings = {v.get("endBoundary") for k, v in family.items() if k not in superseded}
    if len(endings) != 1:
        raise CostError("cost binding has divergent scope successors")
    result = deepcopy(root)
    ending = endings.pop()
    if ending is not None:
        result["endBoundary"] = ending
    return result


def _validate_binding_family(root, family):
    immutable = (
        "source",
        "agent",
        "sourceSessionId",
        "boundary",
        "format",
        "runId",
        "phase",
    )
    for value in family.values():
        if any(value.get(k) != root.get(k) for k in immutable):
            raise CostError(
                "cost binding supersession changes its authorized source or scope"
            )
        parent = family.get(value.get("supersedesBindingId"))
        if (
            parent
            and parent.get("endBoundary")
            and parent.get("endBoundary") != value.get("endBoundary")
        ):
            raise CostError(
                "cost binding supersession cannot widen or reinterpret closed scope"
            )


def _verify_record(kind, value):
    _, field = RECORD_TYPES[kind]
    if value[field] != _record_digest(value, field):
        raise CostError("cost record integrity verification failed")


def _record_owner(value, identity):
    if (
        not identity
        or value.get("accountingVideoId", identity["accountingVideoId"])
        != identity["accountingVideoId"]
    ):
        raise CostError("cost evidence belongs to another production")


def _operation_record(records, operation):
    return next(
        (
            item
            for item in records
            if operation and item.get("operationId") == operation
        ),
        None,
    )


def _packet_replay(batch, packet):
    if any(batch.get(k) != v for k, v in packet.items()):
        raise CostError("cost operation replay conflicts with accepted content")
    return {
        "status": "ok",
        "imported": 0,
        "batchId": batch["batchId"],
        "replayed": True,
    }


def _validate_packet(packet, view, allow_synthetic):
    profiles = {p["profileId"]: p for p in view["profiles"]}
    profile = profiles.get(packet["profileId"])
    if profile is None:
        raise CostError("cost packet references an unknown source profile")
    keys = CostStore.keys_for(packet["observations"])
    metadata = packet["evidence"]
    if len(keys) != len(metadata) or keys != [item["key"] for item in metadata]:
        raise CostError("cost packet requires one-to-one observation evidence")
    if not keys and not packet["receipts"]:
        raise CostError("empty cost packet requires a meaningful collection receipt")
    facts = _packet_participations(view)
    for row, item in zip(packet["observations"], metadata):
        _validate_packet_evidence(row, item, profile, facts, allow_synthetic)
    _validate_receipts(packet, view, _accepted_rows(packet, view))


def _declared_participations(view):
    return {
        fact["participationId"]: fact
        for fact in view["participations"]
        if fact["kind"] in {"declare", "declare-no-external-agent"}
    }


def _packet_participations(view):
    from avo.cost_participation import project_participation_facts

    records = view["participations"]
    current = project_participation_facts(records)["participations"]
    return {
        "records": {fact["factId"]: fact for fact in records},
        "current": {fact["participationId"]: fact for fact in current},
        "historical": {},
    }


def _historical_participation(facts, reference, participation_id):
    from avo.cost_participation import project_participation_facts

    target = facts["records"].get(reference)
    if target is None or target["participationId"] != participation_id:
        raise CostError("cost evidence references an unknown participation fact")
    if reference not in facts["historical"]:
        selected = {}
        pending = [reference]
        while pending:
            identity = pending.pop()
            if identity not in selected:
                fact = facts["records"][identity]
                selected[identity] = fact
                pending.extend(fact["predecessors"])
        projected = project_participation_facts(list(selected.values()))
        facts["historical"][reference] = next(
            item
            for item in projected["participations"]
            if item["participationId"] == participation_id
        )
    return facts["historical"][reference]


def _evidence_participation(item, facts):
    identity = item["participationId"]
    reference = item.get("participationFactId")
    fact = (
        _historical_participation(facts, reference, identity)
        if reference
        else facts["current"].get(identity)
    )
    if fact is None:
        raise CostError("cost packet has no declared host participation")
    if fact["conflicted"] or len(fact["frontier"]) != 1:
        raise CostError("cost evidence requires an unambiguous participation fact")
    return fact


def _accepted_rows(packet, view):
    result = {}
    for batch in view["batches"]:
        _verify_batch(batch, {"accountingVideoId": packet["accountingVideoId"]})
        keys = batch.get("observationKeys", CostStore.keys_for(batch["observations"]))
        result.update(
            (content_hash(k), row) for k, row in zip(keys, batch["observations"])
        )
    result.update(
        (content_hash(k), row)
        for k, row in zip(
            CostStore.keys_for(packet["observations"]), packet["observations"]
        )
    )
    return result


def _validate_packet_evidence(row, item, profile, facts, allow_synthetic):
    from avo.cost_participation import evidence_id
    from avo.cost_profiles import profile_status

    if item["profileId"] != profile["profileId"] or item["evidenceId"] != evidence_id(
        item
    ):
        raise CostError("cost packet evidence identity/profile mismatch")
    if item["interval"]["sourceSessionId"] != row["sourceSessionId"]:
        raise CostError("cost packet evidence has a different source session")
    version = _evidence_version(row, item, profile, facts)
    if (
        item["nature"] == "measured"
        and profile_status(profile, version=version, allow_synthetic=allow_synthetic)
        != "qualified"
    ):
        raise CostError(
            "source profile is not qualified for measured usage; use an explicit fallback"
        )
    _profile_counter_semantics(row, profile)


def _evidence_version(row, item, profile, facts):
    if row["agent"] != profile["agent"]:
        raise CostError("cost observation agent does not match its source profile")
    if row["serviceClass"] == "host-agent":
        fact = _evidence_participation(item, facts)
        version = _host_evidence_version(row, fact, profile)
    else:
        if not item["participationId"].startswith("pipeline-service:"):
            raise CostError("cost service evidence requires an explicit service scope")
        version = row["agentVersion"]
    return version


def _host_evidence_version(row, fact, profile):
    version = fact.get("agent", {}).get("version")
    if fact.get("agent", {}).get("family") != profile["agent"]:
        raise CostError("cost packet profile does not match the declared host")
    if version is not None and row["agentVersion"] != version:
        raise CostError(
            "cost observation version does not match its participation fact"
        )
    _validate_evidence_scope(row, fact.get("scope", {}))
    return version


def _validate_evidence_scope(row, scope):
    for field in ("sourceInstanceId", "sourceSessionId", "counterEpoch"):
        if field == "counterEpoch" and scope.get(field) is None:
            continue
        if field in scope and scope[field] != row.get(field):
            raise CostError("cost packet observation is outside the declared scope")


def _profile_counter_semantics(row, profile):
    semantics = profile["semantics"]
    counter = semantics["counter"]
    if (
        counter in {"request", "cumulative"}
        and row.get("measurementKind", "request") != counter
    ):
        raise CostError("cost observation counter semantics do not match its profile")
    for category, relation in semantics["categoryOverlap"].items():
        if (
            category in row["tokens"]
            and row["semantics"].get(category, "unknown") != relation
        ):
            raise CostError("cost observation categories do not match its profile")


def _validate_receipts(packet, view, known_rows):
    receipts = {
        r["receiptId"]: r for b in view["batches"] for r in b.get("receipts", [])
    }
    receipts.update({r["receiptId"]: r for r in packet["receipts"]})
    bindings = {b["bindingId"] for b in view["bindings"]}
    for receipt in packet["receipts"]:
        _validate_receipt(receipt, packet["profileId"], bindings, known_rows)
        _validate_receipt_lineage(receipt, receipts)


def _validate_receipt(receipt, profile_id, bindings, known_rows):
    if receipt["profileId"] != profile_id or receipt["receiptId"] != _record_digest(
        receipt, "receiptId"
    ):
        raise CostError("cost receipt identity/profile mismatch")
    if receipt["bindingId"] is not None and receipt["bindingId"] not in bindings:
        raise CostError("cost receipt references an unknown binding")
    for key in receipt["observationKeys"]:
        row = known_rows.get(content_hash(key))
        if row is None:
            raise CostError("cost receipt advances past unaccepted evidence")
        fields = ("sourceInstanceId", "sourceSessionId", "counterEpoch")
        if any(receipt[field] != row.get(field) for field in fields):
            raise CostError("cost receipt crosses observation source scope")


def _validate_receipt_lineage(receipt, receipts):
    previous = receipts.get(receipt["predecessorReceiptId"])
    if receipt["predecessorReceiptId"] and previous is None:
        raise CostError("cost receipt references an unknown predecessor")
    fields = ("profileId", "sourceInstanceId", "sourceSessionId", "counterEpoch")
    if previous and any(previous[k] != receipt[k] for k in fields):
        raise CostError("cost receipt predecessor crosses source scope")


def _receipt_conflicts(batches):
    branches = {}
    for batch in batches:
        for receipt in batch.get("receipts", []):
            key = (
                receipt["profileId"],
                receipt["sourceInstanceId"],
                receipt["sourceSessionId"],
                receipt["counterEpoch"],
                receipt["predecessorReceiptId"],
            )
            branches.setdefault(key, set()).add(receipt["receiptId"])
    return [
        {"code": "receipt-predecessor-conflict", "receiptIds": sorted(ids)}
        for ids in branches.values()
        if len(ids) > 1
    ]

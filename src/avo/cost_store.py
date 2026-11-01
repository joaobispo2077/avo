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










































def _is_storage_link(path):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & 0x400
    )




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



















































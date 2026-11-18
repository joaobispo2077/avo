"""Optional revision-bound audio/text similarity; catalogue policy stays upstream."""

from __future__ import annotations

import math
from pathlib import Path

from avo.capabilities import optional_embedding_capability
from avo.embedding_manifest import EmbeddingError, contained_file, read_bounded_json
from avo.timeline.contracts import content_hash, file_fingerprint
from avo.timeline.store import atomic_write_json


def _vector(value, dimension):
    import numpy as np

    if (
        not isinstance(value, list)
        or len(value) != dimension
        or any(type(x) not in {int, float} or not math.isfinite(x) for x in value)
    ):
        raise EmbeddingError("embedding vector has invalid finite numeric dimensions")
    vector = np.asarray(value, dtype=np.float64)
    if not math.isclose(float(np.linalg.norm(vector)), 1.0, rel_tol=1e-5, abs_tol=1e-5):
        raise EmbeddingError("embedding vector is not L2-normalized")
    return vector


def _vectors(result, identity, count):
    if not isinstance(result, dict) or result.get("jointSpace") != identity:
        raise EmbeddingError("encoder returned an incompatible joint-space identity")
    vectors = result.get("vectors")
    if not isinstance(vectors, list) or len(vectors) != count:
        raise EmbeddingError("encoder returned an incompatible vector count")
    return [_vector(value, identity["dimension"]) for value in vectors]


def _selected_entries(document, request):
    query, selected = request["query"], request["entryIds"]
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 512:
        raise EmbeddingError("semantic query must contain 1..512 characters")
    if (
        not isinstance(selected, list)
        or len(selected) > 5000
        or len(set(selected)) != len(selected)
    ):
        raise EmbeddingError("semantic selection exceeds its entry budget")
    return query, _current_entries(document, selected)


def _current_entries(document, selected):
    entries = document["entries"]
    if len(entries) > 5000:
        raise EmbeddingError("semantic generation exceeds its entry budget")
    indexed = {entry["entryId"]: entry for entry in entries}
    if len(indexed) != len(entries) or any(key not in indexed for key in selected):
        raise EmbeddingError("semantic request contains stale or duplicate entry IDs")
    return [indexed[key] for key in selected]


class SemanticSoundRanker:
    """Rank only catalogue-selected IDs. No backend means explicit unavailable."""

    def __init__(self, workspace, *, roots, encoder=None):
        self.workspace = workspace
        self.roots = {key: Path(path) for key, path in roots.items()}
        self.encoder = encoder

    def _cache_directory(self):
        root = Path(self.workspace.raw_dir).resolve()
        directory = root / "edit" / "sfx" / "embeddings"
        if not directory.resolve().is_relative_to(root):
            raise EmbeddingError("embedding cache escapes the project edit tree")
        return directory

    def _source(self, entry):
        source = entry["source"]
        if source["state"] != "available" or source["sizeBytes"] > 512 * 1024 * 1024:
            raise EmbeddingError(
                "embedding source is unavailable or exceeds its byte budget"
            )
        root = self.roots.get(entry["libraryId"])
        if root is None:
            raise EmbeddingError("embedding source library is not declared")
        path = contained_file(root, entry["relativePath"])
        actual = file_fingerprint(path)
        if (
            actual["sha256"] != source["sha256"]
            or actual["sizeBytes"] != source["sizeBytes"]
        ):
            raise EmbeddingError(
                "embedding source digest changed since catalogue generation"
            )
        return path

    def _binding(self, document, entry, identity):
        return {
            "generationId": document["generationId"],
            "entryId": entry["entryId"],
            "entryRevision": entry["entryRevision"],
            "sourceSha256": entry["source"]["sha256"],
            "jointSpace": identity,
        }

    def _cached(self, directory, binding, dimension):
        path = directory / f"{content_hash(binding)}.json"
        if not path.exists():
            return None
        if not path.resolve().is_relative_to(directory.resolve()):
            raise EmbeddingError("embedding cache entry escapes its root")
        try:
            record = read_bounded_json(path, limit=128 * 1024)
            if record.get("binding") == binding and record.get(
                "sha256"
            ) == content_hash({"binding": binding, "vector": record["vector"]}):
                return _vector(record["vector"], dimension)
        except (EmbeddingError, OSError, KeyError, TypeError, AttributeError):
            pass
        return None

    def _audio_vectors(self, document, entries, identity):
        directory = self._cache_directory()
        found, pending = {}, []
        for entry in entries:
            path = self._source(entry)
            binding = self._binding(document, entry, identity)
            vector = self._cached(directory, binding, identity["dimension"])
            if vector is None:
                pending.append((entry, path, binding))
            else:
                found[entry["entryId"]] = vector
        for offset in range(0, len(pending), 16):
            batch = pending[offset : offset + 16]
            items = [
                {"path": str(path), "sha256": entry["source"]["sha256"]}
                for entry, path, _ in batch
            ]
            vectors = _vectors(
                self.encoder.encode("audio", items), identity, len(batch)
            )
            for (entry, _path, binding), vector in zip(batch, vectors, strict=True):
                self._source(entry)
                directory = self._cache_directory()
                directory.mkdir(parents=True, exist_ok=True)
                record = {"binding": binding, "vector": vector.tolist()}
                atomic_write_json(
                    directory / f"{content_hash(binding)}.json",
                    {**record, "sha256": content_hash(record)},
                )
                found[entry["entryId"]] = vector
        return found

    def rank(self, document, request):
        if self.encoder is None:
            return {
                "status": "unavailable",
                "scores": [],
                "warnings": [
                    "Semantic mode needs an explicitly provisioned local audio/text encoder; select descriptor mode separately."
                ],
            }
        try:
            query, entries = _selected_entries(document, request)
            readiness = optional_embedding_capability(self.encoder)
            if readiness["status"] != "ready":
                raise EmbeddingError(readiness["reason"])
            identity = readiness["jointSpace"]
            text = _vectors(self.encoder.encode("text", [query]), identity, 1)[0]
            vectors = self._audio_vectors(document, entries, identity)
            scores = [
                {
                    "entryId": entry["entryId"],
                    "entryRevision": entry["entryRevision"],
                    "score": max(
                        -1.0, min(1.0, float(vectors[entry["entryId"]] @ text))
                    ),
                }
                for entry in entries
            ]
            return {
                "status": "ready",
                "jointSpace": identity,
                "scores": scores,
                "warnings": [],
            }
        except (
            EmbeddingError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            RecursionError,
        ) as exc:
            return {
                "status": "unavailable",
                "scores": [],
                "warnings": [
                    f"Semantic mode unavailable: {exc}; select descriptor mode separately."
                ],
            }


def build_semantic_backend(workspace, roots, *, root=None, invocation=None):
    """Compose only for an explicit semantic operation; loading waits until rank."""
    from avo.adapters.understand.clap_embeddings import LocalClapEncoder
    from avo.model_sources import resolve_job

    project = workspace.project
    provider = str(project.get("provider") or "")
    video_key = f"{provider}:{workspace.video_id}" if provider else None
    jobs = [
        resolve_job(
            job,
            root=root,
            project=project,
            video_key=video_key,
            invocation=(invocation or {}).get(job),
        )
        for job in ("audio_embed", "text_embed")
    ]
    return SemanticSoundRanker(workspace, roots=roots, encoder=LocalClapEncoder(*jobs))

"""Explicit library preservation coverage, independent of media admission."""

from __future__ import annotations

from avo.library.rules import read_request, reject, safe_path
from avo.library.store import LibraryStore

PERSISTENT = (
    "inventory",
    "recordings",
    "proposals",
    "prepared",
    "decisions",
    "operations",
    "batches",
    "transcripts",
    "handoffs",
    "reports",
)


def bound_store(root):
    path = safe_path(root, "edit/library-index.json")
    if not path.exists():
        return None
    head = read_request(path)
    store = LibraryStore(root, head.get("provider"))
    store.head()
    return store


def retention_plan(root):
    store = bound_store(root)
    if store is None:
        return {"requiredPaths": [], "estimatedBytes": 0, "missingPaths": []}
    required = ["edit/library-index.json"]
    required.extend(
        f"edit/library/{name}"
        for name in PERSISTENT
        if store.path(f"edit/library/{name}").exists()
    )
    declared = _declared(store)
    files = [p for relative in required for p in _files(store, relative)]
    return {
        "requiredPaths": required,
        "estimatedBytes": sum(p.stat().st_size for p in files),
        "missingPaths": [p for p in required if p not in declared],
    }


def _declared(store):
    project = store.path("avo.project.json")
    return (
        (read_request(project).get("cleanup") or {}).get("preservePaths", [])
        if project.exists()
        else []
    )


def _files(store, relative):
    path = store.path(relative)
    candidates = [path] if path.is_file() else list(path.rglob("*"))
    files = []
    for item in candidates:
        checked = store.path(item.relative_to(store.root).as_posix())
        if checked.is_file():
            if checked.stat().st_nlink != 1:
                reject("LIB_ROOT_UNSAFE", "Library metadata cannot be hardlinked")
            files.append(checked)
    return files


def library_paths(root):
    store = bound_store(root)
    if store is None:
        return []
    plan = retention_plan(root)
    if plan["missingPaths"]:
        reject(
            "LIB_RETENTION_REQUIRED",
            "Review exact library retention paths before cleanup",
            "conflict",
        )
    return [p for relative in plan["requiredPaths"] for p in _files(store, relative)]


def library_sources(root):
    store = bound_store(root)
    if store is None:
        return []
    head = store.head()
    inventory = (
        store.get(head["inventoryRef"]) if head["inventoryRef"] else {"recordings": []}
    )
    return [
        store.path(r["path"])
        for r in inventory["recordings"]
        if r["availability"] != "missing" and store.path(r["path"]).is_file()
    ]

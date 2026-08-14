# Timeline fixtures

Small, synthetic fixtures for canonical CMap, BMap, tracks, animation, sync,
review, migration, and projection tests live here. Fixtures must not reference
private footage or depend on project-specific helper scripts.

Rules:

- raw inputs use stable fake SHA-256 identities;
- canonical times use integer ticks and rational timebases;
- approvals bind exact revision, dependency, output, and candidate hashes;
- invalid fixtures state the single contract rule they intentionally violate.

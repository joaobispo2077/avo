# Synthetic OTIO fixtures

These tiny, hand-authored examples contain no private media, source paths or creator content. `file:///originals/` is a deliberately nonexistent reference. Inspecting these files must not attempt to open it.

- `clip-v1.otio`: one Timeline.1, one Stack.1, one Video Track.1, one Clip.1, one ExternalReference.1, 24 fps, nonzero timeline/media origins.
- `clip-v2.otio`: one Timeline.1, one Video track, two Clip.2 occurrences of one reference, explicit active media key and an inactive reference; 30000/1001 rate evidence is decimal and remains unverified during inspection.
- Collections, unsupported objects, hostile metadata and malformed limits are derived in tests without adding footage.

Fixtures prove structural behavior only. An actual Resolve-exported sample must be qualified separately before claiming interoperability.

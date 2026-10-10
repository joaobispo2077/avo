# Cutting fixtures

`tests/cutting_fixtures.py` generates original WAV tones and quiet guards in
pytest temporary external workspaces. These synthetic signals test routing,
clocks, envelopes and provenance; they are not human speech or intelligibility
ground truth. Tests that need picture generate media through FFmpeg and record
the exact inputs. No downloaded or private media is stored here.

Canonical fixtures use declared dialogue channels and explicitly approved Sync
N/A. Public speech evaluation requires authorized recordings and independently
annotated evidence. Private historical footage and its case inventory remain in
the footage project's external edit directory.

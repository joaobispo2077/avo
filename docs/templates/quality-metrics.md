# Quality metrics snapshot

`docs/quality-metrics.md` is not maintained by hand. The release cut
(`.github/workflows/release.yml`) writes it from the green Software quality
artifact `quality-metrics` for the exact tip SHA.

The cut fails when that JSON is missing, not overall PASS, or bound to a
different SHA. It does not re-run gates and does not reuse the previous
release's numbers. Ordinary pull requests do not write the file.

Optional PNGs land in `docs/quality/charts/<version>/` only at the cut. If
they ship, their embedded series must match the JSON and the tables.

Mutation is a kill rate only when that cut's mutation JSON includes `killed`
and `survived` for the same SHA. Otherwise the file shows — and points at
the Mutation sticky. The snapshot does not invent a score, and it does not
change floors or gates.

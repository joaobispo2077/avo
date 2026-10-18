# Metric meaning and fixed behavior

These reviewed source fixtures describe semantics, effective policy and small fixed examples. They are separate from generated run/release evidence and image pixels. Production never reads these expectations; ordinary tests only read them.

`definitions.json` records all published measurement IDs plus file coupling and testcase events. `policy.json` records currently resolved configuration: coverage 68 with default precision 0, duplication ceiling 2, mutation light 40/full 50. Runtime reports retain only their own frozen applicable policy; policy-only edits do not automatically change calculation revisions.

The case expectations were derived independently:

- Coverage is covered/total times 100; 169/250 is 67.6. The frozen zero-decimal gate accepts it as 68 while its raw band remains red. Minimum yellow ends at 68 + 0.25 * 32 = 76.
- Duplication is duplicated/total times 100. The green boundary is 0.75 * 2 = 1.5; the maximum remains 2. Inconsistent reported percentages are unavailable.
- Mutation uses killed/(killed+survived) only after complete accounting. 2/5 is 40%; each unresolved category or remainder withholds the score.
- CRAP is CC² times uncovered fraction cubed plus CC: 6/0% gives 42, 10/50% gives 22.5, and 10/100% gives 10. The toy callable has CC 2, covers 2 of 3 statements, and scores 2 + 4/27. Floating comparisons allow only 1e-10 absolute error.
- The graph's reader imports its target twice and a namespace once, plus itself. Therefore its CE is 2, each distinct target has CA 1, and package projection has one group-to-namespace edge. Six actual files produce medians CE 0 / CA 0. Paths determine F IDs; exact coordinates determine G IDs.
- The JUnit document records five execution events across two suites, including a repeated name. It represents two passes, one failure, one error and one skip, not five unique tests. Finding counts retain their own tool/population units; six dependency operations are proposals only.

Fixed source cases execute the installed locked Radon/import collector; code-risk evidence already records tool versions. Tests preserve independent mathematical, accounting and source-integrity checks. A finite corpus cannot prove all analyzer inputs.

Only explicitly volatile publication/timestamp/run-detail fields are excluded from semantic comparisons; controlled source hashes and identity assertions remain. Scope, states, units, denominators, policy and references are never scrubbed to make comparisons pass.

Intentional changes require scoped input/result diffs, a definition revision when meaning changes, a policy diff when policy changes, and rationale with the production change in the same PR. Keep tests/fixtures, production and infrastructure in separate atomic commits under the owner's approval rules. Analyzer upgrades receive the same fixed-source checks. There is no auto-accept flag or CI baseline writer.

File-coupling definition revision 2 intentionally changes visual interpretation: four equal-area colored quadrants, centered on the same raw medians using disclosed piecewise log2(1+count) spacing, with numbered coincident groups and a file index below the plot. Raw counts, source scope, zero-degree behavior, all-file median population, equality-lower rule, stable F/G IDs and effective policy are unchanged. Colors communicate connectivity regions; they do not certify architectural health or add gates. The catalog entry is hand-edited for this change, rather than regenerated from production; fixed display cases separately detect axis behavior drift.

The independent axis cases use powers of two: counts 0, 1, 3, 7 and 15 have log2(1+count) values 0, 1, 2, 3 and 4. A raw median of 3 splits the range into two equal display halves, so their positions are 0, 0.25, 0.5, 0.75 and 1. When the median is zero, zero stays at the division and the lower numeric range is empty; count 1 with maximum 7 is at 0.5 + 0.5/3 = 2/3. A maximum at the median leaves the upper numeric range empty. Display comparisons allow only 1e-12 absolute error; count and median expectations remain exact.

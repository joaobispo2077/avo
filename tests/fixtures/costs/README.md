# Cost evidence fixtures and acceptance map

All fixtures are synthetic metadata, not private agent logs or model prices.
The seven files under agents/ exercise the normalized/manual fallback. They
do not claim native compatibility for unknown installed agent versions.
Native documented-shape cases are constructed in test_cost_sources.py from
the official source references in docs/video-cost-transparency-research.md
and feature 011 research.md. No paid inference or account keys are needed.

| Contract | Regression evidence |
| --- | --- |
| FR-001 command/alias/filtering | test_costs_cli.py, test_cost_packaging.py |
| FR-002 stable identity/ownership | test_costs.py, test_cost_contracts.py, test_session.py |
| FR-003 categories and provenance | test_costs.py, test_cost_sources.py |
| FR-004 valuation basis | test_costs.py, test_cost_invariants.py |
| FR-005 pipeline service separation | test_cost_services.py |
| FR-006 deduplication and correction | test_costs.py, test_cost_invariants.py |
| FR-007 coverage/cutoff | test_costs.py, test_cost_sources.py |
| FR-008 all-agent fallback | test_cost_contracts.py, test_cost_sources.py |
| FR-009 retained history | test_cost_closure.py, test_cost_history.py |
| FR-010 same snapshot | test_cost_closure.py, test_wrap.py, test_learndown_export.py |
| FR-011 recorded cohorts | test_cost_history.py |
| FR-012 privacy/local boundaries | test_cost_contracts.py, test_cost_services.py |
| FR-013 unknown/errors | test_costs_cli.py, test_cost_sources.py |
| FR-014 frozen prices | test_costs.py, test_cost_invariants.py |
| FR-015 no inference/editorial mutation | test_cost_packaging.py, test_costs_cli.py |
| FR-016 closing summaries | test_cost_responses.py, test_cost_closure.py |
| FR-017 model/provider switching | test_costs.py, test_cost_sources.py, test_cost_invariants.py |
| SC-001 performance | test_cost_performance.py |
| SC-002 seven agents | test_cost_contracts.py |
| SC-003 isolation/replay | test_costs.py, test_cost_invariants.py |
| SC-004 equality | test_cost_closure.py |
| SC-005 unknown/subscription | test_costs.py |
| SC-006 cleanup/history | test_cost_closure.py, test_cost_history.py |
| SC-007 zero private content | test_cost_contracts.py, test_cost_services.py |
| SC-008 automatic response/switch | test_cost_responses.py, test_costs.py |

Tests are consolidated by accounting boundary instead of creating a new file
for every task. Their scope is unchanged from feature 011 tasks.md.

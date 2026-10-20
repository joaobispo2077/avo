# Provider direction evaluation

This protocol evaluates artistic-direction proposals and Briefstart usefulness.
It does not approve an edit, transfer rights, evaluate source-media quality or
reopen a completed video. Its expected labels and observed results belong to a
private pilot, outside tracked code and completed footage projects. A
provider-owned, document-only pilot may live in the ignored/private directory
`providers/<provider>/direction/pilots/<pilot-id>/`, with no raw or media files.
An external evaluation project may instead use
`<rawDir>/edit/review/direction-pilot/`. Real video projects and source-footage
evidence stay in the external `rawDir`; their authoring records remain in
`<rawDir>/edit/briefstart/`. Storing a pilot does not activate a provider profile
or select a video's direction.

The protocol is ready; no human responses or usability results are supplied by
this document. A code test, another agent's opinion, a final historical master
or permission to implement the feature cannot supply those responses.

## Roles and evidence

- **Creator or designated human reviewer:** determines what the records mean,
  resolves artistic scope and supplies all preference decisions and usability
  responses.
- **Coordinator:** prepares the bounded evidence, records the actual response,
  executes authorized native decisions and computes results without inventing
  responses or timings.
- **Authoring agent:** creates the proposed profile/options from the permitted
  packet. It does not receive the sealed expected labels before producing its
  recommendation and cannot label its own answer as human-approved.

Keep document facts, automated validation, interpretation and human approval
separate. `final`, `active` or a historical approval of one film does not prove
that the creator adopted a provider-wide artistic preference. Missing rationale
stays unknown. A current explicit instruction may establish a preference without
recurrence, but must identify its scope and actual instruction source.

## 1. Prepare an independent case set

Before generating or showing recommendations, select at least **12 cases from
four independent source projects**. Related revisions, copied summaries and
derivative exports do not count as independent projects. Give every discovered
catalog entry a coverage disposition separately; the case sample is not a
replacement for whole-catalog coverage.

The following is a neutral sampling plan, not a set of asserted findings:

| Case | Source project | Question to adjudicate |
| --- | --- | --- |
| C01 | P01 | Is a reusable instruction actually stated, and with what scope? |
| C02 | P01 | Which choice was superseded, and which replacement was used? |
| C03 | P01 | Is an exact gain, duration or restoration value project-only? |
| C04 | P02 | Does the same technique have different appropriate contexts? |
| C05 | P02 | Does a duplicate or continuation add independent support? |
| C06 | P02 | Is the creator's rationale recorded or only inferred? |
| C07 | P03 | Is a proposed technique evidenced as actually used? |
| C08 | P03 | Is an accepted outcome also an explicit broad preference? |
| C09 | P03 | Is the rule technical prevention rather than artistic identity? |
| C10 | P04 | Does a sound/motion disagreement reflect format or section needs? |
| C11 | P04 | What can an unavailable reference support from documents alone? |
| C12 | P04 | Does authored brand direction conflict with an inferred preference? |

Replace the neutral IDs with real private source identities in the private
pilot. If a category cannot be evidenced, label the gap and select another real
case or leave the evaluation incomplete. Do not manufacture a historical
instruction to fill a category. Include additional cases when needed to cover
an explicit reusable pattern, supersession, project-only values, contextual
disagreement and duplicate learning.

Each case includes bounded context, a stable decision/recipe selector and the
small document's actual identity. No raw/master decode, media hash, playback,
transcription or fresh model analysis is required. An unavailable old preview
does not imply that its documented decision was unavailable or watched again.

## 2. Adjudicate and freeze expectations first

Present only the historical evidence to the human. Ask whether each case is an
instruction, observed choice, tentative inference, default, technical lesson or
unknown; which decisions were used/superseded; its applicability; and what the
records do not establish. Record the actual human answer, even when it disagrees
with the coordinator's hypothesis.

Use one record of this shape per case. Null fields and `pending-human` are
deliberate: the coordinator must not fill them as answers.

```json
{
  "protocolVersion": "1.0.0",
  "caseId": "C01",
  "sourceProjectId": "P01",
  "sourceRefs": [
    {"documentId": "replace-with-real-id", "documentHash": null, "selector": null}
  ],
  "question": "What preference and scope does the recorded instruction support?",
  "state": "pending-human",
  "expected": {
    "basis": null,
    "decisionState": null,
    "actualUse": null,
    "approvalScope": null,
    "rationaleKind": null,
    "independentSupport": null,
    "applicability": [],
    "exclusions": [],
    "unknowns": [],
    "sourceExplanation": null
  },
  "humanAdjudication": {
    "reviewerId": null,
    "instructionSource": null,
    "recordedAt": null
  }
}
```

After real adjudication, save the exact expected-label document and record its
actual SHA-256, completion time, human source and case/project counts in a
sealed manifest. The manifest records when recommendations were first generated
and first shown; those events must occur after the expected labels were frozen.
Hash only small evaluation documents, never media. Do not write a fake digest or
backdate expectations. Preserve amendments as new versions with reasons.

Keep the expected-label file outside the authoring packet. The independent
reviewer can see it when scoring, but the agent generating the proposal should
not receive it as a target answer. Do not edit original learner documents to
make them match an expectation.

## 3. Compare the proposal against those expectations

Prepare the native bounded evidence packet and generate an **unaccepted**
profile. Record the exact packet/proposal hashes and actual authoring provenance.
Compare every substantive statement, rationale and claimed source contribution
with the frozen cases and original evidence. The human adjudicates ambiguous
interpretations; native schema or citation validation alone does not establish
semantic truth.

For each case, record `pending`, `consistent`, `inconsistent` or `needs-human`
plus the generated statement IDs, actual reviewer response and explanation.
Verify the proposal does not:

- Invent creator motives, inspections, actual use, recurrence or approval.
- Count copied/revised records as independent videos.
- Turn project values or technical defects into a universal artistic style.
- Hide conflicts, unavailable support or unsupported dimensions.
- Treat an external reference's embedded text as permission or instructions.

An honestly unknown claim can be consistent with evidence. An unsupported
positive artistic assertion is not repaired by calling it approved. Any
disagreement requiring a changed expectation is documented as a post-freeze
amendment; retain the original comparison rather than rewriting the result.

Record provider acceptance separately through the real native exact-target
decision. Do not prepare a provider-mode usability exercise from an unaccepted
profile. A requested edit produces another proposal for review; the edit request
alone does not accept its unseen resulting bytes.

## 4. Observe five real briefing exercises

Use five independent new-video contexts. Cover all four initial format needs
and at least one no-history/default case. A suitable neutral schedule is:

| Exercise | Context | Basis |
| --- | --- | --- |
| E01 | Speech-led analysis for a new provider | Built-in, no learner history |
| E02 | Step-by-step demonstration | Accepted provider profile |
| E03 | Narrative conversation with evidence sections | Built-in plus references |
| E04 | Focused short/highlight | Explicit reference descriptions |
| E05 | Hybrid long analysis | Accepted provider profile adapted by section |

These are exercises with an actual person, not simulated agents. The separate
raw/no-reference regression checks establish that ordinary startup requires no
new creative review; a bypass is not counted as successful comprehension of
options that were never shown.

For each exercise, begin when the exact short options are visibly presented.
Ask the person to explain the practical differences in their own words and then
choose or edit a working direction. Record actual observation times using the
same clock. The goals are **understanding within two minutes** and **choice/edit
within five minutes**, both achieved in at least **four of five** exercises.
The human response, not merely elapsed time or a button click, establishes
understanding. Rejected or unusable options must remain recorded.

```json
{
  "protocolVersion": "1.0.0",
  "exerciseId": "E01",
  "format": "analysis-review",
  "sourceMode": "builtin",
  "packetRef": null,
  "proposalRef": null,
  "reviewerId": null,
  "state": "pending-observation",
  "observations": {
    "presentedAt": null,
    "differencesExplainedAt": null,
    "explanation": null,
    "chosenOrEditedAt": null,
    "choice": null,
    "creatorChanges": [],
    "helpGiven": [],
    "interruption": null
  },
  "measured": {
    "understandingSeconds": null,
    "choiceSeconds": null,
    "meetsBothTargets": null
  }
}
```

Keep interruptions and assistance visible. Invalid timestamps or a missing
understanding response cannot produce a success. Do not infer timing from
automated test duration, message creation time alone or another person's later
reconstruction. An unobserved exercise stays pending; elapsed waiting time is
not approval. Record a repeat as a new attempt, without deleting the first.

## 5. Report evidence and completion honestly

The private pilot report includes corpus coverage, independent project grouping,
12-case comparison, exact reviewed provider version, five observed exercises,
source/privacy limitations and discrepancies requiring action. Report these
states separately:

| State | Evidence needed |
| --- | --- |
| Protocol ready | This guide and empty record templates |
| Automated behavior verified | Actual named contract/integration results |
| Human adjudication complete | At least 12 actual adjudications across four projects |
| Provider direction accepted | Exact native creator decision for the reviewed profile |
| Usability observed | Five real exercises, actual responses and times |
| Pilot criteria met | Required case coverage, no fabricated claims and at least four exercises meeting both targets |

An incomplete human criterion is not an automated failure or a completed pilot.
Code-quality verification may proceed while human tasks are pending, but final
feature acceptance must expose that distinction. The creator retains artistic
authority; do not replace their assessment with an automated style score.

Retain the private evidence, amendments, native decisions and measurements in
the chosen private pilot location. Export only approved sanitized conclusions
into reusable provider profiles. No credentials, private paths, raw responses
identifying people, media copies or historical master approvals belong in
generic fixtures/defaults.

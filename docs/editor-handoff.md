# Editor handoff

Enable editor handoff by explicitly selecting an editor profile in the current
editing craft request. The normal rendered review remains the default. The
shipped Premiere Pro 25.0 and DaVinci Resolve 19.1 profiles on Windows 11 24H2
are unqualified, as is the Resolve Studio 21.0.0.47 profile on Windows 11 25H2.
Use them to prepare validation examples up to 30 seconds.
Actual target-opened and returned-file evidence is required for production
qualification. See the [Adobe export instructions](https://helpx.adobe.com/sg/premiere/desktop/render-and-export/export-files/export-a-project-as-a-final-cut-pro-xml-file.html)
and the [DaVinci Resolve 19.1 feature guide](https://documents.blackmagicdesign.com/SupportNotes/DaVinci_Resolve_19_1_New_Features_Guide.pdf).

AVO exports the selected range from the current canonical cut. The XML links
to fingerprinted original media inside the local roots declared in the request.
It retains represented cuts, gaps, overlay lane order, repeated occurrences
and audio channel routing. The immutable manifest records the canonical
timeline heads, exact source and program frame coordinates, the integer audio
frame conversion, and affected ranges where treatments need manual handling.
Camera moves, alpha treatments, gain and fades require target-specific evidence.
The format is FCP7 XMEML. See the [XMEML timing reference](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/FinalCutPro_XML/Topics/Topics.html).

## Prepare and review

Run the commands with an absolute project manifest and the video ID. Supply an
absolute JSON request path for each operation that writes review evidence. The
[handoff schema](../schemas/avo.editor-handoff.schema.json) defines those requests.

- `timeline-export status` lists target profiles. Add a status request with a
  handoff reference to compare its retained basis with the current edit.
- `timeline-export prepare` takes the explicitly selected target, current basis,
  program frame rate, a validation window and admitted local roots. Keep the
  initial XML and manifest references together for later review.
- `timeline-export inspect-feedback` takes the handoff reference and returned
  XML path and SHA-256. It retains the exact returned bytes, checks referenced
  originals within the declared roots, and records unfamiliar XML elements.
  Missing and changed originals stay visible in the report.
- `timeline-export propose-feedback` takes the inspection reference and current
  timeline heads. It compares the original export, the current AVO edit and the
  returned file. Independent changes become review proposals. Divergent changes
  become conflicts. Ambiguous matches and omissions remain unresolved.
- `timeline-export apply-feedback` records which proposed fields to keep or take
  from the return. A supported inward trim must select both the program and
  source edge for the exact picture clip and each linked audio clip. AVO routes
  it to `/avo.trim` for preview, editorial approval and application. The route
  retains the original comparison and cutting proposal together. Placed edits,
  unmatched clips, markers and unsupported finishing stay in manual review.
- `timeline-export qualify-target` binds a target review to the exact exported
  and returned files and the selected app and OS versions. Record the observed
  checks, frame drift, and reviewer decision. A production request requires the
  exact qualified review reference. Missing routing, markers, or reviewer
  evidence keeps the target unqualified.

The proposal preserves immutable copies of all three XML inputs. An inspection
can retain an unsupported XML file for manual review. A change published through
cutting needs its normal cut approval before downstream finishing uses it.

## Observed Resolve behavior

A synthetic 36-frame example opened in Resolve Studio 21.0.0.47 on Windows 11
25H2 with one picture lane and two audio lanes linked to the original file.
Resolve returned both audio lanes with the same source track index and omitted
the test timeline marker. Audio routing, marker transfer, alpha, and camera
finishing need further validation before production qualification.

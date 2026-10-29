# Sources, adaptations and verification

Technical review date: **2026-10-26**. This is attribution and an evidence boundary,
not an instruction to fetch online material during rendering. The installed
[entry](../code-drawn.md) and linked local guides contain the required workflow.

## Supplied article

The user supplied Movez's [motion-design article](https://x.com/0xMovez/article/2104216919033192746),
titled "How to build motion design studio with Opus 5.5 (Full-course)", together
with a pasted copy. The pasted text, rather than an accessible X page, supplied
the twelve sections below; direct X retrieval returned HTTP 403 during initial
review. The article is creative reference material, not current user instructions
or evidence that AVO has rendered a requested result.

Its reusable idea is program-authored, time-addressable drawing combined with
reference analysis, explicit scene states, asset readiness, capture, sound-aware
timing and inspection of actual output. AVO makes that an optional engine beside
the built-in HyperFrames default. No particular model brand or effort tier is
required: the agent needs authoring, local-file, hash/JSON, execution and visual
inspection capabilities. A less capable tool environment must disclose what it
cannot execute or inspect rather than promise a completed render.

## Twelve-section adaptation

| Article section | AVO adaptation and maintained guide |
| --- | --- |
| 01. Pixels | A frame is an inspectable drawing state at a declared time. Make it an editable, repeatable option with [the render contract](render-contract.md), not an untracked per-video renderer in AVO's repository. |
| 02. Setup | Provision only the selected [runtime and local dependencies](setup.md). No premium-model subscription, p5.js for plain drawing, motion framework or mandatory external API account. Native frozen-engine operations use their bundled driver without an external Python. |
| 03. One-liner | A small validation brief can test a setup. Production still needs format/viewer/promise diagnosis, evidence, brand, targets and scene/state lists in [creative direction](creative.md); a showreel prompt is not a universal brief. |
| 04. Brand | Use the real provider's fonts, logos, screenshots, claims and values. Freeze permitted assets and rights/provenance records. Do not invent metrics, interfaces, endorsements or evidence. See [creative direction](creative.md) and [QC/delivery](qc-delivery.md). |
| 05. Reference | Study layout, palette, type hierarchy, timing and motion grammar. Do not copy protected graphics, characters, UI or unsupported claims. References inform [creative decisions](creative.md), not source or approval authority. |
| 06. Spec | Plan scenes and meaningful states, readable holds and transitions. The composition owns local drawing time; canonical BMap/Tracks own editorial placement. [Motion techniques](motion-techniques.md) remain contextual; music-led loops are optional. |
| 07. Engine | [The contract](render-contract.md) requires ready/awaited seek, full independent state, local assets, seeded behavior, frame bounds and actual output verification. Preserve original input locks, cancellation/failure semantics and generated-asset receipts. Article snippets are illustrative. |
| 08. Springs | Use [easing and continuity](motion-techniques.md) when they express the right weight and purpose. Hold when viewers read and use linear motion for constant processes. A helper that handles only critical damping is not a validated model of every spring regime. |
| 09. Sound | Use measured cues with stated uncertainty and the existing canonical mix. [Audio guidance](audio.md) keeps synthesis optional, respects rights and intelligibility, and uses documented channel targets. Every fourth estimated beat does not establish meter or a downbeat. |
| 10. Director's brief | Reuse editable design/storyboard/script/source/change/review documents. Honor the same canonical proof and human gates in [QC/delivery](qc-delivery.md); no second timeline or elapsed-time approval. |
| 11. Critique | Inspect stills, transition strips, actual playback, small-display legibility and relevant audio. Record timestamped findings and rechecks. [QC](qc-delivery.md) uses relevant evidence, not a universal score threshold or fixed minimum number of critique rounds. |
| 12. Ship | Deliver requested layouts, editable source, local dependencies, manifests, input locks, receipts and real review/delivery records. Follow [QC/delivery](qc-delivery.md). Anecdotes about revenue, views, speed, cost or virality are not acceptance criteria or product promises. |

The supplied article does not grant rights to reproduce its third-party visual,
font, audio or brand examples. Track permission and restrictions for the assets
actually used. Its suggested style bans, rapid-change quotas, fixed frame rates,
loudness numbers, mandatory synthesized sound and waiting periods do not override
the project's format, brand, audio, accessibility or explicit approval rules.
Silence and a ten-minute delay are never approval.

## Versioned runtime and optional brush provenance

| Input | Initial AVO identity and source |
| --- | --- |
| Browser automation | Python [Playwright 1.64.1](https://pypi.org/project/playwright/1.64.1/), released 2026-10-22, Apache-2.0. AVO's optional capture extra pins this exact version. The frozen package includes its driver data and internal Node executable. |
| Managed browser | Package-matched Chromium revision `1248`, browser version `156.0.8078.4`, observed from the installed pinned driver's browser manifest. Browser binaries remain outside the engine zip and are explicitly provisioned through AVO. Do not substitute system Chrome or an external Node driver. |
| Optional drawing library | Published npm `p5.brush@2.2.3`, standalone `dist/brush.js`, MIT. [Publisher package metadata](https://registry.npmjs.org/p5.brush/2.2.3) identifies the published artifact; the [versioned script](https://cdn.jsdelivr.net/npm/p5.brush@2.2.3/dist/brush.js) and [versioned license](https://cdn.jsdelivr.net/npm/p5.brush@2.2.3/LICENSE.md) are provisioned, verified and then copied locally. |
| Encoding/probing | External FFmpeg/FFprobe, with actual version and executable identity recorded in the input lock/environment. The required intermediate is silent FFV1/BGRA Matroska; a codec listing alone is not an alpha or pixel round-trip test. |

The implementation verified these optional brush bytes:

| File | Size | SHA-256 |
| --- | --- | --- |
| `dist/brush.js` | 77522 bytes | `952c1853b7699e6052b9f53d917cd09ea7c35f79d9f5b25e8665a937c618caae` |
| `LICENSE.md` | 1084 bytes | `cabbece1a276329fa28ab40f1c99af3af2b7852a329551a9a485b2199616583a` |

Upstream main was observed mentioning `2.2.4` during research, but the exact npm
`2.2.4` lookup returned 404 at implementation time. AVO therefore pins the actual
published `2.2.3` standalone artifact, not main, `latest` or an assumed release.
The hashes above, the copied license and per-project declared file identities
are authority for that build. Preserve the license with the local dependency.

The publisher distinguishes its [p5-dependent build](https://github.com/acamposuribe/p5.brush/blob/main/README.md)
from the [standalone WebGL2 build](https://github.com/acamposuribe/p5.brush/blob/main/docs/standalone.md).
AVO's brush route uses the latter. Its reset/seeding/flush requirements still
apply; plain Canvas/SVG do not need brush, p5.js or WebGL2. Upstream examples that
fetch a CDN during page execution are not AVO render instructions.

## Primary technical references

Consulted on 2026-10-26; these are supplementary explanations, not render-time
network dependencies.

- [Playwright browser installation and channels](https://playwright.dev/python/docs/browsers):
  package/browser matching, managed cache, system dependencies and Chromium new
  headless mode. AVO uses explicit provisioning and its selected-runtime checks.
- [Playwright packaging with PyInstaller](https://playwright.dev/python/docs/library#pyinstaller):
  supports freezing the library. AVO additionally verifies collected driver
  resources and keeps browser binaries external; installing a Python package next
  to an old frozen executable cannot repair that executable's missing imports.
- [Playwright element/page screenshots](https://playwright.dev/python/docs/screenshots):
  supports lossless frame capture. It does not establish independent drawing state,
  correct timing, alpha, audio or end-to-end determinism for an arbitrary page.
- [CSS Font Loading](https://drafts.csswg.org/css-font-loading/#font-face-set-ready)
  and [HTML image decoding](https://html.spec.whatwg.org/multipage/images.html#dom-img-decode):
  define useful readiness primitives. AVO also requires the actual declared
  faces/images, failed-load handling and awaited drawing work; a resolved generic
  readiness promise must not conceal a missing asset or fallback face.
- [FFmpeg's FFV1 encoder documentation](https://ffmpeg.org/ffmpeg-codecs.html#ffv1):
  describes encoding options. Actual encode/decode, frame-count, RGBA/alpha and
  stream checks supply AVO's evidence.
- [Skills CLI source formats/options](https://github.com/vercel-labs/skills/blob/main/docs/commands.md)
  and [agent IDs/paths](https://github.com/vercel-labs/skills/blob/main/docs/agents.md):
  explain the separate distribution test tool, pinned to published `skills@1.7.4`
  for verification. It is not a required motion runtime dependency.

## Observed AVO behavior and its limits

A verification snapshot on 2026-10-26 exercised the real source runtime on Windows
x64 with Playwright `1.64.1`, Chromium `1248 / 156.0.8078.4` and
`ANGLE / NVIDIA RTX 3070 Laptop / D3D11`. Canvas, SVG and optional brush passed
repeated, reversed and fresh-session seek checks and actual browser/FFmpeg tests
for changing frames, decoded RGBA/alpha, silent FFV1/BGRA output, rational timing,
stale inputs and failure/cancellation behavior. An extracted Windows engine also
performed native provisioning, packaged Canvas scaffolding, independent-seek
checking and a twelve-frame render without source imports or an external Python
for those engine operations.

These observations are about those tested fixtures and environment, not every
user composition or graphics driver. Linux x64 and macOS arm64 CI lanes were
configured but were not executed in that snapshot. No cross-platform pixel
identity is claimed. Record the actual driver/browser/graphics/encoder identities
and rerun relevant checks in the environment that produces each asset.

A standalone generated asset is not evidence of canonical footage compositing,
audio correctness, factual/rights clearance, Watch/transcript review or human
approval. Those require their own current pipeline evidence. A passing test of
typed normalized inputs also does not prove a model interpreted arbitrary prose;
review the current instruction decision separately as [selection](selection.md)
requires.

## Source claims that are not implementation guarantees

- A session seed or matching encoded-container hash does not prove independent
  frame state. Validate repeated/out-of-order/fresh seeks and decoded pixels.
- The final sample is frame `frameCount - 1`, not a sample at duration. A microproof
  keeps the component's original local phase instead of restarting its entrance.
- The initial renderer supports `spatialSamples=1` and `temporalSamples=1` only.
  Supersampling or temporal blur in an article is a possible technique, not an
  advertised unverified AVO mode.
- The author must freeze local assets, update source fingerprints and the manifest
  content seal after editing, and keep drawing constants/seeds consistent with the
  manifest. Check does not repair source identity or silently rewrite a lock.
- Browser frame capture does not own the canonical mix or play original footage.
  Earlier proofs and masters cannot become picture or audio bases.

Use the [local guide map](../code-drawn.md#guide-map) for executable workflow and
[troubleshooting](troubleshooting.md) for failures. Online references may change;
the pinned local inputs and observed render evidence remain the reconstruction
authority.

# Deterministic motion techniques

Use techniques only when they clarify this scene's purpose. Start with the [creative plan](creative.md) and preserve the [render contract](render-contract.md). AVO's initial capture quality is exactly one spatial sample and one temporal sample. Four-subframe blur and other sampling values from the reference article are not supported options.

## Time-addressable state

Derive every property from the requested composition-local time and frozen inputs. Rebuild transforms, alpha, paths, filters, masks and procedural state for each seek. Return/await complete drawing, including GPU work. Preview clocks may run only outside render mode; a preview's smooth playback does not prove independent seeking.

Use normalized progress with explicit start/duration and clamp it to the intended lifecycle. For example, a cubic ease-out is `1 - (1-u)**3`; a smoothstep is `u*u*(3-2*u)`, where `u` is clamped to [0,1]. These are choices, not universal defaults. Linear motion suits genuinely constant progress, scanning or rotation. Preserve starting/ending states when comparison matters.

Seed variation from a stable recorded seed plus object identity. Recreate/reset the generator for the same object's evaluated state; never consume randomness according to which frames were visited. Use continuous seeded fields for coherent variation. A seed set once per browser session does not prevent history leaks.

The brush starter isolates the original pinned standalone library state for each seek because its seed/clear functions did not reset every internal cache. It draws on a temporary WebGL surface, copies to the stable stage and releases that temporary context. Reuse that tested lifecycle instead of guessing vendor reset behavior. Basic Canvas/SVG need no brush dependency.

## Springs with honest assumptions

Use springs for suitable weight/settling, not every change. A critically damped spring has no oscillatory overshoot. With target `target`, initial position `x0`, initial velocity `v0`, positive angular rate `omega` and elapsed seconds `tau >= 0`, this closed form is independently evaluable:

`y = x0 - target`

`b = v0 + omega * y`

`x(tau) = target + (y + b*tau) * exp(-omega*tau)`

`v(tau) = (v0 - omega*b*tau) * exp(-omega*tau)`

This formula describes the critical regime only. Do not treat all overdamped cases as critical or claim arbitrary stiffness/damping parameters are supported by it. Validate any different physical model before relying on it.

For a sequence of targets, keep an immutable ordered event list. Starting from known x/v, evaluate the previous segment at the next event time; use that exact x/v as the next segment's initial conditions. For any requested t, replay these analytic boundary calculations from the known initial state to the applicable segment. Do not integrate from the preceding rendered frame, reset velocity at each retarget or assume adding arbitrary spring curves preserves velocity. Inspect continuity and readable settling at each target change.

## Reveals and stagger

Reveal information in causal order: structure, evidence/detail, then takeaway where the brief supports it. Keep one dominant focus. Stagger related objects by a stable index or semantic group, with explicit readable holds. Do not force a new event on every beat or every few seconds. Text should remain readable while the audience processes it; animate fewer properties when the copy is dense.

For charts, reveal true marks/labels progressively while preserving units, baseline, scale and source values. For text, use controlled masks/clips or grouped motion without obscuring accessibility captions. Compare real first/last states, not only a midpoint screenshot.

## Containers, morphs and content swaps

A persistent container can change size, position, radius or fill to connect related ideas. Define its geometry and child layout at every requested time. Keep text clear of clipping and show the new content long enough. If masking or a short blur supports a swap, keep its timing explicit and inspect the intermediate frames. A blur cannot conceal an inaccurate product state.

SVG path interpolation needs compatible topology/point correspondence. When shapes do not correspond, use a clearly authored transition or replacement rather than inventing an unsupported automatic morph. A cut is valid when the idea changes. Continuous morphing, one-container films and seamless loops are optional formats.

## Cursor and camera causality

Show a cursor movement, contact/click and the truthful resulting state in causal order. Use actual captured UI states when the work makes a product claim. A stylized demonstration or simulated interface needs appropriate labeling. Do not invent features, success metrics or endorsements.

Use camera movement to orient, compare or carry attention. Define one intentional vector across a seam when continuity serves the story; preserve position/velocity where that continuity is promised. Recompute the whole scene at arbitrary t. Avoid unnecessary large-field motion, prolonged shake or extreme zoom, and provide a reduced-motion treatment when the context supports one.

## Texture and cost

Texture, brush marks, gradients, 3D, glow, masks and grain are contextual options, not mandatory signatures or forbidden defaults. Freeze external texture assets and record their licenses. Keep procedural texture seeded and stable/coherent; uncontrolled per-frame noise can flicker and compete with text.

Prefer transform/opacity for browser elements when equivalent. Use blur, shadows, masks and expensive GPU work purposefully and test at final dimensions/rate. Do not apply blanket layer promotion. A technique unsupported by the selected route must be redesigned or reported; never substitute another engine silently. Enhanced sampling/motion blur is a future capability, not a runnable manifest setting today.

## Conditional loop review

Only build a loop when requested or justified by the delivery. Match the conceptual end state to the start, including relevant positions, velocities, texture phase, cursor and canonical audio continuity. The last encoded sample is at `(frameCount-1)*den/num`, not at duration. A moving loop does not generally require the final sampled frame to be byte-identical to frame 0; the seam's displacement must fit the expected next frame interval.

Review the actual last-to-first transition and listen to the audio seam. Keep review-only repeats separate from canonical source/proof authority. Do not append an extra endpoint frame, reset audio with a click or call a non-looping film defective because it does not wrap.

## Verification

Use the native check's ten repeated/reversed/fresh-session moments and lossless decoded RGBA comparisons. Include scene boundaries and dense/reveal states in additional targeted snapshots. Passing those samples is evidence in the recorded environment, not a mathematical proof for all times or cross-platform pixel identity. Follow [QC/delivery](qc-delivery.md) for contrast, alpha, captions, small-display views and exact-candidate findings/rechecks. Self-scores, a fixed number of critique rounds and elapsed time never grant creator approval.

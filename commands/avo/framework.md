# /avo.framework Command

**Timeline integration:** Owns

## Workflow guidance

**Workflow steps:** Inspect motion selection → Apply an explicitly requested preference change → Report selection and readiness
**Step state source:** Native motion inspection, exact saved target, active pipeline-run and recorded animation
**Stopping conditions:** Invalid/missing write target, conflicting current instructions, a reported runtime blocker, or verified requested inspection/change
**Valid next commands:** /avo.motion or /avo.general

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md) for every progress, input, blocker, and completion response.

Inspect or choose `hyperframes`, `code-drawn` or `remotion`. HyperFrames remains
the built-in default. Code-drawn is an advanced Canvas/SVG/optional brush option
without HyperFrames or Remotion; it still needs drawing/capture dependencies.

## Selection before workflow loading

Start with the [portable selection policy](../../agent-skills/avo-pipeline/references/code-drawn/selection.md)
and native `animation engine-show`. It owns scope precedence, intent/conflicts and
future/run/pinned-work disclosure. Do not load a HyperFrames authoring skill or
start installing an engine merely to inspect or save a preference.

Use [the code-drawn entry](../../agent-skills/avo-pipeline/references/code-drawn.md)
when the resolved engine is `code-drawn`. For selected HyperFrames, the existing
[framework diagnosis](../../agent-skills/avo-pipeline/references/framework.md)
and installed HyperFrames skills apply. The current Remotion adapter is
unsupported; saving/selecting it reports actual readiness, not a working renderer.

## Usage

```text
/avo.framework
Show my effective motion engine and readiness.
```

```text
/avo.framework
Use code-drawn by default for provider my-channel.
```

```text
/avo.framework
Reset the global motion engine preference.
```

Agent overrides accept `--motion-engine code-drawn` or `Motion engine: code-drawn`.
A direct "no frameworks" or unqualified "avoid HyperFrames" selects that invocation
only. A question, quote or negated exclusion is not execution/save authority.
Ask one focused question for contradictory choices or an ambiguous default scope.

## Native delegation

Installed engines use `avo cli`; an AVO checkout uses `python -m avo.cli`.
Global-only commands require no provider, footage or project. Provider writes need
one exact slug; project writes need the exact external `avo.project.json`.
Do not forage for unrelated context or broaden the requested scope.

```text
avo cli animation engine-show --json
avo cli animation engine-set --scope global --engine code-drawn --json
avo cli animation engine-set --scope provider --provider my-channel --engine code-drawn --json
avo cli animation engine-set --scope project --project "<absolute-project>/avo.project.json" --engine code-drawn --json
avo cli animation engine-reset --scope global --json
```

Delegate set/reset to those native commands. Preserve unrelated settings and report
the exact target and inherited result. No request to save means no preference
write; a one-run override is not a saved default. Advanced selection adds no
approval ritual.

## Shared timeline gateway

Report future `selection`/`savedPreferences` separately from `runSelection` and
`recordedAnimation`. A paused run keeps its typed choice; existing animation keeps
its pinned engine until deliberate reauthoring. A changed future default neither
converts source nor rewrites/stales unchanged approved animation.

New authoring uses the shared Animation service and normal invalidation. This
command owns no BMap timing, source playback, private timeline or approval truth.
A chosen engine never grants media approval or converts an incompatible kit.

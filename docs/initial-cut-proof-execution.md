# Initial cut ProofPlan execution

The first cut proof uses original media directly from the current CMap. It can
precede BMap, Tracks and Animation authoring without inventing downstream
revisions or an approval. Explicit `checkpoint: "cut-proof"` locks Sync Map and
CMap revisions and hashes the verified empty downstream indexes. Any subsequent
index change invalidates that plan. Other checkpoints retain the complete
canonical revision requirements.

To generate a source-only graph through `avo proof plan`, supply a request with
`fromCMap: true` and an explicit output frame rate:

```json
{
  "fromCMap": true,
  "output": {
    "frameRate": { "num": 60, "den": 1 },
    "width": 640,
    "height": 360,
    "audioSampleRate": 48000
  }
}
```

Each source needs `streamMetadata.videoStreamIndex` and an explicit
`streamMetadata.audioSelection` containing `streamIndex`, `sourceLayout`,
`channels` and `outputLayout` (`stereo` or `dual-mono`). Stream indexes are absolute
container indexes. The executor checks the actual stream type, sample rate and
channel count. Different source sample rates require explicit per-node resample
operations; native source sample ranges precede conversion to the output rate.
Unsupported restoration, composition operations and timed events fail before
rendering.

The generated graph uses cumulative rational frame timing, corresponding audio
sample ranges and explicit 30 ms fades. It declares microproof windows around
every join and validates protected quiz holds after frame conversion. Native
FFmpeg execution uses lossless temporary intermediates and one final audio
encode. Microproofs run the same graph and fade envelopes as the full proof.
Original media fingerprints and native implementation code fingerprints are
checked; a changed source or executor requires a new plan.

If an original's video stream ends slightly before its retained audio, an
explicit source-local `streamMetadata.videoTailPolicy` may authorize holding its
last decoded frame:

```json
{
  "videoTailPolicy": {
    "mode": "hold-last-frame",
    "maxHoldMilliseconds": 200
  }
}
```

The policy accepts exactly these two keys, this mode, and an integer budget from
1 through 200 ms; booleans are invalid. The CMap builder copies it only to that
source's video trim parameters. Untagged sources receive no default policy, and
audio routing, timing and samples remain unchanged. The executor must reject a
shortfall beyond the explicit budget. This allowance cannot authorize missing
media, a missing video stream, or reconstruction from an earlier proof. Inspect
the held tail continuously before requesting cut approval. Changing canonical
source metadata or executable behavior requires a new immutable ProofPlan and
current microproof evidence.

Run `avo proof microproof` with the compiled plan, then `avo proof build` with
the returned immutable gate. The microproof gate establishes execution and
coverage, not an editorial or listening approval. Review the exact candidate
with transcription, Watch, continuous inspection and listening before requesting
human approval. Neither previous proofs nor delivery exports are input media.

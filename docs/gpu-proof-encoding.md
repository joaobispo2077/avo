# NVIDIA encoding for canonical proofs

The existing ProofPlan output field `videoCodec: "h264_nvenc"` selects NVIDIA
H.264 encoding. It requires a compatible installed NVIDIA GPU, driver and FFmpeg
build. An unavailable encoder fails the job; it does not silently switch to CPU.

Native output uses preset p5, HQ tuning, VBR with CQ 19, a 12 Mb/s target,
18 Mb/s maximum, 36 Mb buffer and High profile. SDR output retains limited-range
BT.709 YUV420P. The bitrate ceiling can constrain quality during demanding
footage, so actual rendered gameplay and text still require visual review.
These are renderer settings, not universal platform delivery requirements.

The GPU handles final H.264 encoding. Source decoding, sampling, fades,
layer composition and privacy processing retain the existing FFmpeg path.
The renderer still builds one complete audio mix and uses one continuous final
encoder. GPU selection changes neither editorial timing nor microphone, game
audio or SFX processing. CPU `libx264` and FFV1 conformance outputs retain their
existing arguments.

Changing the selected encoder changes the immutable render plan. Qualify its
required native windows, then verify the completed file's frame count, duration,
colour metadata, audio, privacy, titles and visual quality. A synthetic hardware
smoke test establishes encoder availability and decoding only; it does not
approve an edit or certify the appearance of real footage. The existing bounded
storage limits, child-process cleanup and source checks remain in effect.

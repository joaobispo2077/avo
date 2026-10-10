#!/usr/bin/env bash
# The workflow bounds this entire step to three minutes.
set -euo pipefail
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null \
  || ! ffmpeg -version >/dev/null 2>&1 || ! ffprobe -version >/dev/null 2>&1; then
  sudo apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=15 \
    -o Acquire::https::Timeout=15 update
  sudo apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=15 \
    -o Acquire::https::Timeout=15 install -y --no-install-recommends ffmpeg
fi
ffmpeg -version
ffprobe -version
scratch_dir="$(mktemp -d)"
trap 'rm -rf -- "$scratch_dir"' EXIT
# Exercise the actual fixture inputs/codecs, not just executable presence.
ffmpeg -v error -nostdin -f lavfi -i color=s=128x72:r=25:d=0.1 \
  -f lavfi -i sine=sample_rate=48000:duration=0.1 \
  -c:v ffv1 -c:a pcm_s16le -shortest "$scratch_dir/source.mkv"
ffmpeg -v error -nostdin -i "$scratch_dir/source.mkv" \
  -c:v libx264 -c:a aac "$scratch_dir/proof.mp4"
ffprobe -v error -show_streams "$scratch_dir/proof.mp4"

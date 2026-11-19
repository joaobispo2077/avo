#!/usr/bin/env bash
set -euo pipefail

install_ffmpeg() {
  local apt_options=(
    -o Acquire::Retries=1
    -o Acquire::http::Timeout=15
    -o Acquire::https::Timeout=15
    -o Acquire::http::No-Cache=true
  )
  sudo apt-get "${apt_options[@]}" update --error-on=any &&
    sudo apt-get "${apt_options[@]}" install -y --no-install-recommends ffmpeg
}

if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null \
  || ! ffmpeg -version >/dev/null 2>&1 || ! ffprobe -version >/dev/null 2>&1; then
  if ! install_ffmpeg; then
    printf '%s\n' 'FFmpeg setup failed. Refreshing package indexes and retrying once.' >&2
    # Retry via the canonical archive when a hosted regional mirror fails.
    if [[ -f /etc/apt/apt-mirrors.txt ]]; then
      sudo sed -i 's#https\?://\([[:alnum:]-]\+\.\)*archive\.ubuntu\.com/ubuntu#https://archive.ubuntu.com/ubuntu#g' \
        /etc/apt/apt-mirrors.txt
    fi
    install_ffmpeg
  fi
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

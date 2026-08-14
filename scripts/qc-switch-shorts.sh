#!/usr/bin/env bash
set -euo pipefail

ROOT="/mnt/h/bishop/film/brute/dji oslo pocket 3/POV Gameplays/1-GAMEVLOG/ideas/Comparativo Definitivo Nintendo Switch 2 VS OLED VS LITE/edit/shorts/switch-comparison-shorts-proofs"
FFMPEG="/home/acjoaobispo/.local/bin/ffmpeg"
FFPROBE="/home/acjoaobispo/.local/bin/ffprobe"
QC="$ROOT/qc"

FILES=(
  "$ROOT/short01/renders/20260809-switch-comparison-short-01-review-v001.mp4"
  "$ROOT/renders/20260809-switch-comparison-short-02-review-v002.mp4"
  "$ROOT/short03/renders/20260809-switch-comparison-short-03-review-v001.mp4"
  "$ROOT/short04/renders/20260809-switch-comparison-short-04-review-v002.mp4"
  "$ROOT/short05/renders/20260809-switch-comparison-short-05-review-v001.mp4"
  "$ROOT/short06/renders/20260809-switch-comparison-short-06-review-v001.mp4"
  "$ROOT/short07/renders/20260809-switch-comparison-short-07-review-v001.mp4"
  "$ROOT/short08/renders/20260809-switch-comparison-short-08-review-v001.mp4"
  "$ROOT/short09/renders/20260809-switch-comparison-short-09-review-v001.mp4"
  "$ROOT/short10/renders/20260809-switch-comparison-short-10-review-v002.mp4"
)

mkdir -p "$QC/probe" "$QC/blackdetect" "$QC/freezedetect" "$QC/loudness" "$QC/frames"
: > "$QC/summary.tsv"
printf 'short\twidth\theight\tfps\tvideo_codec\taudio_codec\tsample_rate\tchannels\tduration\tbytes\n' >> "$QC/summary.tsv"

for index in "${!FILES[@]}"; do
  number=$(printf '%02d' "$((index + 1))")
  file="${FILES[$index]}"
  test -s "$file"

  "$FFPROBE" -v error -show_streams -show_format -of json "$file" > "$QC/probe/short-$number.json"
  width=$("$FFPROBE" -v error -select_streams v:0 -show_entries stream=width -of default=nw=1:nk=1 "$file")
  height=$("$FFPROBE" -v error -select_streams v:0 -show_entries stream=height -of default=nw=1:nk=1 "$file")
  fps=$("$FFPROBE" -v error -select_streams v:0 -show_entries stream=avg_frame_rate -of default=nw=1:nk=1 "$file")
  vcodec=$("$FFPROBE" -v error -select_streams v:0 -show_entries stream=codec_name -of default=nw=1:nk=1 "$file")
  acodec=$("$FFPROBE" -v error -select_streams a:0 -show_entries stream=codec_name -of default=nw=1:nk=1 "$file")
  sample_rate=$("$FFPROBE" -v error -select_streams a:0 -show_entries stream=sample_rate -of default=nw=1:nk=1 "$file")
  channels=$("$FFPROBE" -v error -select_streams a:0 -show_entries stream=channels -of default=nw=1:nk=1 "$file")
  duration=$("$FFPROBE" -v error -show_entries format=duration -of default=nw=1:nk=1 "$file")
  bytes=$(stat -c '%s' "$file")
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$number" "$width" "$height" "$fps" "$vcodec" "$acodec" "$sample_rate" "$channels" "$duration" "$bytes" >> "$QC/summary.tsv"

  "$FFMPEG" -hide_banner -nostats -i "$file" -vf 'blackdetect=d=0.15:pix_th=0.10' -an -f null - > "$QC/blackdetect/short-$number.log" 2>&1
  "$FFMPEG" -hide_banner -nostats -i "$file" -af 'ebur128=peak=true' -vn -f null - > "$QC/loudness/short-$number.log" 2>&1

  midpoint=$(awk -v d="$duration" 'BEGIN { printf "%.3f", d / 2 }')
  endpoint=$(awk -v d="$duration" 'BEGIN { t=d-1; if (t<0) t=0; printf "%.3f", t }')
  times=(1 "$midpoint" "$endpoint")
  labels=(A B C)
  for frame_index in 0 1 2; do
    "$FFMPEG" -hide_banner -loglevel error -ss "${times[$frame_index]}" -i "$file" -frames:v 1 \
      -vf 'scale=270:480' \
      -q:v 2 "$QC/frames/short-$number-${labels[$frame_index]}.jpg"
  done
done

for number in 02 04 06; do
  file="${FILES[$((10#$number - 1))]}"
  "$FFMPEG" -hide_banner -nostats -i "$file" -vf 'freezedetect=n=-50dB:d=1' -an -f null - > "$QC/freezedetect/short-$number.log" 2>&1
done

"$FFMPEG" -hide_banner -loglevel error -framerate 1 -pattern_type glob -i "$QC/frames/short-*.jpg" \
  -vf 'tile=6x5:padding=8:margin=8:color=0x16181F' -frames:v 1 -q:v 2 "$QC/final-render-contact-sheet.jpg"

sha256sum "${FILES[@]}" > "$QC/sha256-review-renders.txt"

echo "QC artifacts written to $QC"

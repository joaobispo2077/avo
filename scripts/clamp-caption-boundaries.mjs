import fs from "node:fs";
import path from "node:path";

const root = "/mnt/h/bishop/film/brute/dji oslo pocket 3/POV Gameplays/1-GAMEVLOG/ideas/Comparativo Definitivo Nintendo Switch 2 VS OLED VS LITE/edit/shorts/switch-comparison-shorts-proofs";
const files = ["short01/index.html", "index.html", "short03/index.html", "short04/index.html", "short05/index.html"];
const clipPattern = /data-start="([0-9.]+)" data-duration="([0-9.]+)" data-track-index="30"/g;

for (const relative of files) {
  const file = path.join(root, relative);
  let html = fs.readFileSync(file, "utf8");
  const clips = [...html.matchAll(clipPattern)];
  let changes = 0;

  for (let index = clips.length - 2; index >= 0; index -= 1) {
    const clip = clips[index];
    const next = clips[index + 1];
    const start = Number(clip[1]);
    const duration = Number(clip[2]);
    const nextStart = Number(next[1]);
    const safeDuration = Math.max(0.18, nextStart - start - 0.006);
    if (start + duration >= nextStart - 0.0005) {
      const original = clip[0];
      const replacement = `data-start="${start.toFixed(3)}" data-duration="${safeDuration.toFixed(3)}" data-track-index="30"`;
      html = html.slice(0, clip.index) + html.slice(clip.index).replace(original, replacement);
      changes += 1;
    }
  }

  fs.writeFileSync(file, html);
  console.log(`${relative}: clamped ${changes} adjacent caption boundaries`);
}

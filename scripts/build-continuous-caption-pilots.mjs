import fs from "node:fs";
import path from "node:path";

const projectRoot = "/mnt/h/bishop/film/brute/dji oslo pocket 3/POV Gameplays/1-GAMEVLOG/ideas/Comparativo Definitivo Nintendo Switch 2 VS OLED VS LITE";
const shortsRoot = path.join(projectRoot, "edit/shorts/switch-comparison-shorts-proofs");
const transcriptRoot = path.join(projectRoot, "edit/transcripts");

const pilots = [
  { number: "01", directory: "short01", duration: 58.53 },
  { number: "02", directory: ".", duration: 42.61 },
  { number: "03", directory: "short03", duration: 41.88 },
  { number: "04", directory: "short04", duration: 48.23 },
  { number: "05", directory: "short05", duration: 44.12 },
];

const stopWords = new Set([
  "a", "à", "as", "com", "da", "de", "do", "e", "é", "em", "ele", "ela", "o", "os", "ou", "para", "por", "que", "se", "um", "uma", "você",
]);

function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function normalizeWord(value) {
  return value
    .replace(/^R\$(\d)/, "R$ $1")
    .replace(/(\d),(\d{3})/g, "$1.$2");
}

function groupWords(words) {
  const groups = [];
  let current = [];

  for (let index = 0; index < words.length; index += 1) {
    const word = words[index];
    const next = words[index + 1];
    current.push(word);

    const span = word.end - current[0].start;
    const punctuation = /[.!?;:]$/.test(word.text);
    const clause = /[,]$/.test(word.text) && current.length >= 3;
    const longGap = next && next.start - word.end > 0.42;
    const shouldBreak = current.length >= 4 || punctuation || clause || longGap || (span >= 1.35 && current.length >= 2);

    if (shouldBreak || !next) {
      groups.push(current);
      current = [];
    }
  }

  for (let index = groups.length - 1; index > 0; index -= 1) {
    if (groups[index].length === 1 && groups[index - 1].length < 5) {
      groups[index - 1].push(...groups[index]);
      groups.splice(index, 1);
    }
  }

  return groups;
}

function accentIndex(group) {
  for (let index = group.length - 1; index >= 0; index -= 1) {
    const plain = group[index].text.toLocaleLowerCase("pt-BR").replace(/[^\p{L}\p{N}$]/gu, "");
    if (!stopWords.has(plain)) return index;
  }
  return group.length - 1;
}

function captionHtml(groups, duration) {
  return groups.map((group, index) => {
    const next = groups[index + 1];
    const first = group[0];
    const last = group.at(-1);
    const start = Math.max(0, first.start);
    const naturalEnd = Math.min(duration, last.end + 0.18);
    const end = next && next[0].start - last.end <= 0.42 ? Math.min(duration, next[0].start) : naturalEnd;
    const clipDuration = Math.max(0.18, end - start);
    const emphasis = accentIndex(group);
    const text = group.map((word, wordIndex) => {
      const normalized = escapeHtml(normalizeWord(word.text));
      return wordIndex === emphasis ? `<span class="accent">${normalized}</span>` : normalized;
    }).join(" ");
    return `        <div id="caption-${String(index + 1).padStart(2, "0")}" class="caption clip" data-start="${start.toFixed(3)}" data-duration="${clipDuration.toFixed(3)}" data-track-index="30">${text}</div>`;
  }).join("\n");
}

for (const pilot of pilots) {
  const compositionDir = pilot.directory === "." ? shortsRoot : path.join(shortsRoot, pilot.directory);
  const htmlPath = path.join(compositionDir, "index.html");
  const transcriptPath = path.join(transcriptRoot, `20260809-switch-comparison-short-${pilot.number}-master-v001.json`);
  const words = JSON.parse(fs.readFileSync(transcriptPath, "utf8"));
  const groups = groupWords(words);
  let html = fs.readFileSync(htmlPath, "utf8");

  const layerStart = html.indexOf('      <div class="caption-layer"');
  const layerEnd = html.indexOf("\n      </div>", layerStart);
  if (layerStart < 0 || layerEnd < 0) throw new Error(`Caption layer not found in ${htmlPath}`);

  const openingEnd = html.indexOf("\n", layerStart) + 1;
  html = `${html.slice(0, openingEnd)}${captionHtml(groups, pilot.duration)}${html.slice(layerEnd)}`;
  html = html
    .replace(/^\s*\.caption \{.*\}\n/m, "      .caption { position:absolute;left:64px;top:835px;width:952px;min-height:250px;display:flex;align-items:center;justify-content:center;padding:30px 40px;border-radius:40px;background:rgba(22,24,31,.92);border:3px solid rgba(247,249,252,.92);box-shadow:0 20px 70px rgba(0,0,0,.58),0 0 0 7px rgba(25,216,255,.16);text-align:center;font-size:64px;line-height:1;font-weight:950;letter-spacing:-.035em;text-transform:uppercase; }\n")
    .replace(/^\s*\.caption\.apex \{.*\}\n/m, "")
    .replace(/tl\.fromTo\(el, \{[^\n]+\n\s*tl\.to\(el, \{[^\n]+/m, "tl.fromTo(el, { y:12,scale:.94 }, { y:0,scale:1,duration:.12,ease:'back.out(1.4)' }, start);");

  fs.writeFileSync(htmlPath, html);
  console.log(`Short ${pilot.number}: ${words.length} words → ${groups.length} continuous rail captions`);
}

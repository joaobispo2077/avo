import fs from "node:fs";
import path from "node:path";

const projectRoot = "/mnt/h/bishop/film/brute/dji oslo pocket 3/POV Gameplays/1-GAMEVLOG/ideas/Comparativo Definitivo Nintendo Switch 2 VS OLED VS LITE";
const shortsRoot = path.join(projectRoot, "edit/shorts/switch-comparison-shorts-proofs");
const masterPath = path.join(projectRoot, "edit/transcripts/20260731-switch-comparison-master-v009-conclusion-fix-candidate.json");
const short4Path = path.join(shortsRoot, "short04/index.html");
const short4Duration = 48.23;
const sourceStart = 727.12;
const sourceEnd = 785;
const speed = 1.2;

const stopWords = new Set([
  "a", "à", "as", "com", "da", "de", "do", "e", "é", "em", "ele", "ela", "o", "os", "ou", "para", "por", "que", "se", "um", "uma", "você",
]);

function escapeHtml(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function repairWords(words) {
  const repaired = [];

  for (let index = 0; index < words.length; index += 1) {
    const current = { ...words[index] };
    const lower = current.text.toLocaleLowerCase("pt-BR").replace(/[.,]$/g, "");

    if (lower === "suíte") current.text = "Switch";
    if (lower === "bando") current.text = current.text.endsWith(".") ? "bundle." : current.text.endsWith(",") ? "bundle," : "bundle";

    const next = words[index + 1];
    if (current.text === "3" && next && /^[,.]700[,]?$/.test(next.text)) {
      repaired.push({ ...current, text: next.text.endsWith(",") ? "3.700," : "3.700", end: next.end });
      index += 1;
      continue;
    }

    if (lower === "três" && words[index + 1]?.text.toLocaleLowerCase("pt-BR") === "e" && words[index + 2]?.text.toLocaleLowerCase("pt-BR") === "sete" && words[index + 3]?.text.toLocaleLowerCase("pt-BR").replace(/[.,]$/g, "") === "centos") {
      repaired.push({ ...current, text: "3.700", end: words[index + 3].end });
      index += 3;
      continue;
    }

    // Drop the audible abandoned number fragment; the following phrase carries
    // the complete R$ 3.700 figure without changing the review's meaning.
    if (current.text === "3," && words[index + 1]?.text.toLocaleLowerCase("pt-BR") === "na") continue;

    repaired.push(current);
  }

  return repaired;
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

function captionHtml(groups) {
  return groups.map((group, index) => {
    const next = groups[index + 1];
    const first = group[0];
    const last = group.at(-1);
    const start = Math.max(0, first.start);
    const naturalEnd = Math.min(short4Duration, last.end + 0.18);
    const end = next && next[0].start - last.end <= 0.42 ? Math.min(short4Duration, next[0].start) : naturalEnd;
    const duration = Math.max(0.18, end - start);
    const emphasis = accentIndex(group);
    const text = group.map((word, wordIndex) => {
      const safe = escapeHtml(word.text);
      return wordIndex === emphasis ? `<span class="accent">${safe}</span>` : safe;
    }).join(" ");
    return `        <div id="caption-${String(index + 1).padStart(2, "0")}" class="caption clip" data-start="${start.toFixed(3)}" data-duration="${duration.toFixed(3)}" data-track-index="30">${text}</div>`;
  }).join("\n");
}

const master = JSON.parse(fs.readFileSync(masterPath, "utf8"));
const sourceWords = master.words
  .filter((word) => word.type === "word" && word.start >= sourceStart && word.start < sourceEnd)
  .map((word) => ({
    ...word,
    start: Math.max(0, (word.start - sourceStart) / speed),
    end: Math.min(short4Duration, (word.end - sourceStart) / speed),
  }));
const words = repairWords(sourceWords);
const groups = groupWords(words);
let html = fs.readFileSync(short4Path, "utf8");
const layerStart = html.indexOf('      <div class="caption-layer"');
const layerEnd = html.indexOf("\n      </div>", layerStart);
const openingEnd = html.indexOf("\n", layerStart) + 1;
if (layerStart < 0 || layerEnd < 0 || openingEnd < 1) throw new Error("Short 4 caption layer not found");
html = `${html.slice(0, openingEnd)}${captionHtml(groups)}${html.slice(layerEnd)}`;
fs.writeFileSync(short4Path, html);

const short1Path = path.join(shortsRoot, "short01/index.html");
const short1 = fs.readFileSync(short1Path, "utf8").replaceAll("ali tem um gente", "ali tem gente");
fs.writeFileSync(short1Path, short1);

console.log(`Short 01: corrected \"ali tem gente\"`);
console.log(`Short 04: ${sourceWords.length} source words → ${words.length} repaired words → ${groups.length} continuous captions`);

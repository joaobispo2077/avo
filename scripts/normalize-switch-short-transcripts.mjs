import fs from "node:fs";
import path from "node:path";

const projectRoot = "/mnt/h/bishop/film/brute/dji oslo pocket 3/POV Gameplays/1-GAMEVLOG/ideas/Comparativo Definitivo Nintendo Switch 2 VS OLED VS LITE";
const transcriptDir = path.join(projectRoot, "edit/transcripts");
const qcDir = path.join(projectRoot, "edit/shorts/switch-comparison-shorts-proofs/qc");
const durations = [58.533333, 42.633333, 41.9, 48.233333, 44.133333, 46, 47.5, 57.6, 49.533333, 24.666667];

const replacements = {
  "01": [["LEX", "OLX"], ["consório", "console"]],
  "02": [["colber", "couber"]],
  "03": [["sedição", "edição"], ["PON,", "cupom,"]],
  "04": [["bando", "bundle"], ["bando,", "bundle,"], ["bando.", "bundle."]],
  "05": [["cuton,", "cupom,"], ["cuton.", "cupom."]],
  "06": [["Eele", "Ele"]],
  "07": [["suíte", "Switch"], ["docket,", "dock,"], ["docket", "dock"]],
  "08": [["Ese", "E se"]],
  "10": [["Ese", "E se"]],
};

function replaceTailWithDonkeyKong(words) {
  const phrase = words.map((word) => word.text).join(" ");
  if (!phrase.endsWith("do um que congue bananas.")) return words;
  const tail = words.splice(-5);
  const start = tail[0].start;
  const end = tail.at(-1).end;
  const span = (end - start) / 3;
  words.push(
    { text: "Donkey", start, end: start + span },
    { text: "Kong", start: start + span, end: start + span * 2 },
    { text: "Bananza.", start: start + span * 2, end },
  );
  return words;
}

const report = [];
for (let index = 0; index < 10; index += 1) {
  const number = String(index + 1).padStart(2, "0");
  const basename = `20260809-switch-comparison-short-${number}-master-v001`;
  const transcriptPath = path.join(transcriptDir, `${basename}.json`);
  let words = JSON.parse(fs.readFileSync(transcriptPath, "utf8"));
  const sourceMaxEnd = Math.max(...words.map((word) => Number(word.end) || 0));

  if (number === "04" || number === "09") {
    const scale = (durations[index] - 0.03) / sourceMaxEnd;
    words = words.map((word) => ({
      ...word,
      start: Number((word.start * scale).toFixed(3)),
      end: Number((word.end * scale).toFixed(3)),
    }));
  }

  words = words
    .filter((word) => word.text && !/^[♪�♫]+$/.test(word.text.trim()))
    .map((word) => {
      const replacement = replacements[number]?.find(([from]) => from === word.text)?.[1];
      const start = Math.min(Number(word.start), durations[index] - 0.04);
      const end = Math.max(start + 0.01, Math.min(Number(word.end), durations[index] - 0.02));
      return { text: replacement ?? word.text, start, end };
    });

  if (number === "10") words = replaceTailWithDonkeyKong(words);

  fs.writeFileSync(transcriptPath, `${JSON.stringify(words, null, 2)}\n`);
  report.push({
    short: number,
    duration: durations[index],
    sourceMaxEnd,
    normalizedMaxEnd: Math.max(...words.map((word) => word.end)),
    wordCount: words.length,
    musicTokens: words.filter((word) => /^[♪�♫]+$/.test(word.text.trim())).length,
    text: words.map((word) => word.text).join(" "),
  });
}

fs.writeFileSync(path.join(qcDir, "transcript-quality.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(`Normalized ${report.length} final-file transcripts.`);

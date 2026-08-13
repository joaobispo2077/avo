import fs from "node:fs";
import path from "node:path";

const root = "/mnt/h/bishop/film/brute/dji oslo pocket 3/POV Gameplays/1-GAMEVLOG/ideas/Comparativo Definitivo Nintendo Switch 2 VS OLED VS LITE/edit/shorts/switch-comparison-shorts-proofs";
const pilots = [
  { number: "01", file: "short01/index.html", placement: "upper" },
  { number: "02", file: "index.html", placement: "seam" },
  { number: "03", file: "short03/index.html", placement: "upper" },
  { number: "04", file: "short04/index.html", placement: "seam" },
  { number: "05", file: "short05/index.html", placement: "upper" },
];

const shared = [
  "position:absolute",
  "left:50%",
  "width:max-content",
  "max-width:900px",
  "padding:18px 30px",
  "border-radius:20px",
  "background:linear-gradient(180deg,rgba(17,20,27,.82),rgba(17,20,27,.74))",
  "border:1.5px solid rgba(247,249,252,.34)",
  "box-shadow:0 10px 30px rgba(0,0,0,.38)",
  "text-align:center",
  "font-size:62px",
  "line-height:1.12",
  "font-weight:750",
  "letter-spacing:-.025em",
  "text-transform:uppercase",
  "text-wrap:balance",
].join(";");

for (const pilot of pilots) {
  const file = path.join(root, pilot.file);
  let html = fs.readFileSync(file, "utf8");
  const position = pilot.placement === "upper"
    ? "top:150px;translate:-50% 0"
    : "top:960px;translate:-50% -50%";
  const css = `      .caption { ${shared};${position}; }`;

  html = html
    .replace(/^\s*\.caption \{.*\}$/m, css)
    .replace(/^\s*\.caption \.accent \{.*\}$/m, "      .caption .accent { color:#19d8ff;font-weight:850; }")
    .replace(/tl\.fromTo\(el, \{ y:12,scale:\.94 \}, \{ y:0,scale:1,duration:\.12,ease:'back\.out\(1\.4\)' \}, start\);/g,
      "tl.fromTo(el, { opacity:0,y:8 }, { opacity:1,y:0,duration:.18,ease:'power2.out' }, start);")
    .replaceAll("ali tem um <span class=\"accent\">gente</span>", "ali tem <span class=\"accent\">gente</span>")
    .replaceAll("esse é a <span class=\"accent\">melhor</span>", "essa é a <span class=\"accent\">melhor</span>");

  fs.writeFileSync(file, html);
  console.log(`Short ${pilot.number}: anchor rail applied at ${pilot.placement}`);
}

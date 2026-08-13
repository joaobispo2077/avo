import fs from "node:fs";
import path from "node:path";

const root = "/mnt/h/bishop/film/brute/dji oslo pocket 3/POV Gameplays/1-GAMEVLOG/ideas/Comparativo Definitivo Nintendo Switch 2 VS OLED VS LITE/edit/shorts/switch-comparison-shorts-proofs";

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

function write(relativePath, html) {
  fs.writeFileSync(path.join(root, relativePath), html);
}

function stripGeneratedChrome(html) {
  return html
    .replace(/^\s*\.ambient \{.*\}\n/m, "")
    .replace(/^\s*\.eyebrow \{.*\}\n/m, "")
    .replace(/^\s*\.title \{.*\}\n/m, "")
    .replace(/^\s*\.insert-label \{.*\}\n/m, "")
    .replace(/^\s*\.footer \{.*\}\n/m, "")
    .replace(/^\s*<div class="ambient"><\/div>\n/m, "")
    .replace(/^\s*<div id="insert-label".*<\/div>\n/m, "")
    .replace(/^\s*<div id="format-label".*<\/div>\n/m, "")
    .replace(/^\s*<div id="main-title".*<\/div>\n/m, "")
    .replace(/^\s*<div id="footer-note".*<\/div>\n/m, "")
    .replace(/^\s*tl\.fromTo\('#format-label, #main-title'.*\n/m, "")
    .replace(/^\s*tl\.to\('#main-footage'.*\n/m, "")
    .replace(/^\s*tl\.to\('#insert-footage'.*\n/m, "");
}

for (const number of ["01", "03", "05", "07", "08", "09"]) {
  const relativePath = `short${number}/index.html`;
  let html = stripGeneratedChrome(read(relativePath));
  html = html
    .replace(/^\s*\.main-video \{.*\}\n/m, "      .main-video { position:absolute;inset:0;width:1080px;height:1920px;object-fit:cover;object-position:50% 50%; }\n")
    .replace(/^\s*\.insert-video \{.*\}\n/m, "");
  write(relativePath, html);
}

for (const number of ["04", "06"]) {
  const relativePath = `short${number}/index.html`;
  const html = stripGeneratedChrome(read(relativePath));
  write(relativePath, html);
}

{
  let html = read("index.html");
  html = html
    .replace(/^\s*\.ambient \{.*\}\n/m, "")
    .replace(/^\s*\.pane \{.*\}\n/m, "      .split-video { position:absolute;left:0;width:1080px;height:960px;object-fit:cover; }\n")
    .replace(/^\s*\.pane\.top \{.*\}\n/m, "      .split-video.top { top:0;border-bottom:4px solid #19d8ff; }\n")
    .replace(/^\s*\.pane\.bottom \{.*\}\n/m, "      .split-video.bottom { top:960px; }\n")
    .replace(/^\s*\.pane video \{.*\}\n/m, "")
    .replace(/^\s*\.pane\.top video \{.*\}\n/m, "")
    .replace(/^\s*\.pane\.bottom video \{.*\}\n/m, "")
    .replace(/^\s*\.shade \{.*\}\n/m, "")
    .replace(/^\s*\.label \{.*\}\n/m, "")
    .replace(/^\s*\.label\.left \{.*\}\n/m, "")
    .replace(/^\s*\.label\.right \{.*\}\n/m, "")
    .replace(/^\s*\.context \{.*\}\n/m, "")
    .replace(/^\s*<div class="ambient"><\/div>\n/m, "")
    .replace(/^\s*<div class="pane top">.*\n/m, "      <video id=\"switch-footage\" class=\"clip split-video top\" src=\"assets/short02-main-gop.mp4\" data-start=\"0\" data-duration=\"42.61\" data-track-index=\"1\" muted playsinline></video>\n")
    .replace(/^\s*<div class="pane bottom">.*\n/m, "      <video id=\"gameplay-footage\" class=\"clip split-video bottom\" src=\"assets/short02-insert-gop.mp4\" data-start=\"0\" data-duration=\"42.61\" data-track-index=\"2\" muted playsinline></video>\n")
    .replace(/^\s*<div id="rule-label".*\n/m, "")
    .replace(/^\s*<div id="debt-label".*\n/m, "")
    .replace(/^\s*<div id="context-note".*\n/m, "")
    .replace(/^\s*tl\.fromTo\('\.label'.*\n/m, "")
    .replace(/^\s*tl\.to\('#switch-footage'.*\n/m, "")
    .replace(/^\s*tl\.to\('#gameplay-footage'.*\n/m, "");
  write("index.html", html);
}

{
  let html = read("short10/index.html");
  html = html
    .replace(/^\s*\.ambient \{.*\}\n/m, "")
    .replace(/^\s*\.eyebrow \{.*\}\n/m, "")
    .replace(/^\s*\.title \{.*\}\n/m, "")
    .replace(/^\s*\.screen \{.*\}\n/m, "      .product-video { position:absolute;inset:0;width:1080px;height:1920px;object-fit:cover;object-position:50% 50%; }\n")
    .replace(/^\s*\.screen video \{.*\}\n/m, "")
    .replace(/^\s*\.screen::after \{.*\}\n/m, "")
    .replace(/^\s*\.choices \{.*\}\n/m, "")
    .replace(/^\s*\.choice \{.*\}\n/m, "")
    .replace(/^\s*\.choice strong \{.*\}\n/m, "")
    .replace(/^\s*\.choice span \{.*\}\n/m, "")
    .replace(/^\s*\.choice\.active \{.*\}\n/m, "")
    .replace(/^\s*\.foot \{.*\}\n/m, "")
    .replace(/^\s*<div class="ambient"><\/div>\n/m, "")
    .replace(/^\s*<div id="format-label".*\n/m, "")
    .replace(/^\s*<div id="main-title".*\n/m, "")
    .replace(/^\s*<div class="screen"><video (.*)<\/video><\/div>\n/m, "      <video $1</video>\n")
    .replace('class="clip" src="assets/short10-main-gop.mp4"', 'class="clip product-video" src="assets/short10-main-gop.mp4"')
    .replace(/\n\s*<div class="choices">[\s\S]*?(?=\n\s*<div id="footer-note")/, "")
    .replace(/^\s*<div id="footer-note".*\n/m, "")
    .replace(/^\s*tl\.fromTo\('\.eyebrow, \.title'.*\n/m, "")
    .replace(/^\s*tl\.to\('#choice-.*\n/gm, "")
    .replace(/^\s*tl\.to\('#product-footage'.*\n/m, "");
  write("short10/index.html", html);
}

console.log("Revised ten Shorts to footage + punchy captions only.");

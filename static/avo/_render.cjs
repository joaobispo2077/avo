// Keyless SVG -> PNG rasterizer for AVO brand assets (uses bundled sharp/librsvg).
// Cross-platform. Usage: node _render.cjs <in.svg> <out.png> <width> [height]
const sharp = require('sharp');
const fs = require('fs');

async function main() {
  const [, , input, output, wArg, hArg] = process.argv;
  if (!input || !output || !wArg) {
    console.error('usage: node _render.cjs <in.svg> <out.png> <width> [height]');
    process.exit(1);
  }
  const width = parseInt(wArg, 10);
  const height = hArg ? parseInt(hArg, 10) : undefined;
  const svg = fs.readFileSync(input);
  const opts = { density: 384 };
  const img = sharp(svg, opts).resize({ width, height, fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 0 } });
  await img.png().toFile(output);
  const meta = await sharp(output).metadata();
  console.log(`wrote ${output} ${meta.width}x${meta.height}`);
}
main().catch((e) => { console.error(e); process.exit(1); });

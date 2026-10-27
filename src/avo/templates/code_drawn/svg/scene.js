/* Generic local SVG drawing. Editorial placement belongs to AVO's timeline. */
(() => {
  'use strict';

  const width = __WIDTH__;
  const height = __HEIGHT__;
  const background = __BACKGROUND__;
  const seed = __SEED__;
  const frameCount = __FRAMES__;
  const rate = { num: __FPS_NUM__, den: __FPS_DEN__ };
  const duration = (frameCount * rate.den) / rate.num;
  const shortSide = Math.min(width, height);
  const portrait = width / height < 0.82;
  const compact = width <= height;
  const byId = (id) => document.getElementById(id);
  const clamp = (value) => Math.max(0, Math.min(1, value));
  const ease = (value) => 1 - Math.pow(1 - clamp(value), 3);
  const attributes = (element, values) => {
    for (const [key, value] of Object.entries(values)) {
      element.setAttribute(key, String(value));
    }
  };

  // Each call starts from the same source values, including this seed offset.
  let seedValue = 0;
  for (const character of String(seed)) {
    seedValue = (Math.imul(seedValue, 31) + character.charCodeAt(0)) >>> 0;
  }

  const inset = shortSide * 0.08;
  const panel = {
    x: inset,
    y: height * (portrait ? 0.13 : 0.12),
    width: width - 2 * inset,
    height: height * (portrait ? 0.74 : 0.76),
  };
  const textX = panel.x + panel.width * 0.09;
  const titleSize = Math.min(
    shortSide * 0.095,
    panel.width / (compact ? 6.8 : 11.2),
  );
  const smallSize = Math.min(shortSide * 0.06, panel.width / 13);
  const titleY = panel.y + panel.height * (compact ? 0.29 : 0.35);
  const shapesY = panel.y + panel.height * (portrait ? 0.68 : 0.66);
  const radius = Math.min(panel.width / 15, panel.height * 0.095);
  const centers = [0.24, 0.5, 0.76].map(
    (fraction) => panel.x + panel.width * fraction,
  );
  const groups = ['shape-one', 'shape-two', 'shape-three'].map(byId);

  attributes(byId('backdrop'), {
    fill: background === null ? 'none' : background,
  });
  attributes(byId('panel'), {
    x: panel.x,
    y: panel.y,
    width: panel.width,
    height: panel.height,
    rx: shortSide * 0.035,
    'stroke-width': Math.max(1, shortSide * 0.002),
  });
  attributes(byId('eyebrow'), {
    x: textX,
    y: panel.y + panel.height * 0.14,
    'font-size': smallSize,
    'letter-spacing': smallSize * 0.08,
  });
  attributes(byId('headline-one'), {
    x: textX,
    y: titleY,
    'font-size': titleSize,
  });
  attributes(byId('headline-two'), {
    x: textX,
    y: titleY + titleSize * 1.15,
    'font-size': titleSize,
  });
  byId('headline-one').textContent = compact
    ? 'Code-drawn'
    : 'Code-drawn motion';
  byId('headline-two').textContent = compact ? 'motion' : '';
  attributes(byId('connector'), {
    d: `M ${centers[0]} ${shapesY} H ${centers[2]}`,
    'stroke-width': Math.max(1, shortSide * 0.003),
  });
  attributes(byId('circle'), { cx: 0, cy: 0, r: radius });
  attributes(byId('square'), {
    x: -radius,
    y: -radius,
    width: 2 * radius,
    height: 2 * radius,
    rx: radius * 0.22,
  });
  attributes(byId('diamond'), {
    d: `M 0 ${-radius * 1.2} L ${radius * 1.2} 0 L 0 ${radius * 1.2} L ${-radius * 1.2} 0 Z`,
  });
  attributes(byId('footer'), {
    x: width / 2,
    y: panel.y + panel.height * 0.91,
    'font-size': smallSize,
  });

  function draw(tSeconds) {
    const time = Number(tSeconds);
    if (!Number.isFinite(time)) {
      throw new RangeError('seek requires a finite composition-local time');
    }
    const phase = clamp(time / duration);
    const entry = ease(phase / 0.16);
    const exit = ease((1 - phase) / 0.16);
    const distance = shortSide * 0.035;
    const offset = distance * (1 - entry) - distance * (1 - exit);

    // One dominant entry/exit; text and settled geometry hold still for reading.
    attributes(byId('card'), {
      opacity: entry * exit,
      transform: `translate(0 ${offset})`,
    });
    groups.forEach((group, index) => {
      const delay =
        0.09 + index * 0.035 + ((seedValue + index * 7) % 13) * 0.001;
      const reveal = ease((phase - delay) / 0.12);
      const scale = 0.72 + reveal * 0.28;
      attributes(group, {
        opacity: reveal,
        transform: `translate(${centers[index]} ${shapesY}) scale(${scale})`,
      });
    });
    return true;
  }

  window.seek = async (tSeconds) => draw(tSeconds);
  window.avoReady = (async () => {
    // Built-in sans-serif is generic; exact font metrics belong to the recorded
    // rendering environment. A production brief may declare local font assets.
    await Promise.all([
      document.fonts.load(`700 ${titleSize}px sans-serif`),
      document.fonts.load(`600 ${smallSize}px sans-serif`),
      document.fonts.load(`400 ${smallSize}px sans-serif`),
    ]);
    await document.fonts.ready;
    draw(0);
    return true;
  })();

  if (!window.__AVO_RENDER__) {
    window.avoReady.then(() => {
      const started = performance.now();
      const preview = (now) => {
        draw(((now - started) / 1000) % duration);
        window.requestAnimationFrame(preview);
      };
      window.requestAnimationFrame(preview);
    });
  }
})();

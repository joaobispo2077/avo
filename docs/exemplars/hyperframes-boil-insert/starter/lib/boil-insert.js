/**
 * Boil insert module — deterministic wiggly/boiling effect for HyperFrames overlays.
 * Maps DaVinci Fusion Displace + Fast Noise to feTurbulence + feDisplacementMap + GSAP seed.
 */
(function (global) {
  "use strict";

  const DEFAULTS = {
    filterId: "boil-filter",
    baseFrequency: 0.02,
    numOctaves: 3,
    scale: 10,
    seedStart: 1,
    fps: 9,
    xChannelSelector: "R",
    yChannelSelector: "G",
  };

  function prefersReducedMotion() {
    return (
      global.matchMedia &&
      global.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function ensureSvgDefs(root) {
    const mount = root || document.body;
    let svg = mount.querySelector("svg.boil-defs");
    if (!svg) {
      svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "boil-defs");
      svg.setAttribute("width", "0");
      svg.setAttribute("height", "0");
      svg.setAttribute("aria-hidden", "true");
      svg.style.position = "absolute";
      svg.style.width = "0";
      svg.style.height = "0";
      svg.style.overflow = "hidden";
      const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
      svg.appendChild(defs);
      mount.prepend(svg);
    }
    return svg.querySelector("defs") || svg;
  }

  /**
   * @param {HTMLElement} root
   * @param {object} options
   * @returns {{ filter: Element, turb: Element, disp: Element, filterUrl: string, opts: object }}
   */
  function createBoilFilter(root, options) {
    const opts = { ...DEFAULTS, ...(options || {}) };
    const defs = ensureSvgDefs(root);
    let filter = defs.querySelector("#" + opts.filterId);
    if (!filter) {
      filter = document.createElementNS("http://www.w3.org/2000/svg", "filter");
      filter.setAttribute("id", opts.filterId);
      filter.setAttribute("x", "-20%");
      filter.setAttribute("y", "-20%");
      filter.setAttribute("width", "140%");
      filter.setAttribute("height", "140%");

      const turb = document.createElementNS("http://www.w3.org/2000/svg", "feTurbulence");
      turb.setAttribute("type", "fractalNoise");
      turb.setAttribute("baseFrequency", String(opts.baseFrequency));
      turb.setAttribute("numOctaves", String(opts.numOctaves));
      turb.setAttribute("seed", String(opts.seedStart));
      turb.setAttribute("result", "noise");

      const disp = document.createElementNS("http://www.w3.org/2000/svg", "feDisplacementMap");
      disp.setAttribute("in", "SourceGraphic");
      disp.setAttribute("in2", "noise");
      disp.setAttribute("scale", String(opts.scale));
      disp.setAttribute("xChannelSelector", opts.xChannelSelector);
      disp.setAttribute("yChannelSelector", opts.yChannelSelector);

      filter.appendChild(turb);
      filter.appendChild(disp);
      defs.appendChild(filter);
    }

    const turbEl = filter.querySelector("feTurbulence");
    const dispEl = filter.querySelector("feDisplacementMap");
    if (opts.baseFrequency != null) {
      turbEl.setAttribute("baseFrequency", String(opts.baseFrequency));
    }
    if (opts.numOctaves != null) {
      turbEl.setAttribute("numOctaves", String(opts.numOctaves));
    }
    if (opts.scale != null) {
      dispEl.setAttribute("scale", String(opts.scale));
    }
    turbEl.setAttribute("seed", String(opts.seedStart));

    return {
      filter,
      turb: turbEl,
      disp: dispEl,
      filterUrl: "url(#" + opts.filterId + ")",
      opts,
    };
  }

  /**
   * @param {gsap.core.Timeline} timeline
   * @param {Element} turbEl feTurbulence element
   * @param {object} options duration, fps, seedStart, startTime, rhythmicLoop
   */
  function applyBoil(timeline, turbEl, options) {
    const opts = { ...DEFAULTS, ...(options || {}) };
    if (prefersReducedMotion()) {
      return timeline;
    }
    if (!turbEl || !timeline) {
      return timeline;
    }

    const duration = opts.duration != null ? opts.duration : timeline.duration();
    const fps = opts.fps != null ? opts.fps : 9;
    const steps = Math.max(1, Math.ceil(duration * fps));
    const seedStart = opts.seedStart != null ? opts.seedStart : 1;
    const startTime = opts.startTime != null ? opts.startTime : 0;

    const state = { seed: seedStart };
    if (opts.rhythmicLoop && opts.loopSeeds && opts.loopSeeds.length) {
      const seeds = opts.loopSeeds;
      const stepDur = 1 / fps;
      for (let i = 0; i < steps; i++) {
        const t = startTime + i * stepDur;
        const seed = seeds[i % seeds.length];
        timeline.set(turbEl, { attr: { seed: String(seed) } }, t);
      }
    } else {
      timeline.to(
        state,
        {
          seed: seedStart + steps,
          duration: duration,
          ease: "steps(" + steps + ")",
          onUpdate: function () {
            turbEl.setAttribute("seed", String(Math.floor(state.seed)));
          },
        },
        startTime
      );
    }
    return timeline;
  }

  function wrapBoilContent(element, filterUrl) {
    if (!element) {
      return element;
    }
    element.style.filter = filterUrl;
    return element;
  }

  global.BoilInsert = {
    DEFAULTS,
    prefersReducedMotion,
    createBoilFilter,
    applyBoil,
    wrapBoilContent,
  };
})(typeof window !== "undefined" ? window : globalThis);

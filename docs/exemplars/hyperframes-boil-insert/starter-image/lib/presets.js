/**
 * Named boil intensity presets for provider defaults and agent authoring.
 */
(function (global) {
  "use strict";

  const PRESETS = {
    subtle: {
      name: "subtle",
      scale: 4,
      baseFrequency: 0.015,
      numOctaves: 2,
      fps: 8,
      seedStart: 1,
    },
    standard: {
      name: "standard",
      scale: 10,
      baseFrequency: 0.02,
      numOctaves: 3,
      fps: 9,
      seedStart: 1,
    },
    wild: {
      name: "wild",
      scale: 22,
      baseFrequency: 0.03,
      numOctaves: 4,
      fps: 12,
      seedStart: 1,
    },
  };

  function getPreset(name) {
    const key = (name || "standard").toLowerCase();
    return { ...(PRESETS[key] || PRESETS.standard) };
  }

  function listPresets() {
    return Object.keys(PRESETS);
  }

  function mergePreset(name, overrides) {
    return { ...getPreset(name), ...(overrides || {}) };
  }

  global.BoilPresets = {
    PRESETS,
    getPreset,
    listPresets,
    mergePreset,
  };
})(typeof window !== "undefined" ? window : globalThis);

(() => {
  "use strict";
  const initialize = () => {
  const root = document.querySelector("[data-composition-id]");
  const phrases = __CAPTION_JSON__;
  const duration = Number(root.dataset.duration);
  const timeline = window.__timelines[root.dataset.compositionId];

  document.querySelectorAll(".caption-phrase").forEach((node) => {
    gsap.set(node, { autoAlpha: 0, y: 10 });
  });
  document.querySelectorAll(".caption-word").forEach((node) => {
    gsap.set(node, { backgroundColor: "transparent", color: "inherit" });
  });

  for (const phrase of phrases) {
    const phraseNode = document.getElementById(phrase.id);
    const wordNodes = phrase.words.map((word) => document.getElementById(word.id));

    // A phrase owns its whole state. Both boundaries clear every word so
    // arbitrary seeks can never inherit the previous phrase's highlight.
    timeline.set(wordNodes, { backgroundColor: "transparent", color: "inherit" }, phrase.startSec);
    timeline.set(phraseNode, { autoAlpha: 1, y: 0 }, phrase.startSec);
    for (const word of phrase.words) {
      const node = document.getElementById(word.id);
      const activeBackground = word.punch
        ? "var(--short-punch)"
        : "var(--short-accent)";
      const activeColor = "#17120a";
      timeline.set(node, { backgroundColor: activeBackground, color: activeColor }, word.highlightEnterSec);
      timeline.set(node, { backgroundColor: "transparent", color: "inherit" }, word.highlightExitSec);
    }
    timeline.set(wordNodes, { backgroundColor: "transparent", color: "inherit" }, phrase.endSec);
    timeline.set(phraseNode, { autoAlpha: 0, y: -8 }, phrase.endSec);
  }

  timeline.to({}, { duration }, 0);
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();

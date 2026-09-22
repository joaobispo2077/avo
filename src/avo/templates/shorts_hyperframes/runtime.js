(() => {
  "use strict";
  const initialize = () => {
  const root = document.querySelector("[data-composition-id]");
  const phrases = __CAPTION_JSON__;
  const callouts = __CALLOUT_JSON__;
  const punchIns = __PUNCHIN_JSON__;
  const graphics = __GRAPHIC_JSON__;
  const duration = Number(root.dataset.duration);
  const uiScale =
    Number.parseFloat(getComputedStyle(root).getPropertyValue("--ui-scale")) || 1;
  const timeline = window.__timelines[root.dataset.compositionId];
  const reducedMotion =
    typeof matchMedia === "function" &&
    matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reducedMotion) {
    gsap.defaults({ duration: 0 });
  }

  document.querySelectorAll(".caption-phrase").forEach((node) => {
    gsap.set(node, { autoAlpha: 0, y: 10 * uiScale });
  });
  document.querySelectorAll(".caption-word").forEach((node) => {
    gsap.set(node, { backgroundColor: "transparent", color: "inherit" });
  });
  document.querySelectorAll(".callout").forEach((node) => {
    const centered = node.classList.contains("corner-bc");
    gsap.set(node, {
      autoAlpha: 0,
      scale: 0.94,
      transformOrigin: "50% 50%",
      xPercent: centered ? -50 : 0,
    });
  });
  document.querySelectorAll(".graphic").forEach((node) => {
    const centered = node.classList.contains("corner-bc");
    gsap.set(node, { autoAlpha: 0, xPercent: centered ? -50 : 0 });
  });
  const wrap = document.getElementById("base-wrap");
  if (wrap) {
    gsap.set(wrap, { scale: 1, transformOrigin: "50% 50%" });
  }

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
    timeline.set(phraseNode, { autoAlpha: 0, y: -8 * uiScale }, phrase.endSec);
  }

  for (const callout of callouts) {
    const node = document.getElementById(callout.id);
    if (!node) continue;
    const centered = node.classList.contains("corner-bc");
    timeline.set(node, { autoAlpha: 1, scale: 1, xPercent: centered ? -50 : 0 }, callout.startSec);
    timeline.set(node, { autoAlpha: 0, scale: 0.94, xPercent: centered ? -50 : 0 }, callout.endSec);
  }

  if (wrap) {
    for (const punch of punchIns) {
      timeline.set(wrap, { scale: punch.scale || 1.08 }, punch.startSec);
      const overlapping = punchIns.filter(
        (other) => other.startSec < punch.endSec && other.endSec > punch.endSec
      );
      const restore = overlapping.length
        ? overlapping[overlapping.length - 1].scale || 1.08
        : 1;
      timeline.set(wrap, { scale: restore }, punch.endSec);
    }
  }

  const showGraphic = (node, startSec, endSec) => {
    const centered = node.classList.contains("corner-bc");
    timeline.set(node, { autoAlpha: 1, xPercent: centered ? -50 : 0 }, startSec);
    timeline.set(node, { autoAlpha: 0, xPercent: centered ? -50 : 0 }, endSec);
  };

  const driveStars = (graphic, node) => {
    const params = graphic.params || {};
    const total = Math.max(1, Number(params.total) || 5);
    const filled = Math.max(0, Number(params.filled) || 0);
    const whole = Math.floor(filled + 1e-9);
    const frac = Math.min(1, Math.max(0, filled - whole));
    const stagger = Number(params.fillStaggerSec) || 0.12;
    showGraphic(node, graphic.startSec, graphic.endSec);
    for (let index = 1; index <= total; index += 1) {
      const fill = node.querySelector(`#${graphic.id}-star-${index} .star-fill`);
      if (!fill) continue;
      gsap.set(fill, {
        scaleY: 0,
        transformOrigin: "50% 100%",
        clipPath: "inset(0 0% 0 0)",
      });
      const amount = index <= whole ? 1 : index === whole + 1 ? frac : 0;
      if (amount <= 0) continue;
      const fillAt = graphic.startSec + (index - 1) * (reducedMotion ? 0 : stagger);
      timeline.to(
        fill,
        {
          scaleY: 1,
          clipPath: `inset(0 ${(1 - amount) * 100}% 0 0)`,
          duration: reducedMotion ? 0 : stagger,
          ease: "none",
        },
        fillAt
      );
    }
  };

  const driveStackResolve = (graphic, node) => {
    const params = graphic.params || {};
    const items = params.items || [];
    const resolveAt = Number(params.resolveAtSec) || graphic.endSec;
    showGraphic(node, graphic.startSec, graphic.endSec);
    items.forEach((item, index) => {
      const plate = document.getElementById(`${graphic.id}-plate-${index + 1}`);
      if (!plate) return;
      const at = item && item.startSec != null ? Number(item.startSec) : graphic.startSec;
      gsap.set(plate, { autoAlpha: 0, y: 8 });
      timeline.set(plate, { autoAlpha: 1, y: 0 }, at);
      timeline.set(plate, { autoAlpha: 0, scale: 0.86 }, resolveAt);
    });
    const lockup = document.getElementById(`${graphic.id}-lockup`);
    if (lockup) {
      gsap.set(lockup, { autoAlpha: 0, scale: 0.9 });
      timeline.set(lockup, { autoAlpha: 1, scale: 1 }, resolveAt);
    }
  };

  const driveVsReject = (graphic, node) => {
    const params = graphic.params || {};
    showGraphic(node, graphic.startSec, graphic.endSec);
    const reject = document.getElementById(`${graphic.id}-reject`);
    const confirm = document.getElementById(`${graphic.id}-confirm`);
    const badge = document.getElementById(`${graphic.id}-badge`);
    const rejectAt = Number((params.reject || {}).atSec) || graphic.startSec;
    const confirmAt = Number((params.confirm || {}).atSec) || graphic.startSec;
    const badgeAt = Number((params.badge || {}).atSec) || graphic.startSec;
    if (reject) {
      gsap.set(reject, { autoAlpha: 0 });
      timeline.set(reject, { autoAlpha: 1 }, rejectAt);
      const mark = reject.querySelector(".vs-x");
      if (mark) {
        gsap.set(mark, { autoAlpha: 0, scale: 0.6 });
        timeline.set(mark, { autoAlpha: 1, scale: 1 }, rejectAt);
      }
    }
    if (confirm) {
      gsap.set(confirm, { autoAlpha: 0, scale: 0.94 });
      timeline.set(confirm, { autoAlpha: 1, scale: 1 }, confirmAt);
    }
    if (badge) {
      gsap.set(badge, { autoAlpha: 0 });
      timeline.set(badge, { autoAlpha: 1 }, badgeAt);
    }
  };

  const driveFlip180 = (graphic, node) => {
    const card = document.getElementById(`${graphic.id}-card`);
    showGraphic(node, graphic.startSec, graphic.endSec);
    if (!card) return;
    gsap.set(card, { rotationY: 0, transformOrigin: "50% 50%" });
    timeline.to(card, { rotationY: 180, duration: 0.42, ease: "power2.out" }, graphic.startSec);
  };

  const driveCoverWipe = (graphic, node) => {
    const params = graphic.params || {};
    const cover = document.getElementById(`${graphic.id}-cover`);
    const wipeAt = Number(params.wipeAtSec) || graphic.startSec;
    showGraphic(node, graphic.startSec, graphic.endSec);
    if (!cover) return;
    gsap.set(cover, { clipPath: "inset(0 100% 0 0)" });
    timeline.to(
      cover,
      { clipPath: "inset(0 0% 0 0)", duration: 0.4, ease: "power2.inOut" },
      wipeAt
    );
  };

  const driveRatioLock = (graphic, node) => {
    showGraphic(node, graphic.startSec, graphic.endSec);
    const frame = node.querySelector(".ratio-frame");
    if (!frame) return;
    gsap.set(frame, { scale: 0.86 });
    timeline.set(frame, { scale: 1 }, graphic.startSec);
  };

  const driveDurationMeter = (graphic, node) => {
    const params = graphic.params || {};
    const ticks = Math.max(1, Number(params.ticks) || 3);
    const stagger = Number(params.fillStaggerSec) || 0.18;
    const fill = document.getElementById(`${graphic.id}-fill`);
    const meta = document.getElementById(`${graphic.id}-metacritic`);
    const metaAt = Number(params.metacriticAtSec) || graphic.endSec;
    const hold = Number(params.meterHoldSec) || 3.6;
    showGraphic(node, graphic.startSec, graphic.endSec);
    if (fill) {
      gsap.set(fill, { scaleX: 0, transformOrigin: "0% 50%" });
      timeline.to(
        fill,
        { scaleX: 1, duration: ticks * stagger, ease: "none" },
        graphic.startSec
      );
    }
    const meter = node.querySelector(".meter-block");
    if (meter) {
      timeline.set(meter, { autoAlpha: 0 }, graphic.startSec + hold);
    }
    if (meta) {
      gsap.set(meta, { autoAlpha: 0 });
      timeline.set(meta, { autoAlpha: 1 }, metaAt);
    }
  };

  const driveTwoRoles = (graphic, node) => {
    const params = graphic.params || {};
    const roles = params.roles || [];
    showGraphic(node, graphic.startSec, graphic.endSec);
    roles.forEach((role, index) => {
      const tile = document.getElementById(`${graphic.id}-role-${index + 1}`);
      if (!tile) return;
      const at = role && role.atSec != null ? Number(role.atSec) : graphic.startSec;
      gsap.set(tile, { autoAlpha: 0, y: 8 });
      timeline.set(tile, { autoAlpha: 1, y: 0 }, at);
    });
    const down = document.getElementById(`${graphic.id}-downbeat`);
    if (down) {
      const at = Number(params.downbeatAtSec) || graphic.endSec;
      gsap.set(down, { autoAlpha: 0 });
      timeline.set(down, { autoAlpha: 1 }, at);
    }
  };

  const driveBadgePair = (graphic, node) => {
    const params = graphic.params || {};
    const badges = params.badges || [];
    showGraphic(node, graphic.startSec, graphic.endSec);
    badges.forEach((badge, index) => {
      const chip = document.getElementById(`${graphic.id}-badge-${index + 1}`);
      if (!chip) return;
      const at = badge && badge.atSec != null ? Number(badge.atSec) : graphic.startSec;
      gsap.set(chip, { autoAlpha: 0, scale: 0.94 });
      timeline.set(chip, { autoAlpha: 1, scale: 1 }, at);
    });
  };

  const drivePriceDuel = (graphic, node) => {
    showGraphic(node, graphic.startSec, graphic.endSec);
    const physical = document.getElementById(`${graphic.id}-physical`);
    const digital = document.getElementById(`${graphic.id}-digital`);
    if (physical) {
      gsap.set(physical, { scale: 0.94 });
      timeline.set(physical, { scale: 1 }, graphic.startSec);
    }
    if (digital) {
      gsap.set(digital, { autoAlpha: 0.7 });
    }
  };

  const drivers = {
    stars: driveStars,
    "stack-resolve": driveStackResolve,
    "vs-reject": driveVsReject,
    "flip-180": driveFlip180,
    "cover-wipe": driveCoverWipe,
    "ratio-lock": driveRatioLock,
    "duration-meter": driveDurationMeter,
    "two-roles": driveTwoRoles,
    "badge-pair": driveBadgePair,
    "price-duel": drivePriceDuel,
  };

  for (const graphic of graphics) {
    const node = document.getElementById(graphic.id);
    if (!node) continue;
    const driver = drivers[graphic.widget];
    if (driver) driver(graphic, node);
    else showGraphic(node, graphic.startSec, graphic.endSec);
  }

  timeline.to({}, { duration }, 0);
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();

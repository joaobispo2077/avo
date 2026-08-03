/**
 * Insert lifecycle — entrance, boil hold, exit. Boil active only during hold.
 */
(function (global) {
  "use strict";

  /**
   * @param {gsap.core.Timeline} timeline
   * @param {Element|string} target
   * @param {object} phases
   * @param {object} phases.entrance { start, duration, from, ease }
   * @param {object} phases.hold { start, duration }
   * @param {object} phases.exit { start, duration, to, ease }
   */
  function scheduleInsertLifecycle(timeline, target, phases) {
    if (!timeline || !target || !phases) {
      return timeline;
    }
    const p = phases;
    if (p.entrance) {
      const e = p.entrance;
      timeline.from(
        target,
        {
          ...(e.from || { opacity: 0, y: 24 }),
          duration: e.duration != null ? e.duration : 0.4,
          ease: e.ease || "power3.out",
        },
        e.start != null ? e.start : 0
      );
    }
    if (p.exit) {
      const x = p.exit;
      timeline.to(
        target,
        {
          ...(x.to || { opacity: 0, y: -12 }),
          duration: x.duration != null ? x.duration : 0.35,
          ease: x.ease || "power2.in",
        },
        x.start != null ? x.start : 0
      );
    }
    return timeline;
  }

  /** Resolve Displace Offset — re-center after displacement drift */
  function applyCenterOffset(element, offset) {
    if (!element || !offset) {
      return element;
    }
    const x = offset.x != null ? offset.x : 0;
    const y = offset.y != null ? offset.y : 0;
    const existing = element.style.transform || "";
    const base = existing && existing !== "none" ? existing + " " : "";
    element.style.transform = base + "translate(" + x + "px, " + y + "px)";
    return element;
  }

  /**
   * Returns hold window for applyBoil — boil only while insert is on screen and settled.
   */
  function boilHoldWindow(phases) {
    if (!phases || !phases.hold) {
      return { startTime: 0, duration: 1 };
    }
    return {
      startTime: phases.hold.start != null ? phases.hold.start : 0,
      duration: phases.hold.duration != null ? phases.hold.duration : 1,
    };
  }

  global.BoilLifecycle = {
    scheduleInsertLifecycle,
    applyCenterOffset,
    boilHoldWindow,
  };
})(typeof window !== "undefined" ? window : globalThis);

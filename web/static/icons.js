import { createMorph } from "./vendor/morphicons/dom.js";
import { ICONS } from "./icon-data.js";

const namespace = "http://www.w3.org/2000/svg";
const drivers = new WeakMap();
const mounted = new Set();
const motionPolicy = () => document.documentElement.dataset.motion === "reduced" ? "always" : "never";

// Keep one path and driver per SVG so rapid state changes remain interruptible.
export function setIcon(element, name, { animate = true } = {}) {
  const svg = element?.matches("svg") ? element : element?.querySelector("svg[data-icon]");
  if (!svg || !ICONS[name]) return;
  let entry = drivers.get(svg);
  if (!entry) {
    const path = document.createElementNS(namespace, "path");
    svg.replaceChildren(path);
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    entry = { svg, name, morph: createMorph(path, ICONS[name], { reducedMotion: motionPolicy() }) };
    drivers.set(svg, entry);
    mounted.add(entry);
  } else if (entry.name !== name) {
    entry.name = name;
    entry.morph.reducedMotion = motionPolicy();
    if (animate) entry.morph.morphTo(ICONS[name], "snappy");
    else entry.morph.set(ICONS[name]);
  }
  svg.dataset.icon = name;
}

export function mountIcons(scope = document) {
  scope.querySelectorAll("svg[data-icon]").forEach((svg) => setIcon(svg, svg.dataset.icon));
}

export function syncIconMotion() {
  const policy = motionPolicy();
  for (const entry of mounted) {
    entry.morph.reducedMotion = policy;
    if (policy === "always") entry.morph.set(ICONS[entry.name]);
  }
}

export function destroyIcons(scope) {
  for (const entry of mounted) {
    if (scope.contains(entry.svg)) {
      entry.morph.destroy();
      drivers.delete(entry.svg);
      mounted.delete(entry);
    }
  }
}

export function iconMarkup(name) {
  if (!ICONS[name]) return "";
  return `<svg data-icon="${name}" viewBox="0 0 24 24" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

export function setButtonLoading(button, loading) {
  const svg = button?.querySelector("svg[data-icon]");
  if (!svg) return;
  if (!svg.dataset.restIcon) svg.dataset.restIcon = svg.dataset.icon;
  setIcon(svg, loading ? "loading" : svg.dataset.restIcon);
  svg.classList.toggle("icon-loading", loading);
  button.setAttribute("aria-busy", String(loading));
}

window.addEventListener("pagehide", (event) => {
  if (!event.persisted) destroyIcons(document);
});

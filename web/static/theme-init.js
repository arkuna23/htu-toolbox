/* Applies saved workspace preferences before first paint.
   Kept as a separate file because the page ships a strict style-src 'self' CSP,
   so inline <script> is not an option. */
(function () {
  "use strict";
  var root = document.documentElement;
  var defaults = {
    themeMode: "dark",
    paletteId: "iris",
    density: "standard",
    motion: "system",
    compactNav: false,
    locale: "zh-CN",
  };
  var settings = defaults;
  try {
    var raw = localStorage.getItem("htu-toolbox.settings.v1");
    if (raw) {
      var parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        settings = {
          themeMode: typeof parsed.themeMode === "string" ? parsed.themeMode : defaults.themeMode,
          paletteId: typeof parsed.paletteId === "string" ? parsed.paletteId : defaults.paletteId,
          density: typeof parsed.density === "string" ? parsed.density : defaults.density,
          motion: typeof parsed.motion === "string" ? parsed.motion : defaults.motion,
          compactNav: parsed.compactNav === true,
          locale: typeof parsed.locale === "string" ? parsed.locale : defaults.locale,
        };
      }
    }
  } catch (error) {
    settings = defaults;
  }

  var prefersLight =
    window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  var prefersReduced =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var dark =
    settings.themeMode === "dark" ||
    (settings.themeMode === "system" && !prefersLight);

  root.classList.toggle("dark", dark);
  root.classList.toggle("light", !dark);
  root.dataset.theme = dark ? "dark" : "light";
  root.dataset.palette = settings.paletteId;
  root.dataset.density = settings.density;
  root.dataset.motion =
    settings.motion === "system" ? (prefersReduced ? "reduced" : "full") : settings.motion;
  root.dataset.compactNav = String(settings.compactNav);
  root.lang = settings.locale;
  root.style.colorScheme = dark ? "dark" : "light";

  // Exposed so the settings dialog can read the same resolved values.
  window.__htuSettings = settings;
})();

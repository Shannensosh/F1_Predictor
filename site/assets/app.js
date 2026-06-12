/* Velocity Strike · F1·26 — shared helpers
   Static pages are rendered server-side by build.py; this file provides the
   shared nav toggle, small formatters, and geo/charts helpers reused inline. */
(function () {
  "use strict";

  // mobile nav
  window.toggleMenu = function () {
    var n = document.querySelector("nav.tabs");
    if (n) n.classList.toggle("open");
  };

  // read the inlined DATA blob a page embeds as <script id="DATA" type="application/json">
  window.PAGE_DATA = function () {
    var el = document.getElementById("DATA");
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  };

  // formatters
  window.F = {
    pct: function (v, d) { return (v == null ? "–" : (+v).toFixed(d == null ? 1 : d) + "%"); },
    n1: function (v) { return v == null ? "–" : (+v).toFixed(1); },
    int: function (v) { return v == null ? "–" : Math.round(v); },
    ord: function (n) {
      n = +n; var s = ["th", "st", "nd", "rd"], v = n % 100;
      return n + (s[(v - 20) % 10] || s[v] || s[0]);
    },
    clock: function (sec) {
      sec = Math.max(0, Math.floor(sec));
      var m = Math.floor(sec / 60), s = sec % 60;
      return m + ":" + (s < 10 ? "0" : "") + s;
    }
  };

  // equirectangular projection: (lat,long) -> {x,y} within a w×h box
  window.project = function (lat, lon, w, h) {
    return { x: (lon + 180) / 360 * w, y: (90 - lat) / 180 * h };
  };

  // build an SVG path "d" from an array of [x,y]
  window.polyPath = function (pts, close) {
    if (!pts || !pts.length) return "";
    var d = "M" + pts.map(function (p) { return p[0] + "," + p[1]; }).join("L");
    return close ? d + "Z" : d;
  };

})();

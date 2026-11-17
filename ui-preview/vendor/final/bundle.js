/* @ds-bundle: {"format":4,"namespace":"Final","components":[{"name":"World"},{"name":"Glass"},{"name":"Panel"},{"name":"FloatingLabel"},{"name":"Card"},{"name":"Icon"},{"name":"Sparkle"},{"name":"FileGlyph"},{"name":"Button"},{"name":"IconButton"},{"name":"Menu"},{"name":"NavRail"},{"name":"TreeNav"},{"name":"SearchBar"},{"name":"StageTrack"},{"name":"Chip"},{"name":"ChipGroup"},{"name":"Status"},{"name":"Fit"},{"name":"Progress"},{"name":"ListRow"},{"name":"Tile"},{"name":"EntryCard"},{"name":"Provenance"},{"name":"Citation"},{"name":"EvidenceLayer"},{"name":"RowActions"},{"name":"AdvisoryStrip"},{"name":"ConflictCard"},{"name":"TextField"},{"name":"StatusSelect"},{"name":"EmptyState"}]} */
/* Final — design system components. Expects window.React and window.ReactDOM (React 18). Source: components/src. Icon geometry from Lucide (ISC). */
(() => {
  var __create = Object.create;
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __getProtoOf = Object.getPrototypeOf;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __commonJS = (cb, mod) => function __require() {
    try {
      return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
    } catch (e) {
      throw mod = 0, e;
    }
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
    // If the importer is in node compatibility mode or this is not an ESM
    // file that has been converted to a CommonJS file using a Babel-
    // compatible transform (i.e. "__esModule" has not been set), then set
    // "default" to the CommonJS "module.exports" for node compatibility.
    isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
    mod
  ));

  // src/react-shim.js
  var require_react_shim = __commonJS({
    "src/react-shim.js"(exports, module) {
      module.exports = window.React;
    }
  });

  // src/actions.tsx
  var React3 = __toESM(require_react_shim());

  // src/foundations.tsx
  var React2 = __toESM(require_react_shim());

  // src/icons.ts
  var ICONS = {
    "alert-circle": [["circle", { "cx": "12", "cy": "12", "r": "10" }], ["line", { "x1": "12", "x2": "12", "y1": "8", "y2": "12" }], ["line", { "x1": "12", "x2": "12.01", "y1": "16", "y2": "16" }]],
    "alert-triangle": [["path", { "d": "m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3" }], ["path", { "d": "M12 9v4" }], ["path", { "d": "M12 17h.01" }]],
    "arrow-right": [["path", { "d": "M5 12h14" }], ["path", { "d": "m12 5 7 7-7 7" }]],
    "arrow-up-right": [["path", { "d": "M7 7h10v10" }], ["path", { "d": "M7 17 17 7" }]],
    "bell": [["path", { "d": "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" }], ["path", { "d": "M10.3 21a1.94 1.94 0 0 0 3.4 0" }]],
    "book-open": [["path", { "d": "M12 7v14" }], ["path", { "d": "M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z" }]],
    "briefcase": [["path", { "d": "M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" }], ["rect", { "width": "20", "height": "14", "x": "2", "y": "6", "rx": "2" }]],
    "building": [["path", { "d": "M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z" }], ["path", { "d": "M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2" }], ["path", { "d": "M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2" }], ["path", { "d": "M10 6h4" }], ["path", { "d": "M10 10h4" }], ["path", { "d": "M10 14h4" }], ["path", { "d": "M10 18h4" }]],
    "calendar": [["path", { "d": "M8 2v4" }], ["path", { "d": "M16 2v4" }], ["rect", { "width": "18", "height": "18", "x": "3", "y": "4", "rx": "2" }], ["path", { "d": "M3 10h18" }]],
    "check": [["path", { "d": "M20 6 9 17l-5-5" }]],
    "check-circle": [["circle", { "cx": "12", "cy": "12", "r": "10" }], ["path", { "d": "m9 12 2 2 4-4" }]],
    "chevron-down": [["path", { "d": "m6 9 6 6 6-6" }]],
    "chevron-left": [["path", { "d": "m15 18-6-6 6-6" }]],
    "chevron-right": [["path", { "d": "m9 18 6-6-6-6" }]],
    "circle-dashed": [["path", { "d": "M10.1 2.182a10 10 0 0 1 3.8 0" }], ["path", { "d": "M13.9 21.818a10 10 0 0 1-3.8 0" }], ["path", { "d": "M17.609 3.721a10 10 0 0 1 2.69 2.7" }], ["path", { "d": "M2.182 13.9a10 10 0 0 1 0-3.8" }], ["path", { "d": "M20.279 17.609a10 10 0 0 1-2.7 2.69" }], ["path", { "d": "M21.818 10.1a10 10 0 0 1 0 3.8" }], ["path", { "d": "M3.721 6.391a10 10 0 0 1 2.7-2.69" }], ["path", { "d": "M6.391 20.279a10 10 0 0 1-2.69-2.7" }]],
    "clock": [["circle", { "cx": "12", "cy": "12", "r": "10" }], ["polyline", { "points": "12 6 12 12 16 14" }]],
    "command": [["path", { "d": "M15 6v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3" }]],
    "compare": [["circle", { "cx": "5", "cy": "6", "r": "3" }], ["path", { "d": "M12 6h5a2 2 0 0 1 2 2v7" }], ["path", { "d": "m15 9-3-3 3-3" }], ["circle", { "cx": "19", "cy": "18", "r": "3" }], ["path", { "d": "M12 18H7a2 2 0 0 1-2-2V9" }], ["path", { "d": "m9 15 3 3-3 3" }]],
    "copy": [["rect", { "width": "14", "height": "14", "x": "8", "y": "8", "rx": "2", "ry": "2" }], ["path", { "d": "M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" }]],
    "download": [["path", { "d": "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }], ["polyline", { "points": "7 10 12 15 17 10" }], ["line", { "x1": "12", "x2": "12", "y1": "15", "y2": "3" }]],
    "external-link": [["path", { "d": "M15 3h6v6" }], ["path", { "d": "M10 14 21 3" }], ["path", { "d": "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" }]],
    "eye": [["path", { "d": "M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0" }], ["circle", { "cx": "12", "cy": "12", "r": "3" }]],
    "file-text": [["path", { "d": "M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" }], ["path", { "d": "M14 2v4a2 2 0 0 0 2 2h4" }], ["path", { "d": "M10 9H8" }], ["path", { "d": "M16 13H8" }], ["path", { "d": "M16 17H8" }]],
    "filter": [["polygon", { "points": "22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" }]],
    "folder": [["path", { "d": "M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" }]],
    "globe": [["circle", { "cx": "12", "cy": "12", "r": "10" }], ["path", { "d": "M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" }], ["path", { "d": "M2 12h20" }]],
    "grid": [["rect", { "width": "7", "height": "7", "x": "3", "y": "3", "rx": "1" }], ["rect", { "width": "7", "height": "7", "x": "14", "y": "3", "rx": "1" }], ["rect", { "width": "7", "height": "7", "x": "14", "y": "14", "rx": "1" }], ["rect", { "width": "7", "height": "7", "x": "3", "y": "14", "rx": "1" }]],
    "history": [["path", { "d": "M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" }], ["path", { "d": "M3 3v5h5" }], ["path", { "d": "M12 7v5l4 2" }]],
    "home": [["path", { "d": "M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8" }], ["path", { "d": "M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" }]],
    "inbox": [["polyline", { "points": "22 12 16 12 14 15 10 15 8 12 2 12" }], ["path", { "d": "M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" }]],
    "info": [["circle", { "cx": "12", "cy": "12", "r": "10" }], ["path", { "d": "M12 16v-4" }], ["path", { "d": "M12 8h.01" }]],
    "layers": [["path", { "d": "m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z" }], ["path", { "d": "m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65" }], ["path", { "d": "m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65" }]],
    "library": [["path", { "d": "m16 6 4 14" }], ["path", { "d": "M12 6v14" }], ["path", { "d": "M8 8v12" }], ["path", { "d": "M4 4v16" }]],
    "link": [["path", { "d": "M9 17H7A5 5 0 0 1 7 7h2" }], ["path", { "d": "M15 7h2a5 5 0 1 1 0 10h-2" }], ["line", { "x1": "8", "x2": "16", "y1": "12", "y2": "12" }]],
    "list-checks": [["path", { "d": "m3 17 2 2 4-4" }], ["path", { "d": "m3 7 2 2 4-4" }], ["path", { "d": "M13 6h8" }], ["path", { "d": "M13 12h8" }], ["path", { "d": "M13 18h8" }]],
    "message": [["path", { "d": "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" }], ["path", { "d": "M13 8H7" }], ["path", { "d": "M17 12H7" }]],
    "minus": [["path", { "d": "M5 12h14" }]],
    "minus-circle": [["circle", { "cx": "12", "cy": "12", "r": "10" }], ["path", { "d": "M8 12h8" }]],
    "more": [["circle", { "cx": "12", "cy": "12", "r": "1" }], ["circle", { "cx": "19", "cy": "12", "r": "1" }], ["circle", { "cx": "5", "cy": "12", "r": "1" }]],
    "more-vertical": [["circle", { "cx": "12", "cy": "12", "r": "1" }], ["circle", { "cx": "12", "cy": "5", "r": "1" }], ["circle", { "cx": "12", "cy": "19", "r": "1" }]],
    "panel-left": [["rect", { "width": "18", "height": "18", "x": "3", "y": "3", "rx": "2" }], ["path", { "d": "M9 3v18" }]],
    "pen-line": [["path", { "d": "M12 20h9" }], ["path", { "d": "M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z" }]],
    "pencil": [["path", { "d": "M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z" }], ["path", { "d": "m15 5 4 4" }]],
    "play": [["polygon", { "points": "6 3 20 12 6 21 6 3" }]],
    "plus": [["path", { "d": "M5 12h14" }], ["path", { "d": "M12 5v14" }]],
    "presentation": [["path", { "d": "M2 3h20" }], ["path", { "d": "M21 3v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V3" }], ["path", { "d": "m7 21 5-5 5 5" }]],
    "quote": [["path", { "d": "M16 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z" }], ["path", { "d": "M5 3a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2 1 1 0 0 1 1 1v1a2 2 0 0 1-2 2 1 1 0 0 0-1 1v2a1 1 0 0 0 1 1 6 6 0 0 0 6-6V5a2 2 0 0 0-2-2z" }]],
    "radar": [["path", { "d": "M19.07 4.93A10 10 0 0 0 6.99 3.34" }], ["path", { "d": "M4 6h.01" }], ["path", { "d": "M2.29 9.62A10 10 0 1 0 21.31 8.35" }], ["path", { "d": "M16.24 7.76A6 6 0 1 0 8.23 16.67" }], ["path", { "d": "M12 18h.01" }], ["path", { "d": "M17.99 11.66A6 6 0 0 1 15.77 16.67" }], ["circle", { "cx": "12", "cy": "12", "r": "2" }], ["path", { "d": "m13.41 10.59 5.66-5.66" }]],
    "refresh": [["path", { "d": "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" }], ["path", { "d": "M21 3v5h-5" }], ["path", { "d": "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" }], ["path", { "d": "M8 16H3v5" }]],
    "scale": [["path", { "d": "m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z" }], ["path", { "d": "m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z" }], ["path", { "d": "M7 21h10" }], ["path", { "d": "M12 3v18" }], ["path", { "d": "M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2" }]],
    "search": [["circle", { "cx": "11", "cy": "11", "r": "8" }], ["path", { "d": "m21 21-4.3-4.3" }]],
    "send": [["path", { "d": "M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z" }], ["path", { "d": "m21.854 2.147-10.94 10.939" }]],
    "share": [["path", { "d": "M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" }], ["polyline", { "points": "16 6 12 2 8 6" }], ["line", { "x1": "12", "x2": "12", "y1": "2", "y2": "15" }]],
    "sliders": [["line", { "x1": "21", "x2": "14", "y1": "4", "y2": "4" }], ["line", { "x1": "10", "x2": "3", "y1": "4", "y2": "4" }], ["line", { "x1": "21", "x2": "12", "y1": "12", "y2": "12" }], ["line", { "x1": "8", "x2": "3", "y1": "12", "y2": "12" }], ["line", { "x1": "21", "x2": "16", "y1": "20", "y2": "20" }], ["line", { "x1": "12", "x2": "3", "y1": "20", "y2": "20" }], ["line", { "x1": "14", "x2": "14", "y1": "2", "y2": "6" }], ["line", { "x1": "8", "x2": "8", "y1": "10", "y2": "14" }], ["line", { "x1": "16", "x2": "16", "y1": "18", "y2": "22" }]],
    "trash": [["path", { "d": "M3 6h18" }], ["path", { "d": "M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" }], ["path", { "d": "M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" }], ["line", { "x1": "10", "x2": "10", "y1": "11", "y2": "17" }], ["line", { "x1": "14", "x2": "14", "y1": "11", "y2": "17" }]],
    "undo": [["path", { "d": "M9 14 4 9l5-5" }], ["path", { "d": "M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a5.5 5.5 0 0 1-5.5 5.5H11" }]],
    "upload": [["path", { "d": "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" }], ["polyline", { "points": "17 8 12 3 7 8" }], ["line", { "x1": "12", "x2": "12", "y1": "3", "y2": "15" }]],
    "user": [["circle", { "cx": "12", "cy": "8", "r": "5" }], ["path", { "d": "M20 21a8 8 0 0 0-16 0" }]],
    "users": [["path", { "d": "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" }], ["circle", { "cx": "9", "cy": "7", "r": "4" }], ["path", { "d": "M22 21v-2a4 4 0 0 0-3-3.87" }], ["path", { "d": "M16 3.13a4 4 0 0 1 0 7.75" }]],
    "x": [["path", { "d": "M18 6 6 18" }], ["path", { "d": "m6 6 12 12" }]],
    "x-circle": [["circle", { "cx": "12", "cy": "12", "r": "10" }], ["path", { "d": "m15 9-6 6" }], ["path", { "d": "m9 9 6 6" }]]
  };

  // src/util.ts
  var React = __toESM(require_react_shim());
  var WORLDS = ["peach", "ice", "sage", "mist", "blush", "stone"];
  function cx(...parts) {
    return parts.filter(Boolean).join(" ");
  }
  var seq = 0;
  function useStableId(prefix, given) {
    const reactId = React.useId ? React.useId() : null;
    const ref = React.useRef();
    if (!ref.current) ref.current = given || `${prefix}-${reactId ? String(reactId).replace(/:/g, "") : ++seq}`;
    return given || ref.current;
  }
  var UNITS = [
    ["year", 31536e3],
    ["month", 2592e3],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60]
  ];
  function relativeTime(when, now = /* @__PURE__ */ new Date(), locale) {
    const d = when instanceof Date ? when : new Date(when);
    const diff = (d.getTime() - now.getTime()) / 1e3;
    const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
    for (const [unit, secs] of UNITS) {
      if (Math.abs(diff) >= secs) return rtf.format(Math.round(diff / secs), unit);
    }
    return rtf.format(0, "minute");
  }
  function formatDate(when, locale, opts) {
    const d = when instanceof Date ? when : new Date(when);
    return new Intl.DateTimeFormat(locale, opts || { day: "numeric", month: "short" }).format(d);
  }
  function formatCount(n, locale) {
    return new Intl.NumberFormat(locale).format(n);
  }
  function useDismiss(open, close, refs, returnFocus) {
    React.useEffect(() => {
      if (!open) return;
      const onKey = (e) => {
        var _a;
        if (e.key === "Escape") {
          e.stopPropagation();
          close();
          (_a = returnFocus == null ? void 0 : returnFocus.current) == null ? void 0 : _a.focus();
        }
      };
      const onDown = (e) => {
        const t = e.target;
        if (refs.every((r) => !r.current || !r.current.contains(t))) close();
      };
      document.addEventListener("keydown", onKey, true);
      document.addEventListener("pointerdown", onDown, true);
      return () => {
        document.removeEventListener("keydown", onKey, true);
        document.removeEventListener("pointerdown", onDown, true);
      };
    }, [open]);
  }

  // src/foundations.tsx
  function Icon({ name, size = 20, strokeWidth = 1.75, title, className, ...rest }) {
    const els = ICONS[name];
    if (!els) return null;
    return /* @__PURE__ */ React2.createElement(
      "svg",
      {
        viewBox: "0 0 24 24",
        width: size,
        height: size,
        fill: "none",
        stroke: "currentColor",
        strokeWidth,
        strokeLinecap: "round",
        strokeLinejoin: "round",
        "aria-hidden": title ? void 0 : true,
        role: title ? "img" : void 0,
        focusable: "false",
        className: cx("fn-icon", className),
        ...rest
      },
      title ? /* @__PURE__ */ React2.createElement("title", null, title) : null,
      els.map(([tag, attrs], i) => React2.createElement(tag, { key: i, ...attrs }))
    );
  }
  var SPARK_PATH = "M12 1.6c.9 5.7 3.8 9 9.4 10.4-5.6 1.4-8.5 4.7-9.4 10.4-.9-5.7-3.8-9-9.4-10.4C8.2 10.6 11.1 7.3 12 1.6Z";
  function Sparkle({ size = 14, label, title = "Made by AI", className }) {
    const mark = /* @__PURE__ */ React2.createElement(
      "svg",
      {
        viewBox: "0 0 24 24",
        width: size,
        height: size,
        className: "fn-sparkle-mark",
        role: label ? void 0 : "img",
        "aria-hidden": label ? true : void 0,
        "aria-label": label ? void 0 : title,
        focusable: "false"
      },
      /* @__PURE__ */ React2.createElement("path", { d: SPARK_PATH })
    );
    if (!label) return /* @__PURE__ */ React2.createElement("span", { className: cx("fn-sparkle", className) }, mark);
    return /* @__PURE__ */ React2.createElement("span", { className: cx("fn-sparkle", "fn-sparkle--label", className) }, mark, /* @__PURE__ */ React2.createElement("span", null, label));
  }
  var FILE_LABEL = { pdf: "PDF", docx: "DOC", pptx: "PPT", xlsx: "XLS", csv: "CSV", txt: "TXT", zip: "ZIP", url: "WEB" };
  function FileGlyph({ type, size = 28, title, className }) {
    const t = FILE_LABEL[type] ? type : "txt";
    return /* @__PURE__ */ React2.createElement(
      "svg",
      {
        viewBox: "0 0 28 32",
        width: size * (28 / 32),
        height: size,
        className: cx("fn-file", `fn-file--${t}`, className),
        role: title ? "img" : void 0,
        "aria-label": title,
        "aria-hidden": title ? void 0 : true,
        focusable: "false"
      },
      /* @__PURE__ */ React2.createElement("path", { className: "fn-file-body", d: "M6 1h11.2c.8 0 1.6.3 2.1.9l6.8 6.8c.6.6.9 1.3.9 2.1V26a5 5 0 0 1-5 5H6a5 5 0 0 1-5-5V6a5 5 0 0 1 5-5Z" }),
      /* @__PURE__ */ React2.createElement("path", { className: "fn-file-fold", d: "M17.5 1.4v5.1a3 3 0 0 0 3 3h5.1" }),
      size >= 22 ? /* @__PURE__ */ React2.createElement("text", { className: "fn-file-text", x: "14", y: "24.5", textAnchor: "middle" }, FILE_LABEL[t]) : null
    );
  }
  var WORLD_SHAPES = {
    peach: [
      { kind: "bubble", x: 90, y: 16, size: 30, depth: 0.12 },
      { kind: "capsule", x: 8, y: 92, size: 38, rotate: -24, depth: 0.32 },
      { kind: "bubble", x: 36, y: 2, size: 9, depth: 0.85 }
    ],
    ice: [
      { kind: "cube", x: 91, y: 14, size: 24, rotate: 10, depth: 0.12 },
      { kind: "bubble", x: 4, y: 94, size: 30, depth: 0.32 },
      { kind: "capsule", x: 78, y: 100, size: 26, rotate: 24, depth: 0.85 }
    ],
    sage: [
      { kind: "bookmark", x: 93, y: 22, size: 15, rotate: 14, depth: 0.12 },
      { kind: "ribbon", x: 10, y: 90, size: 38, rotate: -8, depth: 0.32 },
      { kind: "bubble", x: 3, y: 6, size: 12, depth: 0.85 }
    ],
    mist: [
      { kind: "ribbon", x: 88, y: 8, size: 38, rotate: 8, depth: 0.12 },
      { kind: "bubble", x: 2, y: 74, size: 24, depth: 0.32 },
      { kind: "cube", x: 96, y: 94, size: 17, rotate: -12, depth: 0.85 }
    ],
    blush: [
      { kind: "bubble", x: 93, y: 92, size: 30, depth: 0.12 },
      { kind: "bookmark", x: 5, y: 8, size: 14, rotate: -18, depth: 0.32 },
      { kind: "capsule", x: 72, y: 0, size: 24, rotate: -28, depth: 0.85 }
    ],
    stone: [
      { kind: "cube", x: 7, y: 90, size: 24, rotate: -8, depth: 0.12 },
      { kind: "capsule", x: 90, y: 10, size: 34, rotate: -20, depth: 0.32 },
      { kind: "bubble", x: 98, y: 70, size: 11, depth: 0.85 }
    ]
  };
  function Shape({ spec, uid }) {
    var _a;
    const id = `${uid}-${spec.kind}-${Math.round(spec.x)}-${Math.round(spec.y)}`;
    const g = "var(--w-glow)";
    const f = "var(--w-field)";
    const d = "var(--w-deep)";
    const stop = (offset, color, opacity = 1) => /* @__PURE__ */ React2.createElement("stop", { offset, style: { stopColor: color, stopOpacity: opacity } });
    let vb = "0 0 200 200";
    let body = null;
    switch (spec.kind) {
      case "bubble":
        body = /* @__PURE__ */ React2.createElement(React2.Fragment, null, /* @__PURE__ */ React2.createElement("defs", null, /* @__PURE__ */ React2.createElement("radialGradient", { id, cx: "32%", cy: "26%", r: "82%" }, stop(0, g), stop(0.3, f), stop(0.8, d), stop(1, d)), /* @__PURE__ */ React2.createElement("radialGradient", { id: `${id}-b`, cx: "74%", cy: "84%", r: "40%" }, stop(0, g, 0.55), stop(1, g, 0))), /* @__PURE__ */ React2.createElement("circle", { cx: "100", cy: "100", r: "96", fill: `url(#${id})` }), /* @__PURE__ */ React2.createElement("circle", { cx: "100", cy: "100", r: "96", fill: `url(#${id}-b)` }));
        break;
      case "capsule":
        vb = "0 0 240 100";
        body = /* @__PURE__ */ React2.createElement(React2.Fragment, null, /* @__PURE__ */ React2.createElement("defs", null, /* @__PURE__ */ React2.createElement("linearGradient", { id, x1: "0", y1: "0", x2: "0.15", y2: "1" }, stop(0, g), stop(0.35, f), stop(0.85, d), stop(1, d))), /* @__PURE__ */ React2.createElement("rect", { x: "2", y: "2", width: "236", height: "96", rx: "48", fill: `url(#${id})` }));
        break;
      case "cube":
        vb = "0 0 200 220";
        body = /* @__PURE__ */ React2.createElement(React2.Fragment, null, /* @__PURE__ */ React2.createElement("defs", null, /* @__PURE__ */ React2.createElement("linearGradient", { id, x1: "0", y1: "0", x2: "0", y2: "1" }, stop(0, g), stop(1, f)), /* @__PURE__ */ React2.createElement("linearGradient", { id: `${id}-l`, x1: "0", y1: "0", x2: "0", y2: "1" }, stop(0, f), stop(1, d))), /* @__PURE__ */ React2.createElement("g", { strokeLinejoin: "round", strokeWidth: "18" }, /* @__PURE__ */ React2.createElement("path", { d: "M18 62 100 106v96L18 158Z", fill: `url(#${id}-l)`, stroke: `url(#${id}-l)` }), /* @__PURE__ */ React2.createElement("path", { d: "M182 62 100 106v96l82-44Z", style: { fill: d, stroke: d } }), /* @__PURE__ */ React2.createElement("path", { d: "M100 18 182 62 100 106 18 62Z", fill: `url(#${id})`, stroke: `url(#${id})` })));
        break;
      case "ribbon":
        vb = "0 0 240 160";
        body = /* @__PURE__ */ React2.createElement(React2.Fragment, null, /* @__PURE__ */ React2.createElement("defs", null, /* @__PURE__ */ React2.createElement("linearGradient", { id, x1: "0", y1: "0", x2: "1", y2: "0.6" }, stop(0, g), stop(0.5, f), stop(1, d))), /* @__PURE__ */ React2.createElement("path", { d: "M28 118c34-86 92-96 120-46s56 52 64-30", fill: "none", strokeWidth: "44", strokeLinecap: "round", style: { stroke: d }, transform: "translate(2 12)" }), /* @__PURE__ */ React2.createElement("path", { d: "M28 118c34-86 92-96 120-46s56 52 64-30", fill: "none", strokeWidth: "44", strokeLinecap: "round", stroke: `url(#${id})` }));
        break;
      case "bookmark":
        vb = "0 0 120 180";
        body = /* @__PURE__ */ React2.createElement(React2.Fragment, null, /* @__PURE__ */ React2.createElement("defs", null, /* @__PURE__ */ React2.createElement("linearGradient", { id, x1: "0", y1: "0", x2: "1", y2: "0.2" }, stop(0, g), stop(0.4, f), stop(1, d))), /* @__PURE__ */ React2.createElement("path", { d: "M22 4h76a18 18 0 0 1 18 18v148c0 7-8 10-13 6l-43-31-43 31c-5 4-13 1-13-6V22A18 18 0 0 1 22 4Z", fill: `url(#${id})` }));
        break;
    }
    const [, , w2, h] = vb.split(" ").map(Number);
    const style = {
      left: `${spec.x}%`,
      top: `${spec.y}%`,
      width: `${spec.size}%`,
      aspectRatio: `${w2} / ${h}`,
      transform: `translate(-50%, -50%) rotate(${spec.rotate || 0}deg)`,
      ["--depth"]: (_a = spec.depth) != null ? _a : 0.4
    };
    return /* @__PURE__ */ React2.createElement("svg", { className: "fn-world-shape", viewBox: vb, style, preserveAspectRatio: "xMidYMid meet", focusable: "false" }, body);
  }
  function WorldLayer({ world, mode, shapes, entering, onEntered }) {
    const uid = useStableId("fn-w");
    const list = Array.isArray(shapes) ? shapes : shapes && mode === "atmosphere" ? WORLD_SHAPES[world] || [] : [];
    return /* @__PURE__ */ React2.createElement("div", { className: cx("fn-world-layer", entering && "is-entering"), "data-world": world, "aria-hidden": "true", onAnimationEnd: entering ? onEntered : void 0 }, /* @__PURE__ */ React2.createElement("div", { className: "fn-world-field" }), list.map((s, i) => /* @__PURE__ */ React2.createElement(Shape, { key: i, spec: s, uid })));
  }
  function World({ world = "peach", mode = "atmosphere", shapes = true, as: Tag = "div", className, children, ...rest }) {
    const [layers, setLayers] = React2.useState([{ world, key: 0 }]);
    React2.useEffect(() => {
      setLayers((ls) => ls[ls.length - 1].world === world ? ls : [ls[ls.length - 1], { world, key: ls[ls.length - 1].key + 1 }]);
    }, [world]);
    const El = Tag;
    return /* @__PURE__ */ React2.createElement(El, { className: cx("fn-world", className), "data-world": world, "data-mode": mode, ...rest }, layers.map((l, i) => /* @__PURE__ */ React2.createElement(
      WorldLayer,
      {
        key: l.key,
        world: l.world,
        mode,
        shapes,
        entering: layers.length > 1 && i === layers.length - 1,
        onEntered: () => setLayers((ls) => ls.slice(-1))
      }
    )), /* @__PURE__ */ React2.createElement("div", { className: "fn-world-content" }, children));
  }
  function Glass({ as: Tag = "div", strong, radius = "xl", className, children, ...rest }) {
    const El = Tag;
    return /* @__PURE__ */ React2.createElement(El, { className: cx("fn-glass", strong && "fn-glass--strong", `fn-r-${radius}`, className), ...rest }, children);
  }
  function Card({ as: Tag = "div", density = "airy", elevated, className, children, ...rest }) {
    const El = Tag;
    return /* @__PURE__ */ React2.createElement(El, { className: cx("fn-card", `fn-card--${density}`, elevated && "fn-card--elevated", className), ...rest }, children);
  }
  function FloatingLabel({ icon, children, as: Tag = "h2", attached = true, id, className }) {
    return /* @__PURE__ */ React2.createElement(Tag, { id, className: cx("fn-flabel", attached && "fn-flabel--attached", className) }, icon ? /* @__PURE__ */ React2.createElement(Icon, { name: icon, size: 18, className: "fn-flabel-icon" }) : /* @__PURE__ */ React2.createElement("span", { className: "fn-flabel-dot", "aria-hidden": "true" }), /* @__PURE__ */ React2.createElement("span", { className: "fn-flabel-text" }, children));
  }
  function Panel({ label, icon, world, labelAs = "h2", className, children, ...rest }) {
    const labelId = useStableId("fn-panel");
    return /* @__PURE__ */ React2.createElement(
      "section",
      {
        className: cx("fn-glass", "fn-r-xl", "fn-panel", label != null && "fn-panel--labelled", className),
        "data-world": world,
        "aria-labelledby": label != null ? labelId : void 0,
        ...rest
      },
      label != null ? /* @__PURE__ */ React2.createElement(FloatingLabel, { icon, as: labelAs, id: labelId }, label) : null,
      children
    );
  }

  // src/actions.tsx
  function Spinner({ size = 16 }) {
    return /* @__PURE__ */ React3.createElement("svg", { className: "fn-spinner", viewBox: "0 0 24 24", width: size, height: size, "aria-hidden": "true", focusable: "false" }, /* @__PURE__ */ React3.createElement("circle", { cx: "12", cy: "12", r: "9", fill: "none", strokeWidth: "2.5" }));
  }
  var Button = React3.forwardRef(function Button2({ variant = "secondary", size = "md", icon, iconEnd, loading, disabled, disabledReason, className, children, type = "button", onClick, ...rest }, ref) {
    const reasonId = useStableId("fn-why");
    const blocked = !!disabledReason || !!disabled;
    const iconSize = size === "sm" ? 16 : 18;
    const btn = /* @__PURE__ */ React3.createElement(
      "button",
      {
        ref,
        type,
        className: cx("fn-btn", `fn-btn--${variant}`, `fn-btn--${size}`, blocked && "is-disabled", loading && "is-loading", className),
        disabled: disabled && !disabledReason,
        "aria-disabled": disabledReason ? true : void 0,
        "aria-describedby": disabledReason ? reasonId : void 0,
        "aria-busy": loading || void 0,
        onClick: blocked || loading ? (e) => e.preventDefault() : onClick,
        ...rest
      },
      loading ? /* @__PURE__ */ React3.createElement(Spinner, { size: iconSize }) : icon ? /* @__PURE__ */ React3.createElement(Icon, { name: icon, size: iconSize }) : null,
      /* @__PURE__ */ React3.createElement("span", { className: "fn-btn-label" }, children),
      iconEnd && !loading ? /* @__PURE__ */ React3.createElement(Icon, { name: iconEnd, size: iconSize }) : null
    );
    if (!disabledReason) return btn;
    return /* @__PURE__ */ React3.createElement("span", { className: "fn-btn-wrap" }, btn, /* @__PURE__ */ React3.createElement("span", { id: reasonId, className: "fn-btn-reason" }, disabledReason));
  });
  var IconButton = React3.forwardRef(function IconButton2({ icon, label, variant = "outline", size = "md", badge, badgeLabel = (n) => `${n} new`, pressed, className, type = "button", ...rest }, ref) {
    const has = typeof badge === "number" && badge > 0;
    const name = has ? `${label}, ${badgeLabel(badge)}` : label;
    return /* @__PURE__ */ React3.createElement(
      "button",
      {
        ref,
        type,
        className: cx("fn-ibtn", `fn-ibtn--${variant}`, `fn-ibtn--${size}`, className),
        "aria-label": name,
        title: label,
        "aria-pressed": pressed,
        ...rest
      },
      /* @__PURE__ */ React3.createElement(Icon, { name: icon, size: size === "sm" ? 16 : 20 }),
      has ? /* @__PURE__ */ React3.createElement("span", { className: "fn-badge", "aria-hidden": "true" }, badge > 99 ? "99+" : badge) : null
    );
  });
  function Menu({ label, items, icon = "more", align = "end", defaultOpen = false, triggerVariant = "ghost" }) {
    const [open, setOpen] = React3.useState(defaultOpen);
    const trigger = React3.useRef(null);
    const panel = React3.useRef(null);
    const menuId = useStableId("fn-menu");
    const userOpened = React3.useRef(false);
    useDismiss(open, () => setOpen(false), [trigger, panel], trigger);
    const focusItem = (dir) => {
      var _a;
      const els = Array.from(((_a = panel.current) == null ? void 0 : _a.querySelectorAll('[role="menuitem"]:not([disabled])')) || []);
      if (!els.length) return;
      const i = els.indexOf(document.activeElement);
      const next = dir === "first" ? 0 : dir === "last" ? els.length - 1 : (i + dir + els.length) % els.length;
      els[next].focus();
    };
    React3.useEffect(() => {
      if (open && userOpened.current) focusItem("first");
    }, [open]);
    const onKey = (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        focusItem(1);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        focusItem(-1);
      } else if (e.key === "Home") {
        e.preventDefault();
        focusItem("first");
      } else if (e.key === "End") {
        e.preventDefault();
        focusItem("last");
      } else if (e.key === "Tab") setOpen(false);
    };
    return /* @__PURE__ */ React3.createElement("div", { className: "fn-menu-wrap" }, /* @__PURE__ */ React3.createElement(
      IconButton,
      {
        ref: trigger,
        icon,
        label,
        variant: triggerVariant,
        "aria-haspopup": "menu",
        "aria-expanded": open,
        "aria-controls": open ? menuId : void 0,
        onClick: () => {
          userOpened.current = true;
          setOpen((o) => !o);
        },
        onKeyDown: (e) => {
          if (e.key === "ArrowDown" && !open) {
            e.preventDefault();
            userOpened.current = true;
            setOpen(true);
          }
        }
      }
    ), open ? /* @__PURE__ */ React3.createElement("div", { ref: panel, id: menuId, role: "menu", "aria-label": label, className: cx("fn-menu", "fn-glass", "fn-glass--strong", "fn-pop", `fn-menu--${align}`), onKeyDown: onKey }, items.map((it) => /* @__PURE__ */ React3.createElement(
      "button",
      {
        key: it.id,
        type: "button",
        role: "menuitem",
        className: cx("fn-menu-item", it.tone === "risk" && "fn-menu-item--risk"),
        disabled: it.disabled,
        onClick: () => {
          var _a, _b;
          setOpen(false);
          (_a = trigger.current) == null ? void 0 : _a.focus();
          (_b = it.onSelect) == null ? void 0 : _b.call(it);
        }
      },
      it.icon ? /* @__PURE__ */ React3.createElement(Icon, { name: it.icon, size: 18 }) : /* @__PURE__ */ React3.createElement("span", { className: "fn-menu-gap" }),
      /* @__PURE__ */ React3.createElement("span", { className: "fn-menu-label" }, it.label),
      it.shortcut ? /* @__PURE__ */ React3.createElement("kbd", { className: "fn-kbd" }, it.shortcut) : null
    ))) : null);
  }

  // src/content.tsx
  var React4 = __toESM(require_react_shim());
  function Chip({ tone = "neutral", icon, dot, onRemove, removeLabel, size = "md", className, children }) {
    const isWorld = WORLDS.includes(tone);
    return /* @__PURE__ */ React4.createElement("span", { className: cx("fn-chip", `fn-chip--${size}`, !isWorld && `fn-chip--${tone}`, className), "data-world": isWorld ? tone : void 0 }, tone === "ai" && !icon ? /* @__PURE__ */ React4.createElement(Sparkle, { size: 12 }) : null, icon ? /* @__PURE__ */ React4.createElement(Icon, { name: icon, size: 14, strokeWidth: 2 }) : null, dot ? /* @__PURE__ */ React4.createElement("span", { className: "fn-chip-dot", "aria-hidden": "true" }) : null, /* @__PURE__ */ React4.createElement("span", { className: "fn-chip-label" }, children), onRemove ? /* @__PURE__ */ React4.createElement("button", { type: "button", className: "fn-chip-x", "aria-label": removeLabel || `Remove ${typeof children === "string" ? children : "item"}`, onClick: onRemove }, /* @__PURE__ */ React4.createElement(Icon, { name: "x", size: 12, strokeWidth: 2.25 })) : null);
  }
  function ChipGroup({ title, count, defaultOpen = true, children }) {
    const [open, setOpen] = React4.useState(defaultOpen);
    const id = useStableId("fn-cg");
    return /* @__PURE__ */ React4.createElement("div", { className: "fn-chipgroup" }, /* @__PURE__ */ React4.createElement("button", { type: "button", className: "fn-chipgroup-head", "aria-expanded": open, "aria-controls": id, onClick: () => setOpen((o) => !o) }, /* @__PURE__ */ React4.createElement(Icon, { name: "chevron-right", size: 16, className: "fn-tree-chevron" }), /* @__PURE__ */ React4.createElement("span", { className: "fn-caption" }, title), typeof count === "number" ? /* @__PURE__ */ React4.createElement("span", { className: "fn-count" }, formatCount(count)) : null), /* @__PURE__ */ React4.createElement("div", { id, className: "fn-chipgroup-body", hidden: !open }, children));
  }
  var STATUS_ICON = { good: "check-circle", risk: "alert-triangle", stale: "circle-dashed" };
  function Status({ status, children, size = "md" }) {
    return /* @__PURE__ */ React4.createElement(Chip, { tone: status, icon: STATUS_ICON[status], size }, children);
  }
  var FIT_FILL = { strong: 3, partial: 2, gap: 0 };
  var FIT_WORD = { strong: "Strong fit", partial: "Partial fit", gap: "Gap" };
  function Fit({ level, children }) {
    const n = FIT_FILL[level];
    return /* @__PURE__ */ React4.createElement("span", { className: cx("fn-chip", "fn-chip--md", "fn-fit", `fn-fit--${level}`) }, /* @__PURE__ */ React4.createElement("span", { className: "fn-fit-meter", "aria-hidden": "true" }, [0, 1, 2].map((i) => /* @__PURE__ */ React4.createElement("i", { key: i, className: i < n ? "on" : void 0 }))), /* @__PURE__ */ React4.createElement("span", { className: "fn-chip-label" }, children != null ? children : FIT_WORD[level]));
  }
  function Progress({ value, label, tone = "link", className }) {
    const v = Math.max(0, Math.min(1, value));
    return /* @__PURE__ */ React4.createElement(
      "div",
      {
        className: cx("fn-progress", `fn-progress--${tone}`, className),
        role: "progressbar",
        "aria-label": label,
        "aria-valuemin": 0,
        "aria-valuemax": 100,
        "aria-valuenow": Math.round(v * 100)
      },
      /* @__PURE__ */ React4.createElement("span", { style: { transform: `scaleX(${v})` } })
    );
  }
  function ListRow({ title, subtitle, file, leading, trailing, progress, progressLabel = "Progress", active, href, onClick, variant = "raised", className }) {
    const TitleTag = href ? "a" : onClick ? "button" : "span";
    return /* @__PURE__ */ React4.createElement("div", { className: cx("fn-row", `fn-row--${variant}`, active && "is-active", (href || onClick) && "is-interactive", className) }, /* @__PURE__ */ React4.createElement("span", { className: "fn-row-marker", "aria-hidden": "true" }), file ? /* @__PURE__ */ React4.createElement(FileGlyph, { type: file, size: 30 }) : leading ? /* @__PURE__ */ React4.createElement("span", { className: "fn-row-lead" }, leading) : null, /* @__PURE__ */ React4.createElement("span", { className: "fn-row-text" }, /* @__PURE__ */ React4.createElement(TitleTag, { className: "fn-row-title", href, type: TitleTag === "button" ? "button" : void 0, onClick, "aria-current": active ? "true" : void 0 }, title), subtitle ? /* @__PURE__ */ React4.createElement("span", { className: "fn-row-sub" }, subtitle) : null, typeof progress === "number" ? /* @__PURE__ */ React4.createElement(Progress, { value: progress, label: progressLabel, className: "fn-row-progress" }) : null), trailing ? /* @__PURE__ */ React4.createElement("span", { className: "fn-row-trail" }, trailing) : null);
  }
  function Tile({ caption, logo, monogram, world = "stone", status, statusLabel, href, onClick }) {
    const Tag = href ? "a" : onClick ? "button" : "div";
    const letters = (monogram || caption.replace(/[^A-Za-z0-9 ]/g, "").split(" ").filter(Boolean).slice(0, 2).map((w2) => w2[0]).join("")).toUpperCase();
    return /* @__PURE__ */ React4.createElement(Tag, { className: cx("fn-tile", (href || onClick) && "is-interactive"), href, type: Tag === "button" ? "button" : void 0, onClick, "data-world": world }, status ? /* @__PURE__ */ React4.createElement(Icon, { name: STATUS_ICON[status], size: 14, strokeWidth: 2, className: `fn-tile-status fn-tone-${status}` }) : null, /* @__PURE__ */ React4.createElement("span", { className: "fn-tile-logo", "aria-hidden": "true" }, logo ? /* @__PURE__ */ React4.createElement("img", { src: logo, alt: "", width: 40, height: 40 }) : /* @__PURE__ */ React4.createElement("span", { className: "fn-tile-mono" }, letters)), /* @__PURE__ */ React4.createElement("span", { className: "fn-tile-caption" }, caption), status && statusLabel ? /* @__PURE__ */ React4.createElement("span", { className: "fn-sr" }, ", ", statusLabel) : null);
  }

  // src/evidence.tsx
  var React6 = __toESM(require_react_shim());

  // src/forms.tsx
  var React5 = __toESM(require_react_shim());
  function StatusSelect({ value, options, onChange, label, className, ...rest }) {
    const current = options.find((o) => o.value === value) || options[0];
    return /* @__PURE__ */ React5.createElement("span", { className: cx("fn-select", `fn-select--${(current == null ? void 0 : current.tone) || "neutral"}`, className) }, /* @__PURE__ */ React5.createElement("span", { className: "fn-select-dot", "aria-hidden": "true" }), /* @__PURE__ */ React5.createElement("select", { "aria-label": label, value, onChange: (e) => onChange == null ? void 0 : onChange(e.target.value), ...rest }, options.map((o) => /* @__PURE__ */ React5.createElement("option", { key: o.value, value: o.value }, o.label))), /* @__PURE__ */ React5.createElement(Icon, { name: "chevron-down", size: 14, strokeWidth: 2, className: "fn-select-chev" }));
  }
  function TextField(props) {
    const { label, hint, error, className, multiline, id: given, ...rest } = props;
    const id = useStableId("fn-field", given);
    const noteId = `${id}-note`;
    const describedBy = error || hint ? noteId : void 0;
    const common = {
      id,
      className: cx("fn-input", multiline && "fn-input--multi"),
      "aria-invalid": error ? true : void 0,
      "aria-describedby": describedBy,
      ...rest
    };
    return /* @__PURE__ */ React5.createElement("div", { className: cx("fn-field", error && "has-error", className) }, /* @__PURE__ */ React5.createElement("label", { htmlFor: id, className: "fn-field-label" }, label), multiline ? /* @__PURE__ */ React5.createElement("textarea", { rows: 4, ...common }) : /* @__PURE__ */ React5.createElement("input", { type: "text", ...common }), error ? /* @__PURE__ */ React5.createElement("p", { id: noteId, className: "fn-field-note fn-field-note--error", "aria-live": "polite" }, /* @__PURE__ */ React5.createElement(Icon, { name: "alert-circle", size: 14, strokeWidth: 2 }), /* @__PURE__ */ React5.createElement("span", null, error)) : hint ? /* @__PURE__ */ React5.createElement("p", { id: noteId, className: "fn-field-note" }, hint) : null);
  }

  // src/evidence.tsx
  var STRIP_ICON = { neutral: "info", good: "check-circle", risk: "alert-triangle", ai: "" };
  function AdvisoryStrip({ tone = "neutral", icon, children, attached, className }) {
    const ic = icon || STRIP_ICON[tone];
    return /* @__PURE__ */ React6.createElement("div", { className: cx("fn-strip", `fn-strip--${tone}`, attached && "fn-strip--attached", className) }, tone === "ai" && !icon ? /* @__PURE__ */ React6.createElement(Sparkle, { size: 13 }) : ic ? /* @__PURE__ */ React6.createElement(Icon, { name: ic, size: 15, strokeWidth: 2 }) : null, /* @__PURE__ */ React6.createElement("span", null, children));
  }
  var CONF_WORD = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" };
  var CONF_N = { high: 3, medium: 2, low: 1 };
  function Provenance({ author, verb, time, sources, confidence, conflicts, onSources, onConflicts, onImprove, improveLabel = "Improve", now, locale }) {
    const isAI = author.kind === "ai";
    const who = isAI ? "AI" : author.name || "a teammate";
    const v = verb || (isAI ? "Drafted" : "Edited");
    const t = time != null ? new Date(time) : null;
    return /* @__PURE__ */ React6.createElement("div", { className: "fn-prov" }, /* @__PURE__ */ React6.createElement("span", { className: "fn-prov-item fn-prov-who" }, isAI ? /* @__PURE__ */ React6.createElement(Sparkle, { size: 13 }) : /* @__PURE__ */ React6.createElement("span", { className: "fn-prov-avatar", "aria-hidden": "true" }, who.slice(0, 1)), /* @__PURE__ */ React6.createElement("span", null, v, " by ", /* @__PURE__ */ React6.createElement("b", { translate: isAI ? "no" : void 0 }, who), t ? /* @__PURE__ */ React6.createElement(React6.Fragment, null, " \xB7 ", /* @__PURE__ */ React6.createElement("time", { dateTime: t.toISOString(), title: formatDate(t, locale, { dateStyle: "medium", timeStyle: "short" }) }, relativeTime(t, now, locale))) : null)), typeof sources === "number" ? onSources ? /* @__PURE__ */ React6.createElement("button", { type: "button", className: "fn-prov-item fn-prov-link", onClick: onSources }, /* @__PURE__ */ React6.createElement(Icon, { name: "book-open", size: 14 }), formatCount(sources, locale), " ", sources === 1 ? "source" : "sources") : /* @__PURE__ */ React6.createElement("span", { className: "fn-prov-item" }, /* @__PURE__ */ React6.createElement(Icon, { name: "book-open", size: 14 }), formatCount(sources, locale), " ", sources === 1 ? "source" : "sources") : null, confidence ? /* @__PURE__ */ React6.createElement("span", { className: "fn-prov-item fn-prov-conf", "data-level": confidence }, /* @__PURE__ */ React6.createElement("span", { className: "fn-fit-meter", "aria-hidden": "true" }, [0, 1, 2].map((i) => /* @__PURE__ */ React6.createElement("i", { key: i, className: i < CONF_N[confidence] ? "on" : void 0 }))), CONF_WORD[confidence]) : null, conflicts ? /* @__PURE__ */ React6.createElement("button", { type: "button", className: "fn-prov-item fn-prov-risk", onClick: onConflicts, disabled: !onConflicts }, /* @__PURE__ */ React6.createElement(Icon, { name: "alert-triangle", size: 14, strokeWidth: 2 }), formatCount(conflicts, locale), " ", conflicts === 1 ? "conflict" : "conflicts") : null, onImprove ? /* @__PURE__ */ React6.createElement("button", { type: "button", className: "fn-prov-improve", onClick: onImprove }, /* @__PURE__ */ React6.createElement(Icon, { name: "pencil", size: 14 }), improveLabel) : null);
  }
  function highlightText(text, hl) {
    if (!hl) return text;
    const i = text.toLowerCase().indexOf(hl.toLowerCase());
    if (i < 0) return text;
    return /* @__PURE__ */ React6.createElement(React6.Fragment, null, text.slice(0, i), /* @__PURE__ */ React6.createElement("mark", null, text.slice(i, i + hl.length)), text.slice(i + hl.length));
  }
  function EvidenceLayer({ source, n, onClose, id, style, className, locale }) {
    const titleId = useStableId("fn-ev");
    return /* @__PURE__ */ React6.createElement("div", { id, role: "dialog", "aria-labelledby": titleId, className: cx("fn-evidence", "fn-glass", "fn-glass--strong", className), style }, /* @__PURE__ */ React6.createElement("div", { className: "fn-evidence-head" }, /* @__PURE__ */ React6.createElement(FileGlyph, { type: source.type || "pdf", size: 30 }), /* @__PURE__ */ React6.createElement("div", { className: "fn-evidence-titles" }, /* @__PURE__ */ React6.createElement("span", { className: "fn-evidence-kicker" }, n != null ? `Source ${n}` : "Source", source.location ? ` \xB7 ${source.location}` : ""), /* @__PURE__ */ React6.createElement("span", { id: titleId, className: "fn-evidence-title" }, source.title)), onClose ? /* @__PURE__ */ React6.createElement(IconButton, { icon: "x", label: "Close source", variant: "ghost", size: "sm", onClick: onClose }) : null), /* @__PURE__ */ React6.createElement("blockquote", { className: "fn-evidence-quote" }, highlightText(source.excerpt, source.highlight)), source.href || source.retrieved ? /* @__PURE__ */ React6.createElement("div", { className: "fn-evidence-foot" }, source.retrieved ? /* @__PURE__ */ React6.createElement("span", null, "Retrieved ", formatDate(source.retrieved, locale, { day: "numeric", month: "short", year: "numeric" })) : /* @__PURE__ */ React6.createElement("span", null), source.href ? /* @__PURE__ */ React6.createElement("a", { className: "fn-link", href: source.href, target: "_blank", rel: "noreferrer" }, "Open Source", /* @__PURE__ */ React6.createElement(Icon, { name: "arrow-up-right", size: 14, strokeWidth: 2 })) : null) : null);
  }
  function Citation({ n, source, defaultOpen = false }) {
    const [open, setOpen] = React6.useState(defaultOpen);
    const [pos, setPos] = React6.useState({});
    const btn = React6.useRef(null);
    const layer = React6.useRef(null);
    const layerId = useStableId("fn-cite");
    const userOpened = React6.useRef(false);
    useDismiss(open, () => setOpen(false), [btn, layer], btn);
    React6.useLayoutEffect(() => {
      var _a;
      if (!open || !btn.current) return;
      const place = () => {
        const r = btn.current.getBoundingClientRect();
        const w2 = Math.min(380, window.innerWidth - 16);
        const left = Math.max(8, Math.min(r.left + r.width / 2 - 40, window.innerWidth - w2 - 8));
        const below = window.innerHeight - r.bottom > 240 || r.top < 260;
        setPos(below ? { position: "fixed", top: r.bottom + 8, left, width: w2 } : { position: "fixed", bottom: window.innerHeight - r.top + 8, left, width: w2 });
      };
      place();
      if (userOpened.current) {
        const first = (_a = layer.current) == null ? void 0 : _a.querySelector("button, a[href]");
        first == null ? void 0 : first.focus({ preventScroll: true });
      }
      window.addEventListener("resize", place);
      window.addEventListener("scroll", place, true);
      return () => {
        window.removeEventListener("resize", place);
        window.removeEventListener("scroll", place, true);
      };
    }, [open]);
    return /* @__PURE__ */ React6.createElement("span", { className: "fn-cite-wrap" }, /* @__PURE__ */ React6.createElement(
      "button",
      {
        ref: btn,
        type: "button",
        className: cx("fn-cite", open && "is-open"),
        "aria-label": `Source ${n}: ${source.title}`,
        "aria-haspopup": "dialog",
        "aria-expanded": open,
        "aria-controls": open ? layerId : void 0,
        onClick: () => {
          userOpened.current = true;
          setOpen((o) => !o);
        }
      },
      n
    ), open ? portal(
      /* @__PURE__ */ React6.createElement("span", { ref: layer, className: "fn-cite-layer fn-pop", style: pos }, /* @__PURE__ */ React6.createElement(EvidenceLayer, { id: layerId, source, n, onClose: () => {
        var _a;
        setOpen(false);
        (_a = btn.current) == null ? void 0 : _a.focus();
      } }))
    ) : null);
  }
  function portal(node) {
    const RD = window.ReactDOM;
    return RD && RD.createPortal && typeof document !== "undefined" ? RD.createPortal(node, document.body) : node;
  }
  function RowActions({ actions, label = "Entry actions", pinned }) {
    return /* @__PURE__ */ React6.createElement("div", { role: "toolbar", "aria-label": label, "aria-orientation": "vertical", className: cx("fn-row-actions", pinned && "is-pinned") }, actions.map((a) => /* @__PURE__ */ React6.createElement(IconButton, { key: a.id, icon: a.icon, label: a.label, variant: "ghost", size: "sm", onClick: a.onClick })));
  }
  function EntryCard({ index, title, status, statusOptions, onStatusChange, advisory, provenance, actions, streaming, active, headingLevel = 3, children, id }) {
    const titleId = useStableId("fn-entry", id && `${id}-title`);
    const H = `h${headingLevel}`;
    return /* @__PURE__ */ React6.createElement("article", { id, className: cx("fn-entry", active && "is-active", actions && "fn-wakes"), "aria-labelledby": titleId }, /* @__PURE__ */ React6.createElement("div", { className: "fn-entry-card" }, advisory ? /* @__PURE__ */ React6.createElement(AdvisoryStrip, { tone: advisory.tone, icon: advisory.icon, attached: true }, advisory.text) : null, /* @__PURE__ */ React6.createElement("div", { className: "fn-entry-head" }, index ? /* @__PURE__ */ React6.createElement("span", { className: "fn-entry-index" }, index) : null, /* @__PURE__ */ React6.createElement(H, { id: titleId, className: "fn-entry-title" }, title), statusOptions && status != null ? /* @__PURE__ */ React6.createElement(StatusSelect, { value: status, options: statusOptions, onChange: onStatusChange, label: `Status${index ? ` of ${index}` : ""}` }) : null), /* @__PURE__ */ React6.createElement("div", { className: "fn-entry-body", "aria-busy": streaming || void 0 }, children), provenance ? /* @__PURE__ */ React6.createElement(Provenance, { ...provenance }) : null), actions ? /* @__PURE__ */ React6.createElement(RowActions, { actions, label: `Actions for ${index || "entry"}` }) : null);
  }
  function ConflictCard({ field, sides, resolved = null, onResolve }) {
    const titleId = useStableId("fn-conflict");
    return /* @__PURE__ */ React6.createElement("section", { className: cx("fn-conflict", resolved != null && "is-resolved"), "aria-labelledby": titleId }, /* @__PURE__ */ React6.createElement(AdvisoryStrip, { tone: resolved != null ? "good" : "risk", icon: resolved != null ? "check-circle" : "compare", attached: true }, /* @__PURE__ */ React6.createElement("span", { id: titleId }, resolved != null ? /* @__PURE__ */ React6.createElement(React6.Fragment, null, "Resolved \u2014 using ", sides[resolved].source, " for ", /* @__PURE__ */ React6.createElement("b", null, field)) : /* @__PURE__ */ React6.createElement(React6.Fragment, null, "Two sources disagree on ", /* @__PURE__ */ React6.createElement("b", null, field)))), /* @__PURE__ */ React6.createElement("div", { className: "fn-conflict-body" }, sides.map((s, i) => /* @__PURE__ */ React6.createElement("div", { key: i, className: cx("fn-conflict-side", resolved === i && "is-chosen", resolved != null && resolved !== i && "is-set-aside") }, /* @__PURE__ */ React6.createElement("div", { className: "fn-conflict-src" }, /* @__PURE__ */ React6.createElement(FileGlyph, { type: s.file || "pdf", size: 24 }), /* @__PURE__ */ React6.createElement("span", null, s.source)), /* @__PURE__ */ React6.createElement("p", { className: "fn-conflict-passage" }, s.passage), resolved == null ? /* @__PURE__ */ React6.createElement(Button, { size: "sm", variant: "secondary", icon: "check", onClick: () => onResolve == null ? void 0 : onResolve(i) }, s.useLabel || "Use This Value") : resolved === i ? /* @__PURE__ */ React6.createElement("span", { className: "fn-conflict-chosen" }, /* @__PURE__ */ React6.createElement(Icon, { name: "check-circle", size: 16, strokeWidth: 2 }), " In use") : null)), /* @__PURE__ */ React6.createElement("span", { className: "fn-conflict-vs", "aria-hidden": "true" }, /* @__PURE__ */ React6.createElement(Icon, { name: "compare", size: 16, strokeWidth: 2 }))));
  }

  // src/navigation.tsx
  var React7 = __toESM(require_react_shim());
  function RailButton({ it, active, onChange }) {
    const content = /* @__PURE__ */ React7.createElement(React7.Fragment, null, /* @__PURE__ */ React7.createElement(Icon, { name: it.icon, size: 22 }), it.badge ? /* @__PURE__ */ React7.createElement("span", { className: "fn-rail-dot", "aria-hidden": "true" }) : null, /* @__PURE__ */ React7.createElement("span", { className: "fn-sr" }, it.badge ? `${it.label}, ${it.badge} new` : it.label));
    const props = {
      className: cx("fn-rail-item", active && "is-active"),
      "aria-current": active ? "page" : void 0,
      title: it.label
    };
    return it.href ? /* @__PURE__ */ React7.createElement("a", { href: it.href, ...props, onClick: () => onChange == null ? void 0 : onChange(it.id) }, content) : /* @__PURE__ */ React7.createElement("button", { type: "button", ...props, onClick: () => onChange == null ? void 0 : onChange(it.id) }, content);
  }
  function NavRail({ items, value, onChange, label = "Main", footer }) {
    return /* @__PURE__ */ React7.createElement("nav", { className: "fn-rail", "aria-label": label }, /* @__PURE__ */ React7.createElement("ul", { className: "fn-rail-list" }, items.map((it) => /* @__PURE__ */ React7.createElement("li", { key: it.id }, /* @__PURE__ */ React7.createElement(RailButton, { it, active: it.id === value, onChange })))), footer && footer.length ? /* @__PURE__ */ React7.createElement("ul", { className: "fn-rail-list fn-rail-foot" }, footer.map((it) => /* @__PURE__ */ React7.createElement("li", { key: it.id }, /* @__PURE__ */ React7.createElement(RailButton, { it, active: it.id === value, onChange })))) : null);
  }
  function TreeRow({ it, depth, value, onChange }) {
    const active = it.id === value;
    const props = {
      className: cx("fn-tree-item", active && "is-active"),
      "aria-current": active ? "page" : void 0,
      style: { ["--depth"]: depth },
      onClick: () => onChange == null ? void 0 : onChange(it.id)
    };
    const inner = /* @__PURE__ */ React7.createElement(React7.Fragment, null, /* @__PURE__ */ React7.createElement("span", { className: "fn-tree-marker", "aria-hidden": "true" }), it.file ? /* @__PURE__ */ React7.createElement(FileGlyph, { type: it.file, size: 18 }) : it.icon ? /* @__PURE__ */ React7.createElement(Icon, { name: it.icon, size: 18, className: "fn-tree-icon" }) : null, /* @__PURE__ */ React7.createElement("span", { className: "fn-tree-label" }, it.label), typeof it.count === "number" ? /* @__PURE__ */ React7.createElement("span", { className: "fn-count" }, formatCount(it.count)) : null);
    return /* @__PURE__ */ React7.createElement("li", null, it.href ? /* @__PURE__ */ React7.createElement("a", { href: it.href, ...props }, inner) : /* @__PURE__ */ React7.createElement("button", { type: "button", ...props }, inner), it.items && it.items.length ? /* @__PURE__ */ React7.createElement("ul", { className: "fn-tree-list fn-tree-list--nested" }, it.items.map((c) => /* @__PURE__ */ React7.createElement(TreeRow, { key: c.id, it: c, depth: depth + 1, value, onChange }))) : null);
  }
  function TreeSectionView({ s, value, onChange, onAdd }) {
    const [open, setOpen] = React7.useState(s.defaultOpen !== false);
    const listId = useStableId("fn-tree");
    return /* @__PURE__ */ React7.createElement("div", { className: "fn-tree-section" }, /* @__PURE__ */ React7.createElement("div", { className: "fn-tree-head" }, /* @__PURE__ */ React7.createElement("button", { type: "button", className: "fn-tree-toggle", "aria-expanded": open, "aria-controls": listId, onClick: () => setOpen((o) => !o) }, /* @__PURE__ */ React7.createElement(Icon, { name: "chevron-right", size: 16, className: "fn-tree-chevron" }), /* @__PURE__ */ React7.createElement("span", { className: "fn-caption" }, s.title)), typeof s.count === "number" ? /* @__PURE__ */ React7.createElement("span", { className: "fn-count" }, formatCount(s.count)) : null, onAdd ? /* @__PURE__ */ React7.createElement("button", { type: "button", className: "fn-tree-add", "aria-label": s.addLabel || `Add to ${s.title}`, title: s.addLabel || `Add to ${s.title}`, onClick: () => onAdd(s.id) }, /* @__PURE__ */ React7.createElement(Icon, { name: "plus", size: 16 })) : null), /* @__PURE__ */ React7.createElement("ul", { id: listId, className: "fn-tree-list", hidden: !open }, s.items.map((it) => /* @__PURE__ */ React7.createElement(TreeRow, { key: it.id, it, depth: 0, value, onChange }))));
  }
  function TreeNav({ sections, value, onChange, onAdd, label = "Library" }) {
    return /* @__PURE__ */ React7.createElement("nav", { className: "fn-tree", "aria-label": label }, sections.map((s) => /* @__PURE__ */ React7.createElement(TreeSectionView, { key: s.id, s, value, onChange, onAdd })));
  }
  var DEFAULT_SCOPES = [
    { label: "tenders", world: "peach" },
    { label: "buyers", world: "ice" },
    { label: "consultants", world: "sage" },
    { label: "past projects", world: "sage" }
  ];
  function joinWords(words) {
    const out = [];
    words.forEach((w2, i) => {
      if (i > 0) out.push(i === words.length - 1 ? " and " : ", ");
      out.push(w2);
    });
    return out;
  }
  function SearchBar({ scopes = DEFAULT_SCOPES, onSubmit, shortcut, value, defaultValue, onChange, name = "q", className, ...rest }) {
    const [inner, setInner] = React7.useState(String(defaultValue != null ? defaultValue : ""));
    const q = value !== void 0 ? String(value) : inner;
    const sentence = `Search ${scopes.map((s) => s.label).join(", ").replace(/, ([^,]*)$/, " and $1")}`;
    return /* @__PURE__ */ React7.createElement(
      "form",
      {
        role: "search",
        className: cx("fn-search", className),
        onSubmit: (e) => {
          e.preventDefault();
          onSubmit == null ? void 0 : onSubmit(q);
        }
      },
      /* @__PURE__ */ React7.createElement(Icon, { name: "search", size: 20, className: "fn-search-icon" }),
      /* @__PURE__ */ React7.createElement("span", { className: "fn-search-field" }, /* @__PURE__ */ React7.createElement(
        "input",
        {
          type: "search",
          name,
          "aria-label": sentence,
          autoComplete: "off",
          spellCheck: false,
          enterKeyHint: "search",
          value: q,
          onChange: (e) => {
            if (value === void 0) setInner(e.target.value);
            onChange == null ? void 0 : onChange(e);
          },
          ...rest
        }
      ), q === "" ? /* @__PURE__ */ React7.createElement("span", { className: "fn-search-hint", "aria-hidden": "true" }, "Search", " ", joinWords(
        scopes.map((s) => /* @__PURE__ */ React7.createElement("b", { key: s.label, "data-world": s.world }, s.label))
      ), "\u2026") : null),
      shortcut ? /* @__PURE__ */ React7.createElement("kbd", { className: "fn-kbd", "aria-hidden": "true" }, shortcut) : null
    );
  }
  var STAGE_ICON = { done: "check", current: "", next: "", skipped: "minus" };
  function StageTrack({ stages, onSelect, label = "Tender stages" }) {
    return /* @__PURE__ */ React7.createElement("ol", { className: "fn-stages", "aria-label": label }, stages.map((s) => {
      const Tag = onSelect ? "button" : "div";
      const state = s.status === "done" ? "done" : s.status === "current" ? "current step" : s.status === "skipped" ? "skipped" : "not started";
      return /* @__PURE__ */ React7.createElement("li", { key: s.id, className: "fn-stage", "data-status": s.status, "data-world": s.world }, /* @__PURE__ */ React7.createElement(
        Tag,
        {
          className: "fn-stage-slab",
          type: onSelect ? "button" : void 0,
          "aria-current": s.status === "current" ? "step" : void 0,
          onClick: onSelect ? () => onSelect(s.id) : void 0
        },
        /* @__PURE__ */ React7.createElement("span", { className: "fn-stage-mark", "aria-hidden": "true" }, STAGE_ICON[s.status] ? /* @__PURE__ */ React7.createElement(Icon, { name: STAGE_ICON[s.status], size: 14, strokeWidth: 2.25 }) : null),
        /* @__PURE__ */ React7.createElement("span", { className: "fn-stage-text" }, /* @__PURE__ */ React7.createElement("span", { className: "fn-stage-label" }, s.label), s.detail ? /* @__PURE__ */ React7.createElement("span", { className: "fn-stage-detail" }, s.detail) : null),
        /* @__PURE__ */ React7.createElement("span", { className: "fn-sr" }, ", ", state)
      ));
    }));
  }

  // src/states.tsx
  var React8 = __toESM(require_react_shim());
  var SPARK = "M30 3.5c.4 2.6 1.8 4.1 4.3 4.7-2.5.6-3.9 2.1-4.3 4.7-.4-2.6-1.8-4.1-4.3-4.7 2.5-.6 3.9-2.1 4.3-4.7Z";
  function Art({ kind }) {
    const ink = "var(--w-ink)";
    const deep = "var(--w-deep)";
    const field = "var(--w-field)";
    const paper = "var(--surface)";
    const s = { stroke: ink, strokeWidth: 2, strokeLinejoin: "round", strokeLinecap: "round" };
    switch (kind) {
      case "tender":
        return /* @__PURE__ */ React8.createElement(React8.Fragment, null, /* @__PURE__ */ React8.createElement("rect", { x: "9", y: "5", width: "20", height: "28", rx: "4", fill: paper, ...s }), /* @__PURE__ */ React8.createElement("path", { d: "M14 12h10M14 17h10M14 22h6", ...s }), /* @__PURE__ */ React8.createElement("circle", { cx: "29", cy: "29", r: "6.5", fill: deep, stroke: ink, strokeWidth: "2" }), /* @__PURE__ */ React8.createElement("path", { d: "m26.6 29 1.6 1.6 3.2-3.2", ...s }));
      case "research":
        return /* @__PURE__ */ React8.createElement(React8.Fragment, null, /* @__PURE__ */ React8.createElement("rect", { x: "7", y: "13", width: "16", height: "21", rx: "3", fill: field, ...s }), /* @__PURE__ */ React8.createElement("path", { d: "M12 19h2M17 19h1M12 24h2M17 24h1M12 29h6", ...s }), /* @__PURE__ */ React8.createElement("circle", { cx: "25", cy: "15", r: "7.5", fill: paper, ...s }), /* @__PURE__ */ React8.createElement("path", { d: "m30.5 20.5 4.5 4.5", stroke: ink, strokeWidth: "3", strokeLinecap: "round" }));
      case "match":
        return /* @__PURE__ */ React8.createElement(React8.Fragment, null, /* @__PURE__ */ React8.createElement("circle", { cx: "14", cy: "13", r: "5", fill: deep, ...s }), /* @__PURE__ */ React8.createElement("path", { d: "M5 31c0-5.5 4-9 9-9s9 3.5 9 9", fill: deep, ...s }), /* @__PURE__ */ React8.createElement("circle", { cx: "25", cy: "15", r: "5", fill: paper, ...s }), /* @__PURE__ */ React8.createElement("path", { d: "M16 33c0-5.5 4-9 9-9s9 3.5 9 9Z", fill: paper, ...s }));
      case "draft":
        return /* @__PURE__ */ React8.createElement(React8.Fragment, null, /* @__PURE__ */ React8.createElement("rect", { x: "5", y: "10", width: "26", height: "20", rx: "4", fill: paper, ...s }), /* @__PURE__ */ React8.createElement("path", { d: "M10 17h10M10 22h14", ...s }), /* @__PURE__ */ React8.createElement("path", { d: SPARK, style: { fill: "var(--spark)" }, transform: "translate(1 1)" }));
      case "review":
        return /* @__PURE__ */ React8.createElement(React8.Fragment, null, /* @__PURE__ */ React8.createElement("path", { d: "M8 8h24a3 3 0 0 1 3 3v14a3 3 0 0 1-3 3H18l-7 5v-5H8a3 3 0 0 1-3-3V11a3 3 0 0 1 3-3Z", fill: paper, ...s }), /* @__PURE__ */ React8.createElement("path", { d: "m14 18 4 4 8-8", stroke: "var(--good)", strokeWidth: "2.5", strokeLinecap: "round", strokeLinejoin: "round", fill: "none" }));
      case "export":
        return /* @__PURE__ */ React8.createElement(React8.Fragment, null, /* @__PURE__ */ React8.createElement("rect", { x: "9", y: "7", width: "24", height: "18", rx: "4", fill: deep, ...s }), /* @__PURE__ */ React8.createElement("rect", { x: "5", y: "13", width: "24", height: "18", rx: "4", fill: paper, ...s }), /* @__PURE__ */ React8.createElement("path", { d: "M13 26 21 18M15.5 18H21v5.5", ...s }));
      case "sources":
        return /* @__PURE__ */ React8.createElement(React8.Fragment, null, /* @__PURE__ */ React8.createElement("rect", { x: "13", y: "5", width: "18", height: "23", rx: "4", fill: deep, ...s }), /* @__PURE__ */ React8.createElement("rect", { x: "7", y: "11", width: "18", height: "23", rx: "4", fill: paper, ...s }), /* @__PURE__ */ React8.createElement("path", { d: "M11 18h10M11 23h10M11 28h6", ...s }));
      case "search":
      default:
        return /* @__PURE__ */ React8.createElement(React8.Fragment, null, /* @__PURE__ */ React8.createElement("circle", { cx: "17", cy: "17", r: "10", fill: paper, ...s }), /* @__PURE__ */ React8.createElement("path", { d: "m24.5 24.5 7 7", stroke: ink, strokeWidth: "3", strokeLinecap: "round" }), /* @__PURE__ */ React8.createElement("path", { d: "M13 17h8", ...s }));
    }
  }
  function EmptyState({ world = "peach", illustration = "tender", title, children, action, layout = "panel", headingLevel = 3, className }) {
    const titleId = useStableId("fn-empty");
    const H = `h${headingLevel}`;
    return /* @__PURE__ */ React8.createElement("section", { className: cx("fn-empty", `fn-empty--${layout}`, className), "data-world": world, "aria-labelledby": titleId }, /* @__PURE__ */ React8.createElement("span", { className: "fn-empty-art", "aria-hidden": "true" }, /* @__PURE__ */ React8.createElement("svg", { viewBox: "0 0 40 40", width: "40", height: "40", fill: "none", focusable: "false" }, /* @__PURE__ */ React8.createElement(Art, { kind: illustration }))), /* @__PURE__ */ React8.createElement("div", { className: "fn-empty-text" }, /* @__PURE__ */ React8.createElement(H, { id: titleId, className: "fn-empty-title" }, title), /* @__PURE__ */ React8.createElement("p", { className: "fn-empty-body" }, children)), action ? /* @__PURE__ */ React8.createElement(Button, { variant: action.variant || "primary", icon: action.icon || "plus", onClick: action.onClick, size: layout === "inline" ? "sm" : "md" }, action.label) : null);
  }

  // src/index.tsx
  var Final = {
    World,
    Glass,
    Panel,
    FloatingLabel,
    Card,
    Icon,
    Sparkle,
    FileGlyph,
    Button,
    IconButton,
    Menu,
    NavRail,
    TreeNav,
    SearchBar,
    StageTrack,
    Chip,
    ChipGroup,
    Status,
    Fit,
    Progress,
    ListRow,
    Tile,
    EntryCard,
    Provenance,
    Citation,
    EvidenceLayer,
    RowActions,
    AdvisoryStrip,
    ConflictCard,
    TextField,
    StatusSelect,
    EmptyState,
    worlds: WORLDS,
    worldShapes: WORLD_SHAPES,
    iconNames: Object.keys(ICONS).sort()
  };
  var w = window;
  w.Final = Object.assign(w.Final || {}, Final);
})();

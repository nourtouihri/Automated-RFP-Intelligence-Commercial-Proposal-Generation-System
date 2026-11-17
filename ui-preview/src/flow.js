// @ts-check
// The tender's next step, shared by Overview, Research, Match and Draft.
window.UIP = window.UIP || {};

window.UIP.flow = (function () {
  var store = window.UIP.store;
  var ui = window.UIP.ui;

  function researching(/** @type {any} */ s, /** @type {string} */ id) {
    return !!s.running['research:' + id];
  }
  function generating(/** @type {any} */ s, /** @type {string} */ id) {
    return !!s.running['deck:' + id];
  }

  /** proposal/main.py TENDER_ID_RE: the id becomes the deck's file name. Detection accepts any id. */
  var DECK_ID = /^[A-Za-z0-9._-]{1,64}$/;

  /** Why Generate Deck cannot run, or null. Mirrors proposal/main.py and compose.py's InputError. */
  function deckBlocked(/** @type {import('./types').Tender} */ t) {
    if (!DECK_ID.test(t.id)) return 'This tender’s ID can’t name a deck file; ingest it again with letters, digits, dots, dashes or underscores.';
    if (!t.requirements.length) return 'Add requirements to generate a deck.';
    return null;
  }

  /** @param {any} s @param {import('./types').Tender} t @param {{ onError: (e: any, on: 'research' | 'deck') => void }} o */
  function primary(s, t, o) {
    var r = s.research[t.id];
    var p = s.proposals[t.id];
    var busy = s.running.pipeline ? 'n8n is running the full pipeline; this tender updates on its own.' : null;
    function research() { store.runResearch(t.id, false).catch(function (e) { o.onError(e, 'research'); }); }
    function deck() { store.generateDeck(t.id).catch(function (e) { o.onError(e, 'deck'); }); }
    if (researching(s, t.id)) return { label: 'Researching…', icon: 'building', loading: true };
    if (generating(s, t.id)) return { label: 'Generating deck…', icon: 'presentation', loading: true };
    if (p && p.kind !== 'rejected') return { label: 'Review Deck', icon: 'list-checks', onClick: function () { ui.go('review/' + t.id); } };
    if (p && p.kind === 'rejected') return { label: 'Regenerate Deck', icon: 'refresh', onClick: deck, disabledReason: busy || deckBlocked(t) };
    if (!r) return { label: 'Run Research', icon: 'play', onClick: research, disabledReason: busy };
    if (!s.insights[t.id]) return { label: 'Run Insights', icon: 'radar', onClick: function () { ui.go('insights/' + t.id); }, disabledReason: busy };
    return { label: 'Generate Deck', icon: 'presentation', onClick: deck, disabledReason: busy || deckBlocked(t) };
  }

  /** Where each tender stands across the pipeline, from what each service holds for it. */
  var PIPELINE = [
    { id: 'detect', label: 'Detect', world: 'peach', has: function () { return true; } },
    { id: 'research', label: 'Research', world: 'ice', has: function (/** @type {any} */ s, /** @type {string} */ id) { var r = s.research[id]; return !!r && r.status !== 'unavailable'; } },
    { id: 'insights', label: 'Insights', world: 'ice', has: function (/** @type {any} */ s, /** @type {string} */ id) { return !!s.insights[id]; } },
    { id: 'match', label: 'Match', world: 'sage', has: function (/** @type {any} */ s, /** @type {string} */ id) { return !!s.proposals[id]; } },
    { id: 'draft', label: 'Draft', world: 'mist', has: function (/** @type {any} */ s, /** @type {string} */ id) { var p = s.proposals[id]; return !!p && p.kind !== 'rejected'; } },
    { id: 'review', label: 'Review', world: 'blush', has: function (/** @type {any} */ s, /** @type {string} */ id) { var p = s.proposals[id]; return !!p && p.kind !== 'rejected' && p.warnings.length > 0; } },
    { id: 'export', label: 'Export', world: 'stone', has: function (/** @type {any} */ s, /** @type {string} */ id) { var p = s.proposals[id]; return !!p && !!p.artifacts.pptx; } },
  ];
  var PIPELINE_DETAIL = { detect: 'detected', research: 'researched', match: 'matched', draft: 'with a deck', review: 'with warnings', export: 'ready to download' };

  /** "Meridian Consumer Goods Group · closes 20 Nov · 4 requirements" */
  function kicker(/** @type {import('./types').Tender} */ t) {
    var when = !t.deadline ? 'no deadline' : (t.quality.is_expired ? 'closed ' : 'closes ') + ui.date(t.deadline);
    return [t.issuer, when, ui.count(t.requirements.length, 'requirement')].join(' · ');
  }

  function rowsOf(/** @type {any} */ p) {
    var d = p && p.deck;
    if (!d) return [];
    return d.all_requirements && d.all_requirements.length ? d.all_requirements : d.requirements || [];
  }

  return { researching: researching, generating: generating, deckBlocked: deckBlocked, primary: primary, kicker: kicker, rowsOf: rowsOf, PIPELINE: PIPELINE, PIPELINE_DETAIL: PIPELINE_DETAIL };
})();

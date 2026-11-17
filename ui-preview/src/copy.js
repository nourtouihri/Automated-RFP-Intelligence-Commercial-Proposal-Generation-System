// @ts-check
// Backend codes and strings turned into interface words (voice.md: calm, specific).
window.UIP = window.UIP || {};

window.UIP.copy = (function () {
  var STRONG_AT = 0.55;
  var PARTIAL_AT = 0.4;

  /** @param {number} score @returns {'strong' | 'partial' | 'gap'} */
  function fitLevel(score) {
    return score >= STRONG_AT ? 'strong' : score >= PARTIAL_AT ? 'partial' : 'gap';
  }

  function matchScore(/** @type {number} */ score) {
    return 'Match ' + score.toFixed(2);
  }

  var SOURCE = { simulated_feed: 'Simulated feed', TED: 'TED EU', SAM: 'SAM.gov', manual: 'Manual' };

  /** @type {Record<string, { label: string, chip: 'good' | 'stale' | 'peach' | 'neutral' }>} */
  var TENDER_STATUS = {
    new: { label: 'New', chip: 'peach' },
    incomplete: { label: 'Incomplete', chip: 'stale' },
    processed: { label: 'Processed', chip: 'good' },
    archived: { label: 'Archived', chip: 'neutral' },
  };

  /** @type {Record<string, string>} detection/normalize.py warning codes */
  var QUALITY = {
    missing_deadline: 'No deadline in the notice',
    deadline_in_past: 'Deadline has passed',
    sanitized_chars: 'Unsafe characters removed at intake',
    llm_unavailable: 'Sector and requirements extracted without the model',
    unknown_fields: 'Unknown fields ignored',
    no_raw_text: 'No tender text supplied',
    text_too_short: 'Tender text is very short',
    text_mostly_symbols: 'Tender text is mostly symbols',
    requirements_capped: 'Requirements capped at 100',
    requirements_trimmed: 'Long requirements trimmed',
  };

  function qualityWord(/** @type {string} */ code) {
    if (code.indexOf('possible_duplicate_of:') === 0) return 'Possible duplicate of ' + code.slice(22);
    return QUALITY[code] || code;
  }

  function sectorLabel(/** @type {string} */ s) {
    return s === 'unknown' ? 'Sector not tagged' : s;
  }

  /** @type {Record<string, { label: string, tone: 'good' | 'stale' }>} */
  var RESEARCH_STATUS = {
    complete: { label: 'Research complete', tone: 'good' },
    partial: { label: 'Research partial', tone: 'stale' },
    unavailable: { label: 'Research unavailable', tone: 'stale' },
  };

  var CONFIDENCE = { high: 'High confidence', medium: 'Medium confidence', low: 'Low confidence' };

  var INSIGHTS_STATUS = {
    complete: { label: 'Insights complete', tone: 'good' },
    partial: { label: 'Insights partial', tone: 'stale' },
    unavailable: { label: 'Insights unavailable', tone: 'stale' },
  };

  var BUDGET_METHOD = {
    explicit: 'Stated in the documents or on the web',
    comparables: 'Priced from comparable tenders found online',
    effort: 'Built up from effort × day rate',
    none: 'Nothing priced — no amount the sources support',
  };

  /** The deck's sections, in slide order. */
  var SECTIONS = [
    { id: 'letter', label: 'Cover letter' },
    { id: 'summary', label: 'Executive summary' },
    { id: 'buyer', label: 'Buyer understanding' },
    { id: 'matrix', label: 'Requirements matrix' },
    { id: 'approach', label: 'Approach' },
    { id: 'team', label: 'Team' },
    { id: 'references', label: 'References' },
    { id: 'investment', label: 'Investment' },
  ];
  var NO_BID_SECTIONS = [
    { id: 'letter', label: 'Cover' },
    { id: 'matrix', label: 'Requirements matrix' },
    { id: 'warnings', label: 'Bid warnings' },
  ];

  /** compose.py step names → deck section */
  var STEP_SECTION = { brief: 'letter', letter: 'letter', summary: 'summary', needs: 'buyer', buyer: 'buyer', evidence: 'matrix', requirements: 'matrix', approach: 'approach', team: 'team', references: 'references', investment: 'investment' };

  function stepsIn(/** @type {string} */ text) {
    var found = {};
    var re = /\b(brief|letter|summary|needs|buyer|evidence|requirements|approach|team|references|investment)\.[a-z_]/g;
    var m;
    while ((m = re.exec(text))) found[STEP_SECTION[m[1]]] = true;
    return Object.keys(found);
  }

  /**
   * Which deck sections a bid warning (compose.bid_warnings, build.py) is about.
   * @param {string} w @returns {string[]}
   */
  function warningSections(w) {
    if (/^(verifier:|grounding check unavailable|\d+ (text field|list))/.test(w) || /^speed promise/.test(w)) {
      var s = stepsIn(w);
      if (s.length) return s;
      var bare = /grounding check unavailable: (\w+):/.exec(w);
      if (bare && STEP_SECTION[bare[1]]) return [STEP_SECTION[bare[1]]];
    }
    if (/^research unavailable/.test(w)) return ['buyer'];
    if (/^the plan runs/.test(w)) return ['approach'];
    if (/^evidence for |requirements shown|no requirement has strong|^no-bid recommendation/.test(w)) return ['matrix'];
    if (/^no project matched|^no delivered reference/.test(w)) return ['references'];
    if (/^no CV matched|^every matched consultant/.test(w)) return ['team'];
    return [];
  }

  /** @param {string} w @returns {'risk' | 'neutral'} */
  function warningTone(w) {
    return /unsupported claim|^no deck written/.test(w) ? 'risk' : 'neutral';
  }

  function sentence(/** @type {string} */ s) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
  }

  /** @type {Record<string, string>} */
  var STEP_LABEL = { brief: 'Tender brief', letter: 'Cover letter', summary: 'Executive summary', needs: 'Buyer needs', evidence: 'Evidence per requirement', approach: 'Approach', team: 'Team', references: 'References', investment: 'Investment' };

  /** @param {any[]} trace @param {string} sectionId */
  function traceFor(trace, sectionId) {
    return (trace || []).filter(function (s) { return STEP_SECTION[s.step] === sectionId; });
  }

  /** True when a step failed, kept an unsupported claim, or its verifier found a weak claim or could not judge. */
  function traceNeedsLook(/** @type {any} */ s) {
    var v = s.verifier;
    return s.ok === false || (s.unsupported || []).length > 0 || !!(v && v.error) ||
      (Array.isArray(v) && v.some(function (/** @type {any} */ row) { return row.verdict === 'unsupported' || row.verdict === 'partial'; }));
  }

  /** One plain line for the entries of one step, or of all steps written for one section. */
  function traceLine(/** @type {any[]} */ steps) {
    var attempts = 0, cut = 0, unsupported = 0, failed = false;
    var tally = { supported: 0, partial: 0, unsupported: 0 };
    var unjudged = false;
    steps.forEach(function (s) {
      attempts += s.attempts || 0;
      cut += (s.trimmed || []).length;
      unsupported += (s.unsupported || []).length;
      if (s.ok === false) failed = true;
      if (s.verifier && s.verifier.error) unjudged = true;
      (Array.isArray(s.verifier) ? s.verifier : []).forEach(function (/** @type {any} */ row) { if (row.verdict in tally) tally[/** @type {'supported'} */ (row.verdict)] += 1; });
    });
    var parts = [];
    parts.push(failed ? 'Failed' : attempts > steps.length ? 'Took ' + attempts + ' attempts' : 'Right on the first try');
    if (cut) parts.push(cut + (cut === 1 ? ' field' : ' fields') + ' cut to fit');
    if (unsupported) parts.push(unsupported + (unsupported === 1 ? ' unsupported claim' : ' unsupported claims'));
    if (unjudged) parts.push('claims not rated against sources');
    var judged = tally.supported + tally.partial + tally.unsupported;
    if (judged) parts.push('verifier: ' + tally.supported + ' supported, ' + tally.partial + ' partial, ' + tally.unsupported + ' unsupported');
    return parts.join(' · ');
  }

  /** The design's four review statuses, as the StatusSelect options. */
  var REVIEW_STATUS = [
    { value: 'draft', label: 'Draft', tone: 'neutral' },
    { value: 'review', label: 'In review', tone: 'stale' },
    { value: 'approved', label: 'Approved', tone: 'good' },
    { value: 'work', label: 'Needs work', tone: 'risk' },
  ];

  /** @type {Record<string, string>} shared/errors.py codes → what to tell the person */
  var ERROR = {
    UNAUTHORIZED: 'The service refused the internal token. An operator needs to check INTERNAL_SERVICE_TOKEN.',
    UPSTREAM_UNAVAILABLE: 'Retrieval or the model is unavailable right now. Try again in a moment.',
    INTERNAL: 'Something failed on the server. Try again; if it repeats, share the request ID.',
  };

  return {
    STRONG_AT: STRONG_AT,
    PARTIAL_AT: PARTIAL_AT,
    fitLevel: fitLevel,
    matchScore: matchScore,
    SOURCE: SOURCE,
    TENDER_STATUS: TENDER_STATUS,
    qualityWord: qualityWord,
    sectorLabel: sectorLabel,
    RESEARCH_STATUS: RESEARCH_STATUS,
    CONFIDENCE: CONFIDENCE,
    INSIGHTS_STATUS: INSIGHTS_STATUS,
    BUDGET_METHOD: BUDGET_METHOD,
    SECTIONS: SECTIONS,
    NO_BID_SECTIONS: NO_BID_SECTIONS,
    warningSections: warningSections,
    warningTone: warningTone,
    sentence: sentence,
    STEP_LABEL: STEP_LABEL,
    traceFor: traceFor,
    traceNeedsLook: traceNeedsLook,
    traceLine: traceLine,
    REVIEW_STATUS: REVIEW_STATUS,
    ERROR: ERROR,
  };
})();

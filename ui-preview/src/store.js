// @ts-check
// The app's state and its actions. Every action calls the UI proxy through api.js;
// only preferences and "Recently opened" live in this browser.
window.UIP = window.UIP || {};

window.UIP.store = (function () {
  var api = window.UIP.api;
  var copy = window.UIP.copy;

  /* Per-viewer conveniences, kept in this browser only (no settings endpoint exists). */
  var PREFS_KEY = 'uip.prefs';
  var RECENT_KEY = 'uip.recent';
  var SECTOR_CHOICES_KEY = 'uip.sectorChoices';
  var DEFAULT_PREFS = {
    sources: { simulated_feed: true, TED: true, SAM: true, manual: true },
    tedPage: 1,
    researchClosed: false,
    topK: 5,
    minSimilarity: 0,
    claimCheck: false,
    theme: 'system',
  };
  function readJson(/** @type {string} */ key, /** @type {any} */ fallback) {
    try {
      var raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) {
      return fallback;
    }
  }
  function writeJson(/** @type {string} */ key, /** @type {any} */ value) {
    try { window.localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode: keep it in memory */ }
  }

  /** @type {{ tenders: import('./types').Tender[], research: Record<string, import('./types').ProspectResearch>, insights: Record<string, import('./types').InsightsRun>, proposals: Record<string, import('./types').ProposalResult>, reviews: Record<string, import('./types').Review>, hits: Record<string, import('./types').QueryResult>, stats: import('./types').LibraryStats | null, running: Record<string, boolean>, pipeline: import('./types').PipelineRun | null, seed: import('./types').SeedResult | null, fetched: any, prefs: typeof DEFAULT_PREFS, recent: string[], health: any, loading: boolean, loadError: import('./types').CapturedError | null, version: number }} */
  var state = {
    tenders: [],
    research: {},
    insights: {},
    proposals: {},
    reviews: {},
    hits: {},
    stats: null,
    running: {},
    pipeline: null,
    seed: null,
    fetched: null,
    prefs: Object.assign({}, DEFAULT_PREFS, readJson(PREFS_KEY, {})),
    recent: readJson(RECENT_KEY, []),
    sectorChoices: readJson(SECTOR_CHOICES_KEY, {}),
    health: null,
    loading: true,
    loadError: null,
    version: 0,
  };

  var listeners = new Set();
  function emit() {
    state = Object.assign({}, state, { version: state.version + 1 });
    listeners.forEach(function (l) { l(); });
  }
  function subscribe(/** @type {() => void} */ l) {
    listeners.add(l);
    return function () { listeners.delete(l); };
  }
  function get() {
    return state;
  }
  function useStore() {
    return React.useSyncExternalStore(subscribe, get);
  }

  /**
   * Runs a service call: marks `key` running until it settles, then passes its result or error on.
   * @template T @param {string} key @param {() => Promise<T>} run @returns {Promise<T>}
   */
  function call(key, run) {
    state.running = Object.assign({}, state.running, { [key]: true });
    emit();
    function settle() {
      var next = Object.assign({}, state.running);
      delete next[key];
      state.running = next;
    }
    return run().then(
      function (out) { settle(); emit(); return out; },
      function (e) { settle(); emit(); throw e; }
    );
  }

  function tender(/** @type {string} */ id) {
    return state.tenders.find(function (t) { return t.id === id; }) || null;
  }

  function applySectorChoices(/** @type {Record<string, import('./types').ProspectResearch>} */ research) {
    var out = {};
    Object.keys(research || {}).forEach(function (id) {
      out[id] = state.sectorChoices[id]
        ? Object.assign({}, research[id], { sector: state.sectorChoices[id] })
        : research[id];
    });
    return out;
  }

  /* -------------------------------------------------------------- Load */

  function reloadTenders() {
    return api.get('/api/tenders').then(function (/** @type {import('./types').Tender[]} */ list) {
      state.tenders = list;
    });
  }

  /** Fills tenders, research and decks. Never rejects: a failure is kept in `loadError` for the page to show. */
  function load() {
    state.loading = true;
    state.loadError = null;
    emit();
    return Promise.all([api.get('/api/tenders'), api.get('/api/research'), api.get('/api/insights').catch(function () { return {}; }), api.get('/api/proposals')]).then(
      function (r) {
        state.tenders = r[0];
        state.research = applySectorChoices(r[1]);
        state.insights = r[2];
        state.proposals = r[3];
        state.loading = false;
        emit();
      },
      function (e) {
        state.loading = false;
        state.loadError = e;
        emit();
      }
    );
  }

  /** Re-reads tenders, research and decks behind the screen on show, without the page-wide loading state. Keeps what it had if a read fails. */
  function refresh() {
    return Promise.all([api.get('/api/tenders'), api.get('/api/research'), api.get('/api/insights').catch(function () { return {}; }), api.get('/api/proposals')]).then(
      function (r) {
        state.tenders = r[0];
        state.research = applySectorChoices(r[1]);
        state.insights = r[2];
        state.proposals = r[3];
        emit();
      },
      function () {}
    );
  }

  /* ---------------------------------------------------------- Pipeline */

  var WATCH_EVERY_MS = 5000;
  var WATCH_UNTRACKED_FOR_MS = 20 * 60 * 1000;

  /** @returns {import('./types').PipelineTally} */
  function tally() {
    var proposals = state.proposals;
    return {
      tenders: state.tenders.length,
      researched: Object.keys(state.research).filter(function (id) { return state.research[id].status !== 'unavailable'; }).length,
      decks: Object.keys(proposals).filter(function (id) { return proposals[id].kind !== 'rejected'; }).length,
    };
  }

  function finishPipeline(/** @type {Partial<import('./types').PipelineRun>} */ change) {
    state.pipeline = Object.assign({}, state.pipeline, { stoppedAt: Date.now() }, change);
    var next = Object.assign({}, state.running);
    delete next.pipeline;
    state.running = next;
    emit();
  }

  /** @returns {import('./types').CapturedError} */
  function runFailure(/** @type {{ error: string | null, failed_node: string | null }} */ run) {
    var message = (run.failed_node ? run.failed_node + ': ' : '') + (run.error || 'The run stopped in n8n.');
    return { status: 500, request_id: '', body: { error: { code: 'INTERNAL', message: message, field: null, retryable: true, request_id: null } } };
  }

  /**
   * Every 5 s while n8n runs: re-reads the services, so each screen fills in as a stage lands, and asks n8n how the run is going.
   * A 404 means n8n has not saved the run yet. Without an API key the run cannot be followed, so the re-reads stop after 20 minutes.
   */
  function watchPipeline() {
    window.setTimeout(function () {
      var run = /** @type {import('./types').PipelineRun} */ (state.pipeline);
      var status = api.get('/api/pipeline/runs/' + encodeURIComponent(String(run.id))).catch(function (/** @type {import('./types').CapturedError} */ e) {
        return { status: e.status === 404 ? 'running' : 'untracked' };
      });
      Promise.all([refresh(), status]).then(function (r) {
        var now = r[1];
        if (now.status === 'success') return refresh().then(function () { finishPipeline({ status: 'success', workflowId: now.workflow_id || run.workflowId }); });
        if (now.status === 'error') return refresh().then(function () { finishPipeline({ status: 'error', error: runFailure(now), workflowId: now.workflow_id || null }); });
        var tracked = now.status !== 'untracked';
        if (!tracked && Date.now() - run.startedAt > WATCH_UNTRACKED_FOR_MS) return finishPipeline({ status: 'unknown', tracked: false });
        var workflowId = now.workflow_id || run.workflowId;
        if (tracked !== run.tracked || workflowId !== run.workflowId) {
          state.pipeline = Object.assign({}, run, { tracked: tracked, workflowId: workflowId });
          emit();
        }
        watchPipeline();
      });
    }, WATCH_EVERY_MS);
  }

  /**
   * POST /api/pipeline/run: n8n fetches a TED and a SAM page and takes their first notices through detection, research, matching and the deck.
   * Resolves once n8n has started; the run itself is followed by watchPipeline.
   */
  function runPipeline() {
    if (state.running.pipeline) return Promise.resolve(state.pipeline);
    state.pipeline = { id: null, status: 'running', tracked: true, error: null, workflowId: null, startedAt: Date.now(), stoppedAt: null, before: tally(), seen: false };
    state.running = Object.assign({}, state.running, { pipeline: true });
    emit();
    return api.post('/api/pipeline/run', { page: state.prefs.tedPage || 1 }).then(
      function (/** @type {{ execution_id: string }} */ r) {
        state.pipeline = Object.assign({}, state.pipeline, { id: String(r.execution_id) });
        emit();
        watchPipeline();
        return state.pipeline;
      },
      function (/** @type {import('./types').CapturedError} */ e) {
        finishPipeline({ status: 'error', error: e });
        throw e;
      }
    );
  }

  /** Someone has looked at the finished run: its pop-out closes and Review stops calling for attention. */
  function seePipeline() {
    if (!state.pipeline || state.pipeline.seen) return;
    state.pipeline = Object.assign({}, state.pipeline, { seen: true });
    emit();
  }

  /* ---------------------------------------------------------- Research */

  /** POST /research/{id}?force= . A skip for a closed tender is returned, never stored (as the service does). */
  function runResearch(/** @type {string} */ id, /** @type {boolean} */ force) {
    return call('research:' + id, function () {
      var params = { force: force || state.prefs.researchClosed ? true : undefined };
      return api.post('/api/research/' + encodeURIComponent(id), undefined, params).then(function (/** @type {import('./types').ProspectResearch} */ r) {
        var skipped = r.status === 'unavailable' && /^Skipped: tender deadline has passed/.test(r.notes);
        if (!skipped) {
          var chosen = state.sectorChoices[id];
          state.research = Object.assign({}, state.research, { [id]: chosen ? Object.assign({}, r, { sector: chosen }) : r });
        }
        return r;
      });
    });
  }

  /** GET /research/{id}/audit: the steps of the tender's latest run. Read on demand, not kept in the store. */
  function loadAudit(/** @type {string} */ id) {
    return api.get('/api/research/' + encodeURIComponent(id) + '/audit');
  }

  function insightsOf(/** @type {string} */ id) {
    return state.insights[id] || null;
  }

  function runInsights(/** @type {string} */ id) {
    return call('insights:' + id, function () {
      return api.post('/api/insights/' + encodeURIComponent(id)).then(function (/** @type {import('./types').InsightsRun} */ r) {
        state.insights = Object.assign({}, state.insights, { [id]: r });
        return r;
      });
    });
  }

  /* ---------------------------------------------------------- Proposal */

  /** POST /proposal/{id}: the deck, plus the knowledge-base records its rows cite, kept for the evidence panels.
   *  The Strict claim check preference travels with every generation and rebuild. */
  function generateDeck(/** @type {string} */ id, /** @type {{ settings?: Record<string, string | number>, force_bid?: boolean }=} */ options) {
    return call('deck:' + id, function () {
      var body = Object.assign({}, options, { claim_check: !!state.prefs.claimCheck });
      if (state.sectorChoices[id]) body.sector = state.sectorChoices[id];
      return api.post('/api/proposal/' + encodeURIComponent(id), body).then(function (/** @type {any} */ response) {
        state.hits = Object.assign({}, state.hits, response && response.hits || {});
        return api.get('/api/proposal/' + encodeURIComponent(id)).then(function (/** @type {import('./types').ProposalResult} */ deck) {
          state.proposals = Object.assign({}, state.proposals, { [id]: deck });
          return deck;
        });
      });
    });
  }

  /** Keeps a chosen research conflict in this browser and applies it to all later UI/deck work. */
  function chooseSector(/** @type {string} */ id, /** @type {string} */ sector) {
    var choices = Object.assign({}, state.sectorChoices, { [id]: sector });
    state.sectorChoices = choices;
    writeJson(SECTOR_CHOICES_KEY, choices);
    if (state.research[id]) {
      state.research = Object.assign({}, state.research, {
        [id]: Object.assign({}, state.research[id], { sector: sector }),
      });
    }
    emit();
  }

  /* --------------------------------------------------------- Detection */

  /** PATCH /tenders/{id}/status: archives a tender, or restores the status its data quality derives. Keeps the tender where it is in the list. */
  function setTenderArchived(/** @type {string} */ id, /** @type {boolean} */ archived) {
    return call('archive', function () {
      return api.patch('/api/tenders/' + encodeURIComponent(id) + '/status', { status: archived ? 'archived' : 'active' }).then(function (/** @type {import('./types').Tender} */ t) {
        state.tenders = state.tenders.map(function (x) { return x.id === t.id ? t : x; });
        return t;
      });
    });
  }

  /** POST /tenders/seed, then reloads the tenders it added. */
  function seedFeed() {
    return call('seed', function () {
      return api.post('/api/tenders/seed').then(function (/** @type {import('./types').SeedResult} */ result) {
        return reloadTenders().then(function () {
          state.seed = result;
          return result;
        });
      });
    });
  }

  /** POST /ingest/TED or POST /ingest/SAM {page}. Fetched notices are not stored. */
  function fetchNotices(/** @type {'TED' | 'SAM'} */ source, /** @type {number} */ page) {
    return call('fetch', function () {
      return api.post('/api/ingest/' + source, { page: page }).then(function (/** @type {import('./types').MappedBatch} */ batch) {
        state.fetched = Object.assign({}, batch, { page: page, source: source });
        return state.fetched;
      });
    });
  }
  /* ------------------------------------------------------------ Review */

  /** The review for the deck on screen. One stored for an older deck is not carried over: it starts empty. */
  function reviewOf(/** @type {string} */ id) {
    var stored = state.reviews[id];
    var deck = state.proposals[id];
    if (stored && deck && stored.deck_generated_at === deck.generated_at) return stored;
    return { deck_generated_at: deck ? deck.generated_at : '', sections: {}, signed_off_by: null, signed_off_at: null };
  }

  /** GET /proposal/{id}/review. */
  function loadReview(/** @type {string} */ id) {
    return api.get('/api/proposal/' + encodeURIComponent(id) + '/review').then(function (/** @type {import('./types').Review} */ r) {
      state.reviews = Object.assign({}, state.reviews, { [id]: r });
      emit();
      return r;
    });
  }

  /** Resolves with the review once the service's copy for the deck on screen is held; rejects if it cannot be read. */
  function ensureReview(/** @type {string} */ id) {
    var stored = state.reviews[id];
    var deck = state.proposals[id];
    return stored && deck && stored.deck_generated_at === deck.generated_at ? Promise.resolve(stored) : loadReview(id);
  }

  /** Re-reads the deck and its review, for when another run regenerated the deck. */
  function reloadReview(/** @type {string} */ id) {
    return call('review:' + id, function () {
      return api.get('/api/proposal/' + encodeURIComponent(id)).then(function (/** @type {import('./types').ProposalResult} */ deck) {
        state.proposals = Object.assign({}, state.proposals, { [id]: deck });
        return loadReview(id);
      });
    });
  }

  /** PUT /proposal/{id}/review for the deck on screen. A 409 means the service holds a newer deck. */
  function saveReview(/** @type {string} */ id, /** @type {Partial<import('./types').Review>} */ change) {
    return call('review:' + id, function () {
      return ensureReview(id).then(function () {
        var current = reviewOf(id);
        var body = { deck_generated_at: current.deck_generated_at, sections: current.sections, signed_off_by: current.signed_off_by };
        return api.put('/api/proposal/' + encodeURIComponent(id) + '/review', Object.assign(body, change)).then(function (/** @type {import('./types').Review} */ r) {
          state.reviews = Object.assign({}, state.reviews, { [id]: r });
          return r;
        });
      });
    });
  }

  // Defines const SECTION to SLIDE_NB
  const SECTION_TO_SLIDE_NB = new Map([
  ["letter", 2],
  ["summary", 3],
  ["buyer", 4],
  ["matrix", 5],
  ["approach", 6],
  ["team", 7],
  ["references", 8],
  ["investment", 9]
]);

  /** PUT /proposal/edit/{id}. Edits selected section.*/
  function promptEdit(
    /** @type {string} */ id, 
    /** @type {string} */ section, 
    /** @type {string} */ prompt
  ) {
    return call("proposal", function () {
      const slide_nb = SECTION_TO_SLIDE_NB.get(section)
      var body = { slide: slide_nb, prompt: prompt };
      return api.put('/api/proposal/edit/' + encodeURIComponent(id), body)
          .then(function (/** @type {import('./types').EditProposalResult} */ res) {
            if (!res.changed) return res;
            return api.get('/api/proposal/' + encodeURIComponent(id)).then(function (/** @type {import('./types').ProposalResult} */ deck) {
              state.proposals = Object.assign({}, state.proposals, { [id]: deck });
              return loadReview(id).then(function () {
                emit();
                return res;
              });
            });
        });
    });
  }

  /** PUT /proposal/accept/{id}. Accepts the result (the deck) in the screen, this also generates PPTX*/
  function acceptProposal(
    /** @type {string} */ id, 
  ) {
    return call("proposal", function () {
      return api.put('/api/proposal/accept/' + encodeURIComponent(id))
          .then(function (/** @type {import('./types').AcceptProposalResult} */ r) {
            state.proposals = Object.assign({}, state.proposals, {
              [id]: Object.assign({}, state.proposals[id], r, r.kind === 'rejected' ? { review_status: 'draft' } : { review_status: 'accepted' }),
            });
            emit();
            return r;
        });
    });
  }

  /** PUT /proposal/refuse/{id}. This just refuses the given proposal. Doesn't generate the PPTX.*/
  function refuseProposal(
    /** @type {string} */ id, 
  ) {
    return call("proposal", function () {
      return api.put('/api/proposal/refuse/' + encodeURIComponent(id))
          .then(function (/** @type {import('./types').RefuseProposalResult} */ r) {
            state.proposals = Object.assign({}, state.proposals, {
              [id]: Object.assign({}, state.proposals[id], { review_status: r.review_status }),
            });
            emit();
            return r;
        });
    });
  }
  

  function setSectionStatus(/** @type {string} */ id, /** @type {string} */ section, /** @type {import('./types').ReviewStatus} */ status) {
    return ensureReview(id).then(function () {
      return saveReview(id, { sections: Object.assign({}, reviewOf(id).sections, { [section]: status }) });
    });
  }

  function signOff(/** @type {string} */ id, /** @type {string | null} */ name) {
    return saveReview(id, { signed_off_by: name });
  }

  var RAW_TEXT_MAX = 20000;
  var TITLE_MAX = 400;
  var ISSUER_MAX = 200;
  var REQ_MAX_ITEMS = 100;
  var REQ_MAX_CHARS = 1000;

  /** @returns {import('./types').CapturedError} */
  function invalid(/** @type {import('./types').ErrorCode} */ code, /** @type {string} */ message, /** @type {string} */ field) {
    return { status: 422, request_id: '', body: { error: { code: code, message: message, field: field, retryable: false, request_id: null } } };
  }

  /** Mirrors detection/normalize.py's rejects, so the form can show a field error before any call. */
  function validateIngest(/** @type {import('./types').IngestPayload} */ p) {
    var title = (p.title || '').trim();
    var issuer = (p.issuer || '').trim();
    if (!title) return invalid('TENDER_INVALID_FIELD', 'Missing required field: title', 'title');
    if (title.length > TITLE_MAX) return invalid('TENDER_INVALID_FIELD', 'title exceeds ' + TITLE_MAX + ' character cap (' + title.length + ' chars)', 'title');
    if (!issuer) return invalid('TENDER_INVALID_FIELD', 'Missing required field: issuer', 'issuer');
    if (issuer.length > ISSUER_MAX) return invalid('TENDER_INVALID_FIELD', 'issuer exceeds ' + ISSUER_MAX + ' character cap (' + issuer.length + ' chars)', 'issuer');
    if (p.deadline && !/^\d{4}-\d{2}-\d{2}$/.test(p.deadline)) return invalid('TENDER_INVALID_DEADLINE', "Invalid deadline date format: '" + p.deadline + "'. Use YYYY-MM-DD.", 'deadline');
    var reqs = p.requirements || [];
    if (reqs.length > REQ_MAX_ITEMS) return invalid('TENDER_INVALID_REQUIREMENTS', 'requirements exceeds ' + REQ_MAX_ITEMS + ' item cap (' + reqs.length + ' items)', 'requirements');
    if (reqs.some(function (r) { return r.length > REQ_MAX_CHARS; })) return invalid('TENDER_INVALID_REQUIREMENTS', 'each requirement must be at most ' + REQ_MAX_CHARS + ' characters', 'requirements');
    if ((p.raw_text || '').length > RAW_TEXT_MAX) return invalid('RAW_TEXT_TOO_LONG', 'raw_text exceeds ' + RAW_TEXT_MAX + ' character cap (' + (p.raw_text || '').length + ' chars)', 'raw_text');
    return null;
  }

  /** POST /tenders/ingest: detection answers with the stored tender (the existing one when it is a duplicate). */
  function ingest(/** @type {import('./types').IngestPayload} */ p) {
    var bad = validateIngest(p);
    if (bad) return Promise.reject(bad);
    return call('ingest', function () {
      return api.post('/api/tenders/ingest', p).then(function (/** @type {import('./types').Tender} */ t) {
        state.tenders = [t].concat(state.tenders.filter(function (x) { return x.id !== t.id; }));
        return t;
      });
    });
  }

  /** A notice's tender id: its own id behind its source, so TED and SAM.gov ids cannot collide. */
  function noticeTenderId(/** @type {import('./types').Notice} */ n) {
    return n.source.toLowerCase() + '-' + n.id;
  }

  /** What n8n sends detection for a fetched notice. */
  function noticePayload(/** @type {import('./types').Notice} */ n) {
    return { id: noticeTenderId(n), title: n.title, issuer: n.issuer, deadline: n.deadline || undefined, raw_text: n.raw_text, requirements: n.raw_text ? [n.raw_text] : [], source: n.source, issuer_country: n.issuer_country, notice_type: n.notice_type, published_at: n.published_at || undefined, links: n.links };
  }

  /**
   * POST /notices/send, then reloads the tenders. Resolves with one result per notice when all were accepted.
   * If any was refused, the batch stays fetched and the call rejects saying how many, so the person can send again.
   */
  var sending = /** @type {Promise<any> | null} */ (null);
  function sendNotices(/** @type {import('./types').Notice[]} */ notices) {
    if (sending) return sending;
    sending = call('send', function () {
      return api.post('/api/notices/send', { notices: notices.map(noticePayload) }).then(function (/** @type {{ results: Array<{ id: string, ok: boolean, tender: import('./types').Tender | null, error: import('./types').ErrorEnvelope | null }> }} */ body) {
        return reloadTenders().then(function () {
          var refused = body.results.filter(function (r) { return !r.ok; });
          if (!refused.length) {
            state.fetched = null;
            return body.results;
          }
          var first = /** @type {import('./types').ErrorEnvelope} */ (refused[0].error).error;
          var rid = first.request_id || '';
          /** @type {import('./types').CapturedError} */
          var failure = {
            status: 422,
            request_id: rid,
            body: { error: { code: 'TENDER_BATCH_INVALID', message: refused.length + ' of ' + notices.length + ' notices were not accepted: ' + first.message, field: first.field, retryable: false, request_id: rid || null } },
          };
          throw failure;
        });
      });
    });
    var current = sending;
    var done = function () { if (sending === current) sending = null; };
    current.then(done, done);
    return current;
  }

  /* ------------------------------------------------------- Preferences */

  function setPref(/** @type {string} */ key, /** @type {any} */ value) {
    state.prefs = Object.assign({}, state.prefs, { [key]: value });
    writeJson(PREFS_KEY, state.prefs);
    emit();
  }

  /** Remembers the tenders a person opened, newest first. */
  function touch(/** @type {string} */ id) {
    if (state.recent[0] === id) return;
    // Called while rendering, so it updates in place without notifying subscribers.
    state.recent = [id].concat(state.recent.filter(function (x) { return x !== id; })).slice(0, 5);
    writeJson(RECENT_KEY, state.recent);
  }

  /* ------------------------------------------------------------ Health */

  var SERVICES = [
    { id: 'detection', name: 'Detection', port: 8000, path: '/health' },
    { id: 'rag', name: 'Retrieval (RAG)', port: 8001, path: '/health' },
    { id: 'research', name: 'Research', port: 8002, path: '/health' },
    { id: 'proposal', name: 'Proposal', port: 8003, path: '/health' },
    { id: 'ingestion', name: 'Ingestion (TED, SAM.gov)', port: 8004, path: '/health' },
    { id: 'insights', name: 'Competitor & budget insights', port: 8006, path: '/health' },
    { id: 'n8n', name: 'n8n workflows', port: 5678, path: '/healthz' },
  ];

  /** GET /api/health: the proxy calls each service's own health route. Never rejects; an unreachable proxy shows every service down. */
  function checkHealth() {
    state.running = Object.assign({}, state.running, { health: true });
    emit();
    return api.get('/api/health').catch(function () { return []; }).then(function (/** @type {Array<{ id: string, up: boolean }>} */ rows) {
      var up = new Set(rows.filter(function (r) { return r.up; }).map(function (r) { return r.id; }));
      state.health = {
        checkedAt: new Date().toISOString(),
        services: SERVICES.map(function (sv) { return Object.assign({}, sv, { up: up.has(sv.id) }); }),
      };
      var next = Object.assign({}, state.running);
      delete next.health;
      state.running = next;
      emit();
      return state.health;
    });
  }

  /* ------------------------------------------------------------ Alerts */

  /**
   * What the services have reported that deserves a look, derived from their responses
   * (detection quality codes, research notes, deck kinds and bid warnings). No event feed needed.
   * @returns {Array<{ id: string, group: 'security' | 'attention' | 'info', title: string, detail: string, href: string }>}
   */
  function alerts() {
    var out = [];
    state.tenders.forEach(function (t) {
      var w = t.quality.warnings;
      if (w.indexOf('sanitized_chars') >= 0) out.push({ id: t.id + ':sanitized', group: 'security', title: 'Hidden characters removed from a tender', detail: t.title + ' · control or invisible direction characters were stripped at intake', href: 'tenders/' + t.id });
      if (w.indexOf('text_mostly_symbols') >= 0) out.push({ id: t.id + ':symbols', group: 'security', title: 'Tender text is mostly symbols', detail: t.title + ' · check the source before researching it', href: 'tenders/' + t.id });
      var dup = w.find(function (x) { return x.indexOf('possible_duplicate_of:') === 0; });
      if (dup) out.push({ id: t.id + ':dup', group: 'attention', title: 'Possible duplicate of ' + dup.slice(22), detail: t.title + ' · ' + copy.SOURCE[t.source], href: 'tenders/' + t.id });
      if (t.quality.missing_fields.length) out.push({ id: t.id + ':gaps', group: 'info', title: 'Accepted with gaps', detail: t.title + ' · missing ' + t.quality.missing_fields.join(', ').replace(/_/g, ' '), href: 'tenders/' + t.id });
      var r = state.research[t.id];
      if (r && r.status === 'unavailable' && r.notes && !/^Skipped/.test(r.notes)) out.push({ id: t.id + ':research', group: 'attention', title: 'Research run degraded', detail: t.issuer + ' · ' + r.notes, href: 'research/' + t.id });
      var p = state.proposals[t.id];
      if (p && p.kind === 'rejected') out.push({ id: t.id + ':rejected', group: 'attention', title: 'Deck refused by the validator', detail: t.title + ' · ' + p.warnings.length + ' issues, no files written', href: 'draft/' + t.id });
      if (p && p.warnings.some(function (x) { return /unsupported claim/.test(x) && p.kind !== 'rejected'; })) out.push({ id: t.id + ':claim', group: 'security', title: 'Unsupported claim in a deck', detail: t.title + ' · the grounding verifier could not support a sentence', href: 'review/' + t.id });
      if (p && p.kind === 'no_bid') out.push({ id: t.id + ':nobid', group: 'info', title: 'No-bid suggested', detail: t.title + ' · every requirement is below the 0.40 match line', href: 'draft/' + t.id });
    });
    return out;
  }

  /* --------------------------------------------------------------- RAG */

  /** POST /query */
  function query(/** @type {import('./types').QueryRequest} */ req) {
    var body = Object.assign({}, req);
    if (!body.doc_type) delete body.doc_type;
    return call('query', function () {
      return api.post('/api/query', body);
    });
  }

  /** GET /api/library/stats. Never rejects: until it succeeds `stats` stays null and the Library trees show no number. */
  function loadStats() {
    if (state.running.stats) return Promise.resolve();
    return call('stats', function () {
      return api.get('/api/library/stats').then(function (/** @type {import('./types').LibraryStats} */ counts) {
        state.stats = counts;
      });
    }).catch(function () {});
  }

  /** Records the RAG service returned for a requirement, per (tender, requirement); only successful searches are kept. */
  var searches = /** @type {Record<string, import('./types').QueryResult[]>} */ ({});
  var pending = /** @type {Record<string, Promise<import('./types').QueryResult[]>>} */ ({});

  function searchKey(/** @type {string} */ tenderId, /** @type {string} */ requirement) {
    return tenderId + '\u0000' + requirement;
  }

  function recordIn(/** @type {import('./types').QueryResult[]} */ rows, /** @type {string} */ recordId) {
    return rows.find(function (r) { return r.metadata && r.metadata.record_id === recordId; }) || null;
  }

  /** The knowledge-base record behind a requirement row, if it is already in memory: from the last generation, else from a search made for the requirement. */
  function hitFor(/** @type {string} */ tenderId, /** @type {string} */ requirement, /** @type {string | null} */ recordId) {
    if (!recordId) return null;
    if (state.hits[recordId]) return state.hits[recordId];
    var rows = searches[searchKey(tenderId, requirement)];
    return rows ? recordIn(rows, recordId) : null;
  }

  /**
   * Looks a record up by re-running the requirement through POST /query (top 5, as the deck's own match does).
   * Resolves with the hit, or null when the record is not among the results now. One search per (tender, requirement).
   * @returns {Promise<import('./types').QueryResult | null>}
   */
  function loadHit(/** @type {string} */ tenderId, /** @type {string} */ requirement, /** @type {string} */ recordId) {
    var known = hitFor(tenderId, requirement, recordId);
    if (known) return Promise.resolve(known);
    var key = searchKey(tenderId, requirement);
    if (!searches[key] && !pending[key]) {
      pending[key] = api.post('/api/query', { text: requirement, top_k: 5 }).then(
        function (/** @type {import('./types').QueryResult[]} */ rows) {
          delete pending[key];
          searches[key] = rows;
          return rows;
        },
        function (e) { delete pending[key]; throw e; }
      );
    }
    return (searches[key] ? Promise.resolve(searches[key]) : pending[key]).then(function (rows) { return recordIn(rows, recordId); });
  }

  /** Tenders whose title, buyer, id or country contain every word of `text`, case-insensitively, in list order. */
  function matchTenders(/** @type {import('./types').Tender[]} */ tenders, /** @type {string} */ text) {
    var words = text.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return [];
    return tenders.filter(function (t) {
      var hay = [t.title, t.issuer, t.id, t.issuer_country].filter(Boolean).join(' ').toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) >= 0; });
    });
  }

  return {
    now: new Date(),
    useStore: useStore,
    get: get,
    load: load,
    refresh: refresh,
    runPipeline: runPipeline,
    seePipeline: seePipeline,
    tally: tally,
    tender: tender,
    runResearch: runResearch,
    loadAudit: loadAudit,
    insightsOf: insightsOf,
    runInsights: runInsights,
    setPref: setPref,
    touch: touch,
    checkHealth: checkHealth,
    alerts: alerts,
    generateDeck: generateDeck,
    chooseSector: chooseSector,
    promptEdit: promptEdit,
    acceptProposal: acceptProposal,
    refuseProposal: refuseProposal,
    seedFeed: seedFeed,
    setTenderArchived: setTenderArchived,
    reviewOf: reviewOf,
    loadReview: loadReview,
    reloadReview: reloadReview,
    setSectionStatus: setSectionStatus,
    signOff: signOff,
    fetchNotices: fetchNotices,
    ingest: ingest,
    validateIngest: validateIngest,
    sendNotices: sendNotices,
    noticePayload: noticePayload,
    query: query,
    matchTenders: matchTenders,
    loadStats: loadStats,
    hitFor: hitFor,
    loadHit: loadHit,
    limits: { RAW_TEXT_MAX: RAW_TEXT_MAX, TITLE_MAX: TITLE_MAX, ISSUER_MAX: ISSUER_MAX, REQ_MAX_ITEMS: REQ_MAX_ITEMS, REQ_MAX_CHARS: REQ_MAX_CHARS },
  };
})();

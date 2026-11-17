// @ts-check
// Shared pieces built from window.Final: routing, the page frame, Future labels,
// the running figure for long calls, error notices and stage logic.
window.UIP = window.UIP || {};

window.UIP.ui = (function () {
  var F = window.Final;
  var h = React.createElement;
  var copy = window.UIP.copy;
  var store = window.UIP.store;
  var FUTURE = window.UIP.FUTURE;

  /* ------------------------------------------------------------- Routing */

  function parse() {
    var raw = window.location.hash.replace(/^#\/?/, '');
    var q = raw.indexOf('?');
    var path = (q >= 0 ? raw.slice(0, q) : raw).split('/').filter(Boolean).map(decodeURIComponent);
    var query = new URLSearchParams(q >= 0 ? raw.slice(q + 1) : '');
    return { screen: path[0] || 'overview', id: path[1] || null, sub: path[2] || null, query: query };
  }

  function useRoute() {
    var s = React.useState(parse);
    React.useEffect(function () {
      function on() { s[1](parse()); window.scrollTo(0, 0); }
      window.addEventListener('hashchange', on);
      return function () { window.removeEventListener('hashchange', on); };
    }, []);
    return s[0];
  }

  function go(/** @type {string} */ path) {
    window.location.hash = '#/' + path;
  }

  function href(/** @type {string} */ path) {
    return '#/' + path;
  }

  /* -------------------------------------------------------------- Format */

  function date(/** @type {string | null} */ iso, /** @type {Intl.DateTimeFormatOptions=} */ opts) {
    if (!iso) return '';
    return new Intl.DateTimeFormat(undefined, opts || { day: 'numeric', month: 'short' }).format(new Date(iso));
  }

  function count(/** @type {number} */ n, /** @type {string} */ one, /** @type {string=} */ many) {
    return new Intl.NumberFormat().format(n) + ' ' + (n === 1 ? one : many || one + 's');
  }

  function money(/** @type {number | null} */ amount, /** @type {string} */ symbol) {
    if (amount == null) return '';
    var code = { '€': 'EUR', '£': 'GBP', $: 'USD' }[symbol];
    return code
      ? new Intl.NumberFormat(undefined, { style: 'currency', currency: code, maximumFractionDigits: 0 }).format(amount)
      : symbol + ' ' + new Intl.NumberFormat().format(amount);
  }

  /* -------------------------------------------------------------- Future */

  /** The one label for a designed feature the backend cannot back yet. */
  function FutureTag(/** @type {{ reason: string }} */ p) {
    return h('span', { className: 'uip-future', title: p.reason },
      h(F.Chip, { tone: 'stale', icon: 'clock', size: 'sm' }, 'Future'),
      h('span', { className: 'fn-sr' }, ': ' + p.reason));
  }

  /** A designed button that stays visible but inert, saying it is coming. */
  function FutureButton(/** @type {{ label: string, icon?: string, reason: string, variant?: 'primary' | 'secondary' | 'tertiary' }} */ p) {
    return h(F.Button, { variant: p.variant || 'secondary', icon: p.icon, disabledReason: h(FutureTag, { reason: p.reason }) }, p.label);
  }

  function promptEditor(/** @type {{ tender: string, section: string }} */ ctx) {
    var dialog = document.createElement('dialog');
    dialog.className = 'uip-prompt-dialog';
    var title = document.createElement('h2');
    title.textContent = 'Prompt-edit section';
    var help = document.createElement('p');
    help.className = 'meta uip-muted';
    help.textContent = 'Describe the change without adding facts or changing scores.';
    var form = document.createElement('form');
    form.method = 'dialog';
    var input = document.createElement('textarea');
    input.rows = 5;
    input.required = true;
    input.placeholder = 'e.g. Make this more concise and direct.';
    var status = document.createElement('p');
    status.className = 'meta uip-muted';
    var cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.textContent = 'Cancel';
    var submit = document.createElement('button');
    submit.type = 'submit';
    submit.textContent = 'Apply edit';
    form.append(input, status, cancel, submit);
    dialog.append(title, help, form);
    document.body.appendChild(dialog);
    cancel.onclick = function () { dialog.close(); };
    dialog.onclose = function () { dialog.remove(); };
    form.onsubmit = function (event) {
      event.preventDefault();
      var prompt = input.value.trim();
      if (!prompt) return;
      submit.disabled = true;
      cancel.disabled = true;
      status.textContent = 'Applying edit…';
      store.promptEdit(ctx.tender, ctx.section, prompt).then(function () {
        status.textContent = 'Section updated.';
        window.setTimeout(function () { dialog.close(); }, 500);
      }, function () {
        submit.disabled = false;
        cancel.disabled = false;
        status.textContent = 'The edit could not be applied. Try again.';
      });
    };
    dialog.showModal();
    input.focus();
  }

  /** @param {{ tender?: string, section?: string, key?: string, title?: string }=} ctx The card each action belongs to. */
  function futureActions(ctx) {
    if (!ctx || !ctx.tender || !ctx.section || ['buyer', 'matrix', 'warnings'].indexOf(ctx.section) >= 0) return [];
    function promptEdit() {
      promptEditor({ tender: ctx.tender, section: ctx.section });
    }
    return [
      { id: 'prompt', icon: 'pen-line', label: 'Prompt-edit this section', onClick: promptEdit },
    ];
  }

  /* -------------------------------------------------------------- Runner */

  /** A running figure beside the icon of the phase: shown while a long call runs. */
  function Runner(/** @type {{ icon: string, label: string, detail?: string, ai?: boolean, world?: string }} */ p) {
    var line = { stroke: 'var(--ink)', strokeWidth: 2.25, strokeLinecap: 'round', strokeLinejoin: 'round', fill: 'none' };
    return h('div', { className: 'uip-runner', role: 'status', 'aria-live': 'polite', 'data-world': p.world },
      h('div', { className: 'uip-runner-scene', 'aria-hidden': 'true' },
        h('svg', { viewBox: '0 0 96 56', width: 120, height: 70, focusable: 'false' },
          h('line', { className: 'uip-runner-ground', x1: 2, y1: 51, x2: 94, y2: 51 }),
          h('g', { className: 'uip-runner-body' },
            h('g', { className: 'uip-runner-limb uip-runner-arm-b' }, h('polyline', Object.assign({ points: '44,19 50,25 56,21' }, line))),
            h('g', { className: 'uip-runner-limb uip-runner-leg-b' }, h('polyline', Object.assign({ points: '40,31 35,40 29,45' }, line))),
            h('line', Object.assign({ x1: 45, y1: 15, x2: 40, y2: 31 }, line)),
            h('circle', { cx: 46.5, cy: 9.5, r: 5, fill: 'var(--surface)', stroke: 'var(--ink)', strokeWidth: 2.25 }),
            h('g', { className: 'uip-runner-limb uip-runner-leg-a' }, h('polyline', Object.assign({ points: '40,31 47,39 45,49' }, line))),
            h('g', { className: 'uip-runner-limb uip-runner-arm-a' }, h('polyline', Object.assign({ points: '44,19 38,24 33,20' }, line))))),
        h('span', { className: 'uip-runner-goal' }, h(F.Icon, { name: p.icon, size: 22 }))),
      h('div', { className: 'uip-runner-text' },
        h('p', { className: 'heading uip-runner-label' }, p.ai ? h(F.Sparkle, { size: 14 }) : null, p.label),
        p.detail ? h('p', { className: 'meta uip-muted' }, p.detail) : null));
  }

  /* --------------------------------------------------------------- Error */

  /** The shared error envelope, said plainly, with its request id and a retry when retryable. */
  function ErrorNotice(/** @type {{ error: any, onRetry?: () => void }} */ p) {
    var e = p.error && p.error.body ? p.error.body.error : { code: 'INTERNAL', message: String(p.error), retryable: true, request_id: null };
    // The envelope's own message names what failed (which service, which key); the fixed copy only fills in when it has none.
    var message = typeof e.message === 'string' ? e.message.trim() : '';
    var text = message ? copy.sentence(message).replace(/\.?$/, '.') : copy.ERROR[e.code] || copy.ERROR.INTERNAL;
    return h('div', { className: 'uip-error', role: 'alert' },
      h(F.AdvisoryStrip, { tone: 'risk' }, text),
      h('p', { className: 'meta uip-muted uip-error-foot' },
        e.request_id ? h('span', null, 'Request ID ', h('code', { className: 'uip-code' }, e.request_id)) : null,
        e.retryable && p.onRetry ? h(F.Button, { variant: 'tertiary', size: 'sm', icon: 'refresh', onClick: p.onRetry }, 'Try Again') : null));
  }

  /** A review save that failed. A 409 means the deck was regenerated, so it offers to reload the deck and its review. */
  function ReviewError(/** @type {{ error: any, onReload: () => void, onRetry?: () => void }} */ p) {
    return h('div', { className: 'uip-stack' },
      h(ErrorNotice, { error: p.error, onRetry: p.onRetry }),
      p.error && p.error.status === 409 ? h('div', null, h(F.Button, { variant: 'secondary', size: 'sm', icon: 'refresh', onClick: p.onReload }, 'Reload Review')) : null);
  }

  /** Runs a store call, tracking its error for an ErrorNotice. */
  function useAction() {
    var err = React.useState(/** @type {any} */ (null));
    function run(/** @type {() => Promise<any>} */ fn) {
      err[1](null);
      return fn().catch(function (e) { err[1](e); throw e; });
    }
    return { error: err[0], clear: function () { err[1](null); }, run: run };
  }

  /* -------------------------------------------------------------- Stages */

  var STAGE_WORLD = { detect: 'peach', research: 'ice', match: 'sage', insights: 'ice', draft: 'mist', review: 'blush', export: 'stone' };

  /** The run's own status label, said the same way the Overview stage track says research's. */
  function insightsRunStatus(/** @type {import('./types').InsightsRun} */ run) {
    var status = run && run.insights && run.insights.status;
    return copy.INSIGHTS_STATUS[(status || 'unavailable')].label;
  }

  /** Where a tender is in the pipeline, from what the services hold for it. */
  function stagesFor(/** @type {import('./types').Tender} */ t, /** @type {import('./types').ProspectResearch | undefined} */ r, /** @type {import('./types').ProposalResult | undefined} */ p, /** @type {import('./types').InsightsRun | undefined} */ u) {
    var deck = /** @type {any} */ (p && p.deck);
    var rows = (deck && (deck.all_requirements && deck.all_requirements.length ? deck.all_requirements : deck.requirements)) || [];
    var covered = rows.filter(function (/** @type {any} */ x) { return x.score >= copy.PARTIAL_AT; }).length;
    var researchDone = !!r && (r.status === 'complete' || r.status === 'partial');
    var insightsDone = !!u && !!u.insights && u.insights.status === 'complete';
    var built = !!p && p.kind !== 'rejected';
    var list = [
      { id: 'detect', label: 'Detect', status: 'done', detail: 'Detected ' + date(t.detected_at) },
      { id: 'research', label: 'Research', status: researchDone ? 'done' : r ? 'skipped' : 'next', detail: r ? copy.RESEARCH_STATUS[r.status || 'unavailable'].label : 'Research not run' },
      { id: 'match', label: 'Match', status: p ? 'done' : 'next', detail: p ? covered + ' of ' + rows.length + ' covered' : 'Runs with the deck' },
      { id: 'insights', label: 'Insights', status: insightsDone ? 'done' : u ? 'skipped' : 'next', detail: u ? insightsRunStatus(u) : 'Market check not run' },
      { id: 'draft', label: 'Draft', status: built ? 'done' : 'next', detail: !p ? 'No deck yet' : p.kind === 'no_bid' ? 'No-bid suggested' : p.kind === 'rejected' ? 'Deck rejected' : 'Deck generated ' + date(p.generated_at) },
      { id: 'review', label: 'Review', status: 'next', detail: built && p ? count(p.warnings.length, 'warning') + ' to read' : 'After the deck' },
      { id: 'export', label: 'Export', status: built && p && p.artifacts.pptx ? 'done' : 'next', detail: built && p ? (p.artifacts.pdf ? 'PPTX · PDF · CSV' : 'PDF skipped') : 'No files yet' },
    ];
    var at = built ? 'review' : p || r ? 'draft' : 'research';
    list.forEach(function (s) { if (s.id === at) s.status = 'current'; });
    return list.map(function (s) { return Object.assign({ world: STAGE_WORLD[s.id] }, s); });
  }

  function currentStage(/** @type {Array<{ id: string, status: string }>} */ stages) {
    var c = stages.find(function (s) { return s.status === 'current'; });
    return c ? c.id : 'export';
  }

  /* --------------------------------------------------------------- Shell */

  var lastTender = /** @type {string | null} */ (null);
  /** The tender last opened, else the first one the services hold, else null. */
  function currentTender() {
    if (lastTender && store.tender(lastTender)) return lastTender;
    var first = store.get().tenders[0];
    return first ? first.id : null;
  }
  function rememberTender(/** @type {string | null} */ id) {
    if (id && store.tender(id)) {
      lastTender = id;
      store.touch(id);
    }
    return currentTender();
  }

  function rail(/** @type {import('./types').Tender[]} */ tenders) {
    var fresh = tenders.filter(function (t) { return t.status === 'new'; }).length;
    return [
      { id: 'overview', label: 'Overview', icon: 'grid' },
      { id: 'tenders', label: 'Tenders', icon: 'inbox', badge: fresh },
      { id: 'research', label: 'Research', icon: 'building' },
      { id: 'match', label: 'Match', icon: 'users' },
      { id: 'insights', label: 'Insights', icon: 'radar' },
      { id: 'draft', label: 'Draft', icon: 'pen-line' },
      { id: 'review', label: 'Review', icon: 'list-checks' },
      { id: 'export', label: 'Export', icon: 'presentation' },
      { id: 'library', label: 'Library', icon: 'library' },
    ];
  }
  var RAIL_FOOT = [
    { id: 'security', label: 'Security', icon: 'layers' },
    { id: 'settings', label: 'Settings', icon: 'sliders' },
  ];
  var PER_TENDER = { overview: 1, research: 1, match: 1, insights: 1, draft: 1, review: 1, export: 1 };

  function onRail(/** @type {string} */ id) {
    var open = currentTender();
    go(PER_TENDER[id] && open ? id + '/' + open : id);
  }

  /** The rail slides each item's name out beside it, so the native title tooltip would repeat it: the label moves to data-tip. */
  function Rail(/** @type {{ value: string }} */ p) {
    var s = store.useStore();
    var box = React.useRef(/** @type {HTMLDivElement | null} */ (null));
    React.useLayoutEffect(function () {
      box.current && box.current.querySelectorAll('.fn-rail-item[title]').forEach(function (el) {
        el.setAttribute('data-tip', el.getAttribute('title') || '');
        el.removeAttribute('title');
      });
    });
    return h('div', { ref: box, className: 'uip-rail-box' },
      h('a', { className: 'uip-brand', href: href('overview'), 'aria-label': 'OliveSoft RFP Intelligence: Overview' },
        h('img', { src: 'src/assets/olivesoft-symbol.svg', alt: '', width: 28, height: 36 })),
      h(F.NavRail, { items: rail(s.tenders), value: p.value, onChange: onRail, footer: RAIL_FOOT }));
  }

  /** The working-screen frame (ReviewPage): rail and main on the stage's faint tint. */
  function WorkPage(/** @type {{ world?: string, rail: string, chip?: string, kicker?: any, title: any, titleClass?: string, actions?: any, children?: any }} */ p) {
    var body = h('div', { className: 'uip-app' },
      h('div', { className: 'uip-rail' }, h(Rail, { value: p.rail })),
      h('main', { className: 'uip-main' },
        h('header', { className: 'uip-head' },
          h('div', null,
            p.kicker || p.chip ? h('p', { className: 'uip-kicker' }, p.chip ? h(F.Chip, { tone: p.world || 'neutral', dot: true, size: 'sm' }, p.chip) : null, p.kicker ? ' ' : null, p.kicker) : null,
            h('h1', { className: p.titleClass || 'title' }, p.title)),
          p.actions ? h('div', { className: 'uip-acts' }, p.actions) : null),
        p.children));
    return p.world
      ? h(F.World, { world: p.world, mode: 'tint', className: 'uip-stage' }, body)
      : h('div', { className: 'uip-stage uip-canvas' }, body);
  }

  /** The tender a per-tender screen is about, or a calm not-found panel. A `lead` goes above the panel and holds the filled action. */
  function needTender(/** @type {string | null} */ id, /** @type {string} */ rail, /** @type {string} */ world, /** @type {any=} */ lead) {
    var t = id ? store.tender(id) : null;
    if (t) return { tender: t, page: null };
    var s = store.get();
    return {
      tender: null,
      page: h(WorkPage, { world: world, rail: rail, title: s.tenders.length ? 'Tender not found' : 'No tenders yet' },
        lead || null,
        h(F.Card, null,
          h(F.EmptyState, {
            world: 'peach', illustration: 'tender',
            title: s.tenders.length ? 'Pick a Tender to Continue' : 'Bring In Your First Tender',
            action: { label: s.tenders.length ? 'Open Tenders' : 'Load Simulated Feed', icon: s.tenders.length ? 'inbox' : 'play', variant: lead ? 'secondary' : undefined, onClick: function () { go('tenders'); } },
          }, s.tenders.length
            ? 'This tender is not in the detection store. Open the tender list to choose one; its research, matches and deck follow it through every stage.'
            : 'Load the simulated feed, fetch a page of TED notices or add one by hand. Each tender gets a sector, its requirements and a data-quality check.'))),
    };
  }

  /** Applies a theme chosen at runtime. At load, index.html applies ?theme=, then the saved choice, then the system. */
  function applyTheme(/** @type {string} */ choice) {
    var dark = choice === 'dark' || (choice === 'system' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  }

  return {
    applyTheme: applyTheme,
    h: h,
    F: F,
    FUTURE: FUTURE,
    useRoute: useRoute,
    go: go,
    href: href,
    date: date,
    count: count,
    money: money,
    FutureTag: FutureTag,
    FutureButton: FutureButton,
    futureActions: futureActions,
    Runner: Runner,
    ErrorNotice: ErrorNotice,
    ReviewError: ReviewError,
    useAction: useAction,
    stagesFor: stagesFor,
    currentStage: currentStage,
    STAGE_WORLD: STAGE_WORLD,
    rememberTender: rememberTender,
    Rail: Rail,
    RAIL_FOOT: RAIL_FOOT,
    rail: rail,
    onRail: onRail,
    WorkPage: WorkPage,
    needTender: needTender,
  };
})();

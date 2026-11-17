// @ts-check
// The full n8n pipeline run: its stage track and outcome on Home's band, and the full-screen scene over every screen.
window.UIP = window.UIP || {};

window.UIP.pipeline = (function () {
  var ui = window.UIP.ui;
  var h = ui.h;
  var F = ui.F;
  var flow = window.UIP.flow;
  var store = window.UIP.store;

  var N8N = 'http://localhost:5678';

  function elapsed(/** @type {number} */ ms) {
    var m = Math.round(ms / 60000);
    return m < 1 ? 'under a minute' : ui.count(m, 'minute');
  }

  /** What a finished run added, from the store's counts before and after it, or null when it added nothing. */
  function added(/** @type {import('./types').PipelineRun} */ run) {
    var now = store.tally();
    if (now.tenders + now.researched + now.decks === run.before.tenders + run.before.researched + run.before.decks) return null;
    var parts = [
      ui.count(now.tenders - run.before.tenders, 'new tender'),
      ui.count(now.researched - run.before.researched, 'new research brief'),
      ui.count(now.decks - run.before.decks, 'new deck'),
    ];
    return 'Pipeline finished in ' + elapsed((run.stoppedAt || Date.now()) - run.startedAt) + ': ' + parts.join(' · ') + '.';
  }

  function link(/** @type {import('./types').PipelineRun | null} */ run) {
    return run && run.workflowId && run.id ? N8N + '/workflow/' + encodeURIComponent(run.workflowId) + '/executions/' + encodeURIComponent(run.id) : N8N;
  }

  /** Tenders whose deck the finished run generated, newest first: what waits for a person's review. */
  function fresh(/** @type {any} */ s) {
    var run = s.pipeline;
    if (!run || run.status !== 'success') return [];
    var made = s.tenders.filter(function (/** @type {import('./types').Tender} */ t) {
      var p = s.proposals[t.id];
      return !!p && p.kind !== 'rejected' && Date.parse(p.generated_at) >= run.startedAt;
    });
    return made
      .sort(function (/** @type {import('./types').Tender} */ a, /** @type {import('./types').Tender} */ b) { return Date.parse(s.proposals[b.id].generated_at) - Date.parse(s.proposals[a.id].generated_at); })
      .map(function (/** @type {import('./types').Tender} */ t) { return t.id; });
  }

  function reviewDue(/** @type {any} */ s) {
    return !!s.pipeline && !s.pipeline.seen && fresh(s).length > 0;
  }

  function openReview(/** @type {any} */ s) {
    store.seePipeline();
    ui.go('tenders?stage=review');
  }

  /** The stages across every tender. While n8n runs, the first unfinished stage is current; once decks land, Review is. */
  function stagesOf(/** @type {any} */ s) {
    var going = !!s.running.pipeline;
    var due = reviewDue(s);
    var counts = flow.PIPELINE.map(function (x) { return s.tenders.filter(function (/** @type {import('./types').Tender} */ t) { return x.has(s, t.id); }).length; });
    var current = going ? counts.findIndex(function (n) { return n < s.tenders.length; }) : -1;
    return flow.PIPELINE.map(function (x, i) {
      var waiting = due && x.id === 'review';
      return {
        id: x.id, label: x.label, world: x.world,
        status: i === current || waiting ? 'current' : counts[i] ? 'done' : 'next',
        detail: waiting ? ui.count(fresh(s).length, 'new deck') + ' to review' : counts[i] + ' ' + flow.PIPELINE_DETAIL[x.id],
      };
    });
  }

  function selectStage(/** @type {any} */ s, /** @type {string} */ id) {
    if (id === 'review' && reviewDue(s)) return openReview(s);
    ui.go(id === 'detect' ? 'tenders' : 'tenders?stage=' + id);
  }

  function Track() {
    var s = store.useStore();
    return h('div', { className: 'uip-pipe-track' + (reviewDue(s) ? ' uip-review-due' : '') },
      h(F.StageTrack, { label: 'Pipeline progress', stages: stagesOf(s), onSelect: function (/** @type {string} */ id) { selectStage(s, id); } }));
  }

  /** How the last run ended, or null while it runs or when it added nothing. */
  function Outcome(/** @type {{ onRetry: () => void }} */ p) {
    var s = store.useStore();
    var run = s.pipeline;
    if (!run || s.running.pipeline) return null;
    var made = run.status === 'success' ? added(run) : null;
    if (made) return h(F.AdvisoryStrip, { tone: 'good' }, made);
    if (run.status === 'unknown') return h(F.AdvisoryStrip, { tone: 'neutral' }, 'Stopped following the run after 20 minutes. Open n8n to see whether it finished.');
    if (run.status === 'error' && run.error) return h(ui.ErrorNotice, { error: run.error, onRetry: p.onRetry });
    return null;
  }

  function start() { store.runPipeline().catch(function () {}); }

  var STAGE_ICON = { detect: 'radar', research: 'building', match: 'users', draft: 'pen-line', review: 'list-checks', export: 'presentation' };

  /** The pipeline drawn large: one node per stage on a rail that fills as the run moves through them. */
  function Scene() {
    var s = store.useStore();
    var stages = stagesOf(s);
    var at = stages.findIndex(function (x) { return x.status === 'current'; });
    var reached = at >= 0 ? at : stages.reduce(function (last, x, i) { return x.status === 'done' ? i : last; }, 0);
    return h('ol', { className: 'uip-scene-track' + (reviewDue(s) ? ' uip-review-due' : ''), 'aria-label': 'Pipeline progress', style: { '--fill': reached / (stages.length - 1) } },
      stages.map(function (x, i) {
        return h('li', { key: x.id, className: 'uip-scene-stage', 'data-status': x.status, 'data-world': x.world, style: { '--i': i } },
          h('button', { type: 'button', className: 'uip-scene-node', 'aria-current': x.status === 'current' ? 'step' : undefined, onClick: function () { selectStage(s, x.id); } },
            h('span', { className: 'uip-scene-orb', 'aria-hidden': 'true' },
              h(F.Icon, { name: STAGE_ICON[x.id], size: 30 }),
              x.status === 'done' ? h('span', { className: 'uip-scene-tick' }, h(F.Icon, { name: 'check', size: 14, strokeWidth: 3 })) : null),
            h('span', { className: 'uip-scene-label' }, x.label),
            h('span', { className: 'uip-scene-detail' }, x.detail)));
      }));
  }

  /**
   * Takes over the screen while n8n runs, the app blurred behind it. Hiding it lasts until the run ends; then it comes
   * back to ask for the decks' review, and Review pulses here, on the band and in the rail until someone opens it or
   * closes this.
   */
  function Popout(/** @type {{ route: { screen: string } }} */ p) {
    var s = store.useStore();
    var run = s.pipeline;
    var going = !!s.running.pipeline;
    var due = reviewDue(s);
    var phase = run ? run.startedAt + (going ? ':running' : ':done') : '';
    var hidden = React.useState('');
    var panel = React.useRef(/** @type {HTMLDivElement | null} */ (null));
    var open = !!run && !(going ? hidden[0] === phase : run.seen);
    function close() {
      if (going) hidden[1](phase);
      else store.seePipeline();
    }
    React.useEffect(function () {
      if (due && p.route.screen === 'review') store.seePipeline();
    }, [due, p.route.screen]);
    React.useEffect(function () {
      document.documentElement.toggleAttribute('data-review-due', due);
    }, [due]);
    React.useEffect(function () {
      if (!open) return;
      if (panel.current) panel.current.focus();
      function onKey(/** @type {KeyboardEvent} */ e) { if (e.key === 'Escape') close(); }
      document.addEventListener('keydown', onKey);
      return function () { document.removeEventListener('keydown', onKey); };
    }, [open, phase]);
    if (!open || !run) return null;

    var title = going ? 'Running the full pipeline' : due ? 'Decks ready for review' : run.status === 'success' ? 'Pipeline finished' : run.status === 'error' ? 'Pipeline stopped' : 'Pipeline status unknown';
    var line = going
      ? run.tracked ? 'n8n is taking TED and SAM notices through every stage · started ' + elapsed(Date.now() - run.startedAt) + ' ago.' : 'Without an n8n API key the UI keeps refreshing for 20 minutes.'
      : due ? 'Each new deck needs a person to read its warnings and sign it off before export.' : null;
    return h('div', { className: 'uip-scene-veil', onClick: function (/** @type {MouseEvent} */ e) { if (e.target === e.currentTarget) close(); } },
      h('div', { className: 'uip-scene', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'uip-scene-title', tabIndex: -1, ref: panel },
        h('div', { className: 'uip-scene-head' },
          h('div', { className: 'uip-pipeline-text' },
            h('p', { className: 'fn-caption' }, 'Automated by n8n'),
            h('h2', { id: 'uip-scene-title', className: 'display uip-inline' }, going ? h(F.Icon, { name: 'refresh', size: 28, className: 'uip-spin' }) : due ? h(F.Sparkle, { size: 24 }) : null, title),
            line ? h('p', { className: 'uip-muted' }, line) : null),
          h(F.IconButton, { icon: 'x', label: going ? 'Hide until the run ends' : 'Close', onClick: close })),
        h(Scene),
        h('div', { 'aria-live': 'polite' }, h(Outcome, { onRetry: start })),
        h('div', { className: 'uip-scene-foot' },
          h('a', { className: 'fn-link', href: link(run), target: '_blank', rel: 'noopener noreferrer' }, 'Open n8n'),
          due
            ? h(F.Button, { variant: 'primary', size: 'lg', icon: 'list-checks', className: 'uip-review-cta', onClick: function () { openReview(s); } }, 'Review Decks')
            : h(F.Button, { variant: 'secondary', size: 'lg', onClick: close }, going ? 'Keep Working' : 'Close'))));
  }

  return { elapsed: elapsed, link: link, start: start, Track: Track, Outcome: Outcome, Popout: Popout };
})();

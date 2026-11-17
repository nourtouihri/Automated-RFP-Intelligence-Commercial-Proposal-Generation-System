// @ts-check
// OverviewPage: one tender on the world layer of its current stage.
window.UIP = window.UIP || {};
window.UIP.screens = window.UIP.screens || {};

window.UIP.screens.overview = (function () {
  var ui = window.UIP.ui;
  var h = ui.h;
  var F = ui.F;
  var copy = window.UIP.copy;
  var flow = window.UIP.flow;
  var store = window.UIP.store;
  var ev = window.UIP.evidence;
  var pipeline = window.UIP.pipeline;

  var SCOPES = [
    { label: 'tenders', world: 'peach' },
    { label: 'consultants', world: 'sage' },
    { label: 'past projects', world: 'sage' },
    { label: 'tools', world: 'sage' },
  ];
  var SHORTCUT = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K';

  /** The side tree: what you opened, what closes next, files, intake channels, the library. */
  function tree(/** @type {any} */ s) {
    /** @type {import('../types').Tender[]} */
    var tenders = s.tenders;
    function bySource(/** @type {string} */ src) {
      return tenders.filter(function (t) { return t.source === src; }).length;
    }
    function item(/** @type {import('../types').Tender} */ t) {
      return { id: t.id, label: t.title, icon: 'file-text', count: t.requirements.length };
    }
    var recent = s.recent.map(store.tender).filter(Boolean).slice(0, 4).map(item);
    var closing = tenders
      .filter(function (t) { return t.deadline && !t.quality.is_expired; })
      .sort(function (a, b) { return a.deadline < b.deadline ? -1 : 1; })
      .slice(0, 5).map(item);
    var docs = [];
    Object.keys(s.proposals).forEach(function (id) {
      var a = s.proposals[id].artifacts;
      if (a.pptx) docs.push({ id: 'doc:' + id, label: a.pptx, file: 'pptx' });
      if (a.csv) docs.push({ id: 'doc:' + id + ':csv', label: a.csv, file: 'csv' });
    });
    var on = s.prefs.sources;
    var sections = [];
    if (recent.length) sections.push({ id: 'recent', title: 'Recently opened', addLabel: 'Add Tender', items: recent });
    sections.push({ id: 'closing', title: 'Closing soon', addLabel: 'Add Tender', items: closing });
    if (docs.length) sections.push({ id: 'docs', title: 'Documents', count: docs.length, addLabel: 'Open Export', defaultOpen: false, items: docs.slice(0, 6) });
    sections.push({ id: 'integrations', title: 'Integrations', addLabel: 'Manage Sources', items: [
      on.simulated_feed !== false ? { id: 'src:simulated_feed', label: copy.SOURCE.simulated_feed, icon: 'inbox', count: bySource('simulated_feed') } : null,
      on.TED !== false ? { id: 'src:TED', label: copy.SOURCE.TED, icon: 'globe', count: bySource('TED') } : null,
      on.SAM !== false ? { id: 'fetch:SAM', label: 'SAM.gov (USA)', icon: 'radar' } : null,
      on.manual !== false ? { id: 'src:manual', label: copy.SOURCE.manual, icon: 'pen-line', count: bySource('manual') } : null,
      { id: 'set:sheet', label: 'Google Sheets via n8n', icon: 'grid' },
      { id: 'set:salesforce', label: 'Salesforce (future)', icon: 'briefcase' },
    ].filter(Boolean) });
    sections.push({ id: 'library', title: 'Library', addLabel: 'Search the Library', items: [
      { id: 'lib:cv', label: 'Consultants', icon: 'users', count: s.stats ? s.stats.cv : undefined },
      { id: 'lib:project', label: 'Past projects', icon: 'briefcase', count: s.stats ? s.stats.project : undefined },
      { id: 'lib:tool', label: 'Tools', icon: 'command', count: s.stats ? s.stats.tool : undefined },
    ] });
    return sections;
  }

  function onTree(/** @type {string} */ id) {
    if (id.indexOf('src:') === 0) return ui.go('tenders?source=' + id.slice(4));
    if (id.indexOf('lib:') === 0) return ui.go('library?type=' + id.slice(4));
    if (id.indexOf('set:') === 0) return ui.go('settings');
    if (id.indexOf('fetch:') === 0) return ui.go('tenders?panel=fetch&from=' + id.slice(6));
    if (id.indexOf('doc:') === 0) return ui.go('export/' + id.split(':')[1]);
    ui.go('overview/' + id);
  }

  function onAdd(/** @type {string} */ section) {
    ui.go(section === 'recent' || section === 'closing' ? 'tenders/new' : section === 'integrations' ? 'settings' : section === 'docs' ? 'export/' + ui.rememberTender(null) : 'library');
  }

  var STAGE_SCREEN = { detect: 'tenders', research: 'research', match: 'match', insights: 'insights', draft: 'draft', review: 'review', export: 'export' };

  /** Home's automation band: one click runs the whole pipeline in n8n, and the stages fill in as each one lands. */
  function PipelineBand() {
    var s = store.useStore();
    var run = s.pipeline;
    var going = !!s.running.pipeline;
    var line = !going
      ? 'Takes the first notices of a TED and a SAM page through every stage. Each screen updates as a stage finishes.'
      : run && run.tracked
        ? 'n8n is working through the notices · started ' + pipeline.elapsed(Date.now() - run.startedAt) + ' ago. The stages below update every few seconds.'
        : 'Running in n8n. Without an n8n API key the UI cannot tell when it ends, so it keeps refreshing for 20 minutes.';

    return h(F.Card, { elevated: true, className: 'uip-pipeline' },
      h('div', { className: 'uip-pipeline-head' },
        h('div', { className: 'uip-pipeline-text' },
          h('p', { className: 'fn-caption' }, 'Automated by n8n'),
          h('p', { className: 'heading' }, 'Fetch, detect, research, match and draft, end to end'),
          h('p', { className: 'meta uip-muted' }, line, ' ', h('a', { className: 'fn-link meta', href: pipeline.link(run), target: '_blank', rel: 'noopener noreferrer' }, 'Open n8n'))),
        h(F.Button, { variant: 'primary', size: 'lg', icon: 'play', loading: going, onClick: pipeline.start }, going ? 'Running in n8n…' : 'Run Full Pipeline')),
      going || run ? h(pipeline.Track) : null,
      h(pipeline.Outcome, { onRetry: pipeline.start }));
  }

  function BuyerCard(/** @type {{ t: import('../types').Tender, s: any, error: any }} */ p) {
    var t = p.t;
    var r = p.s.research[t.id];
    var body;
    if (flow.researching(p.s, t.id)) {
      body = h(ui.Runner, { icon: 'globe', world: 'ice', label: 'Researching ' + t.issuer + '…', detail: 'Searching the web, then reading each page in quarantine.' });
    } else if (p.error) {
      body = h(ui.ErrorNotice, { error: p.error });
    } else if (!r) {
      body = [
        h('div', { key: 't', className: 'uip-ov-tiles' }, h(F.Tile, { caption: t.issuer, world: 'ice', status: 'stale', statusLabel: 'research not run', onClick: function () { ui.go('research/' + t.id); } })),
        h(F.EmptyState, {
          key: 'e', world: 'ice', illustration: 'research', layout: 'inline', title: 'Research This Buyer',
          action: p.s.proposals[t.id] ? { label: 'Run Research', icon: 'play', variant: 'secondary', onClick: function () { store.runResearch(t.id, false).catch(function () {}); } } : undefined,
        },
          'Sector, estimated revenue, past projects and key partners appear here, each with the web sources it came from.'),
      ];
    } else {
      var st = copy.RESEARCH_STATUS[r.status || 'unavailable'];
      var conflict = !p.s.sectorChoices[t.id] && /Sector disagreement across sources: (.+)/.exec(r.notes);
      body = [
        h('div', { key: 't', className: 'uip-ov-tiles' }, h(F.Tile, { caption: t.issuer, world: 'ice', status: st.tone, statusLabel: st.label.toLowerCase(), onClick: function () { ui.go('research/' + t.id); } })),
        conflict
          ? h(F.AdvisoryStrip, { key: 'a', tone: 'risk' }, h('span', null, 'Sources disagree on ', h('b', null, 'sector'), ': ' + conflict[1].split('; ').join(' or ') + '.'))
          : r.status === 'unavailable' ? h(F.AdvisoryStrip, { key: 'a', tone: 'neutral' }, r.notes || 'No facts found.') : null,
        h('div', { key: 'c', className: 'uip-ov-chips' },
          r.sector ? h(F.Chip, { tone: 'ice' }, r.sector) : null,
          r.estimated_revenue ? h(F.Chip, null, r.estimated_revenue) : null,
          r.key_partners.slice(0, 2).map(function (k) { return h(F.Chip, { key: k }, k); })),
        r.status !== 'unavailable' ? h(F.Provenance, { key: 'v', author: { kind: 'ai' }, verb: 'Researched', time: r.completed_at || undefined, now: store.now, sources: r.sources.length, confidence: r.confidence, conflicts: conflict ? 1 : undefined, onSources: function () { ui.go('research/' + t.id); } }) : null,
      ];
    }
    return h(F.Card, { className: 'uip-ov-labelled fn-enter', style: { '--i': 1 } },
      h(F.FloatingLabel, { icon: 'building' }, 'Buyer research'), body);
  }

  function DraftCard(/** @type {{ t: import('../types').Tender, s: any, error: any }} */ p) {
    var t = p.t;
    var res = p.s.proposals[t.id];
    var deck = res && res.deck;
    var act = ui.useAction();
    var label = 'Deck';
    var body;
    if (flow.generating(p.s, t.id)) {
      body = h(ui.Runner, { icon: 'presentation', world: 'mist', ai: true, label: 'Generating the deck…', detail: 'Matching each requirement, writing each section, then checking every claim against its record.' });
    } else if (p.error) {
      body = h(ui.ErrorNotice, { error: p.error });
    } else if (!res) {
      body = h(F.EmptyState, { world: 'mist', illustration: 'draft', layout: 'inline', title: 'Draft the Proposal Deck' },
        'Cover letter, summary, approach, team, references and pricing, written from your matched records. Every claim cites its record.');
    } else if (res.kind === 'rejected') {
      body = [
        h(F.AdvisoryStrip, { key: 'a', tone: 'risk' }, 'No deck written — the validator found ' + ui.count(res.warnings.length, 'issue') + '.'),
        h('ul', { key: 'l', className: 'uip-list ui' }, res.warnings.map(function (w) { return h('li', { key: w }, copy.sentence(w.replace(/^no deck written: /, ''))); })),
      ];
    } else if (res.kind === 'no_bid') {
      label = 'Deck · ' + copy.NO_BID_SECTIONS.length + ' sections';
      body = [
        h(F.AdvisoryStrip, { key: 'a', tone: 'neutral' }, 'No-bid suggested — every requirement is below the 0.40 match line.'),
        h('p', { key: 'p', className: 'uip-ov-a' }, deck.recommendation),
        h(F.Provenance, { key: 'v', author: { kind: 'ai' }, verb: 'Composed', time: res.generated_at, now: store.now, onSources: function () { ui.go('match/' + t.id); }, sources: flow.rowsOf(res).length }),
      ];
    } else {
      label = 'Deck · ' + copy.SECTIONS.length + ' sections';
      var pillar = deck.summary.pillars[0];
      body = h('div', null,
        h('div', { className: 'uip-ov-ehead' },
          h('h2', { className: 'uip-ov-q' }, pillar.title),
          h(F.StatusSelect, { value: store.reviewOf(t.id).sections.summary || 'draft', options: copy.REVIEW_STATUS, label: 'Review status of ' + pillar.title, onChange: function (/** @type {any} */ v) { act.run(function () { return store.setSectionStatus(t.id, 'summary', v); }).catch(function () {}); } })),
        act.error ? h(ui.ReviewError, { error: act.error, onReload: function () { act.run(function () { return store.reloadReview(t.id); }).catch(function () {}); } }) : null,
        h('p', { className: 'uip-ov-a' }, pillar.body, ev.citations(t.id, pillar.evidence)),
        h(F.Provenance, { author: { kind: 'ai' }, time: res.generated_at, now: store.now, sources: pillar.evidence.length, onSources: function () { ui.go('review/' + t.id + '?section=summary'); } }));
    }
    return h(F.Card, { className: 'uip-ov-labelled fn-enter', style: { '--i': 2 } },
      h(F.FloatingLabel, { icon: 'pen-line' }, label), body);
  }

  function MatchCard(/** @type {{ t: import('../types').Tender, s: any }} */ p) {
    var t = p.t;
    var res = p.s.proposals[t.id];
    var rows = flow.rowsOf(res);
    var covered = rows.filter(function (/** @type {any} */ r) { return r.score >= copy.PARTIAL_AT; }).length;
    var body = rows.length
      ? h('div', { className: 'uip-ov-rows' },
        rows.slice(0, 3).map(function (/** @type {import('../types').RequirementRow} */ r) {
          return h(F.ListRow, {
            key: r.requirement, variant: 'flat', title: r.requirement,
            subtitle: r.evidence_id ? r.evidence + ' · ' + r.evidence_id : 'Nothing retrieved for this requirement',
            trailing: h('span', { className: 'uip-trail' }, h('span', { className: 'meta uip-muted uip-num' }, copy.matchScore(r.score)), h(F.Fit, { level: copy.fitLevel(r.score) })),
            onClick: function () { ui.go('match/' + t.id); },
          });
        }),
        rows.length > 3 ? h('div', { className: 'uip-ov-more' }, h(F.Button, { variant: 'tertiary', size: 'sm', iconEnd: 'arrow-right', onClick: function () { ui.go('match/' + t.id); } }, 'See All ' + rows.length + ' Requirements')) : null)
      : h(F.EmptyState, { world: 'sage', illustration: 'match', layout: 'inline', title: 'Match Your People to This Tender' },
        'Each of the ' + ui.count(t.requirements.length, 'requirement') + ' gets its best consultant or past project, rated strong, partial or gap, with the record behind every pick.');
    return h(F.Card, { className: 'uip-ov-labelled uip-ov-wide fn-enter', style: { '--i': 3 } },
      h(F.FloatingLabel, { icon: 'users' }, rows.length ? 'Match · ' + covered + ' of ' + rows.length + ' covered' : 'Match'), body);
  }

  function Overview(/** @type {{ route: any }} */ p) {
    var s = store.useStore();
    var err = React.useState(/** @type {any} */ (null));
    var search = React.useRef(/** @type {HTMLDivElement | null} */ (null));
    React.useEffect(function () { if (!s.stats) store.loadStats(); }, []);
    React.useEffect(function () {
      function onKey(/** @type {KeyboardEvent} */ e) {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
          e.preventDefault();
          var input = search.current && search.current.querySelector('input');
          if (input) input.focus();
        }
      }
      document.addEventListener('keydown', onKey);
      return function () { document.removeEventListener('keydown', onKey); };
    }, []);
    var id = ui.rememberTender(p.route.id || (s.tenders[0] && s.tenders[0].id));
    var need = ui.needTender(id, 'overview', 'peach', h(PipelineBand));
    if (!need.tender) return need.page;
    var t = need.tender;
    var stages = ui.stagesFor(t, s.research[t.id], s.proposals[t.id], s.insights[t.id]);
    var world = ui.STAGE_WORLD[ui.currentStage(stages)];
    var action = flow.primary(s, t, { onError: function (e, on) { err[1](Object.assign({}, e, { on: on })); } });
    var failedOn = err[0] && err[0].on;

    return h(F.World, { world: world, className: 'uip-ov-stage' },
      h(F.Glass, { radius: "none", className: 'uip-ov-app fn-enter' },
        h(ui.Rail, { value: 'overview' }),
        h('div', { className: 'uip-ov-side' }, h(F.TreeNav, { sections: tree(s), value: t.id, onChange: onTree, onAdd: onAdd })),
        h('main', { className: 'uip-ov-main' },
          h(PipelineBand),
          h('div', { className: 'uip-ov-top', ref: search },
            h(F.SearchBar, { scopes: SCOPES, shortcut: SHORTCUT, onSubmit: function (/** @type {string} */ q) { ui.go('library?q=' + encodeURIComponent(q)); } }),
            h(F.IconButton, { icon: 'bell', label: 'Alerts', variant: 'glass', badge: store.alerts().length, onClick: function () { ui.go('alerts'); } })),
          h('header', { className: 'uip-ov-head' },
            h('div', null,
              h('p', { className: 'uip-ov-kicker' }, flow.kicker(t)),
              h('h1', { className: 'display' }, t.title)),
            h(F.Button, {
              variant: 'secondary', size: 'lg', icon: action.icon, loading: action.loading, disabledReason: action.disabledReason,
              onClick: function () {
                err[1](null);
                if (action.onClick) action.onClick();
              },
            }, action.label)),
          h(F.StageTrack, { stages: stages, onSelect: function (/** @type {string} */ sid) { ui.go(STAGE_SCREEN[sid] + '/' + t.id); } }),
          h('div', { className: 'uip-ov-panels' },
            h(BuyerCard, { t: t, s: s, error: failedOn === 'research' ? err[0] : null }),
            h(DraftCard, { t: t, s: s, error: failedOn === 'deck' ? err[0] : null }),
            h(MatchCard, { t: t, s: s })))));
  }

  return Overview;
})();

// @ts-check
// Research stage (ice): what the quarantined research agent found about the buyer.
window.UIP = window.UIP || {};
window.UIP.screens = window.UIP.screens || {};

window.UIP.screens.research = (function () {
  var ui = window.UIP.ui;
  var h = ui.h;
  var F = ui.F;
  var copy = window.UIP.copy;
  var store = window.UIP.store;
  var flow = window.UIP.flow;

  // research/runner.py: the disagreement note, optionally followed by a degraded-run note.
  var SECTOR_CONFLICT = /Sector disagreement across sources: (.*?)(?= Search provider| Refresh produced|$)/;

  function host(/** @type {string} */ url) {
    try { return new URL(url).hostname.replace(/^www\./, ''); } catch (e) { return url; }
  }

  function safeHref(/** @type {string} */ url) {
    try { var u = new URL(url); return u.protocol === 'http:' || u.protocol === 'https:' ? u.href : null; } catch (e) { return null; }
  }

  function Cite(/** @type {{ url: string }} */ p) {
    var href = safeHref(p.url);
    var label = host(p.url);
    return href
      ? h('a', { className: 'fn-link meta', href: href, target: '_blank', rel: 'noopener noreferrer', title: p.url }, label)
      : h('span', { className: 'meta uip-muted', title: p.url }, label);
  }

  function sourceOf(/** @type {import('../types').ProspectResearch} */ r, /** @type {string} */ category, /** @type {string | null} */ value) {
    if (value == null) return null;
    var key = value.trim().toLowerCase();
    var hit = (r.facts || []).filter(function (f) { return f.category === category && f.value.trim().toLowerCase() === key; })[0];
    return hit ? hit.source : null;
  }

  function Cited(/** @type {{ source: string | null, children: any }} */ p) {
    return h('span', { className: 'uip-inline' }, p.children, p.source ? h(Cite, { url: p.source }) : null);
  }

  function FactRow(/** @type {{ label: string, children: any }} */ p) {
    return h('div', { className: 'uip-fact' }, h('dt', { className: 'meta uip-muted' }, p.label), h('dd', { className: 'body' }, p.children));
  }

  var AUDIT_STEP = {
    research_run_start: 'Run started',
    search: 'Page read',
    entity_mismatch: 'Page refused: another organisation',
    search_rate_limited: 'Search paused',
    search_auth_error: 'Search refused',
    'Search Error': 'Search failed',
    research_evidence_preserved: 'Earlier evidence kept',
    missing_fields: 'All fields found',
  };

  /** What a step was about, taken from its params. Always plain text. */
  function auditSubject(/** @type {import('../types').AuditEntry} */ e) {
    var v = e.params.query || e.params.url || e.params.issuer;
    return typeof v === 'string' ? v : '';
  }

  /** The audit trail of the latest run, read on demand. Page text is untrusted, so every part of it is rendered as text. */
  function AuditTrail(/** @type {{ id: string }} */ p) {
    var act = ui.useAction();
    var log = React.useState(/** @type {import('../types').ResearchAudit | null} */ (null));
    var busy = React.useState(false);

    function load() {
      busy[1](true);
      act.run(function () { return store.loadAudit(p.id); })
        .then(function (res) { log[1](res); })
        .catch(function () {})
        .then(function () { busy[1](false); });
    }

    var entries = log[0] ? log[0].entries : [];
    return h(F.Card, { density: 'compact', className: 'uip-queue' },
      h('p', { className: 'fn-caption uip-cap' }, 'How this was researched'),
      act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: load }) : null,
      !log[0] ? h('div', { className: 'uip-pad' },
        h(F.Button, { variant: 'secondary', size: 'sm', icon: 'history', disabled: busy[0], onClick: load }, busy[0] ? 'Loading…' : 'Show the Steps')) : null,
      log[0] && !entries.length ? h('p', { className: 'meta uip-muted uip-pad' }, 'No steps were recorded for the latest run.') : null,
      entries.map(function (e, i) {
        var subject = auditSubject(e);
        return h(F.ListRow, {
          key: i + e.hash,
          variant: 'flat',
          title: AUDIT_STEP[e.tool] || e.tool,
          subtitle: [subject, e.content].filter(Boolean).join(' · '),
        });
      }));
  }

  function Research(/** @type {{ route: any }} */ p) {
    var s = store.useStore();
    var act = ui.useAction();
    var skip = React.useState(/** @type {import('../types').ProspectResearch | null} */ (null));
    var need = ui.needTender(p.route.id || ui.rememberTender(null), 'research', 'ice');
    if (!need.tender) return need.page;
    var t = need.tender;
    ui.rememberTender(t.id);
    var stored = s.research[t.id];
    var r = stored || skip[0];
    var running = flow.researching(s, t.id);

    function run(/** @type {boolean} */ force) {
      skip[1](null);
      act.run(function () { return store.runResearch(t.id, force); })
        .then(function (res) { if (!store.get().research[t.id]) skip[1](res); })
        .catch(function () {});
    }

    var skipped = !!r && r.status === 'unavailable' && /^Skipped: tender deadline has passed/.test(r.notes);
    var conflict = r && !s.sectorChoices[t.id] && SECTOR_CONFLICT.exec(r.notes);
    var actions = [];
    if (r && !running) actions.push(h(F.Button, { key: 'f', icon: 'refresh', onClick: function () { run(true); } }, skipped ? 'Research Anyway' : 'Re-run Research'));
    if (r && !running) actions.push(h(F.Button, { key: 'p', variant: 'primary', icon: 'arrow-right', onClick: function () { ui.go('draft/' + t.id); } }, 'Continue to Draft'));

    var body;
    if (running) {
      body = h(F.Card, null, h(ui.Runner, { icon: 'globe', world: 'ice', label: 'Researching ' + t.issuer + '…', detail: 'Searching the web, then reading each page in quarantine. Closed tenders are skipped to save budget.' }));
    } else if (!r) {
      body = h(F.Card, null,
        act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: function () { run(false); } }) : null,
        h(F.EmptyState, { world: 'ice', illustration: 'research', title: 'Research This Buyer', action: { label: 'Run Research', icon: 'play', onClick: function () { run(false); } } },
          'Four facts about ' + t.issuer + ' — sector, estimated revenue, past projects and key partners — each backed by the web sources it came from and a confidence level.'));
    } else {
      var st = copy.RESEARCH_STATUS[r.status || 'unavailable'];
      var otherNotes = r.notes.replace(SECTOR_CONFLICT, '').trim();
      body = h('div', { className: 'uip-cols' },
        h(F.Card, { density: 'compact', className: 'uip-pad uip-stack-s' },
          h('p', { className: 'fn-caption' }, 'Run'),
          h('div', { className: 'uip-chips' },
            h(F.Status, { status: st.tone, size: 'sm' }, st.label),
            h(F.Chip, { size: 'sm' }, copy.CONFIDENCE[r.confidence])),
          h('dl', { className: 'uip-facts' },
            h('div', { className: 'uip-fact' }, h('dt', { className: 'meta uip-muted' }, 'Sources'), h('dd', { className: 'ui-strong uip-num' }, r.sources.length)),
            r.completed_at ? h('div', { className: 'uip-fact' }, h('dt', { className: 'meta uip-muted' }, 'Finished'), h('dd', { className: 'ui-strong' }, ui.date(r.completed_at, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }))) : null),
          h(F.AdvisoryStrip, { tone: 'neutral', icon: 'layers' },
            h('span', null, 'Read in quarantine; confidence counts distinct sources, not the model’s opinion. ', h('a', { className: 'fn-link', href: ui.href('security') }, 'How research stays safe')))),
        h('div', { className: 'uip-stack' },
          act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: function () { run(true); } }) : null,
          skipped ? h(F.AdvisoryStrip, { tone: 'neutral' }, 'Skipped — the deadline has passed, so no search budget was spent. Research anyway if you still plan to bid.') : null,
          !skipped && r.status === 'unavailable' ? h(F.AdvisoryStrip, { tone: 'neutral' }, otherNotes || 'No facts found on the web for this buyer.') : null,
          conflict ? h(F.ConflictCard, {
            field: 'sector',
            sides: /** @type {any} */ (conflict[1].split('; ').slice(0, 2).map(function (v) {
              var src = sourceOf(r, 'sector', v);
              return { source: src ? host(src) : 'Web research', file: 'url', passage: h('span', null, 'Sector reported as ', h('strong', null, v), '.', src ? h('span', null, ' ', h(Cite, { url: src })) : null), useLabel: 'Use This Value' };
            })),
            resolved: s.sectorChoices[t.id] ? conflict[1].split('; ').slice(0, 2).indexOf(s.sectorChoices[t.id]) : null,
            onResolve: function (index) {
              var value = conflict[1].split('; ').slice(0, 2)[index];
              if (value) store.chooseSector(t.id, value);
            },
          }) : null,
          conflict && !s.sectorChoices[t.id] ? h('p', { className: 'meta uip-muted' }, 'Choose the sector to use for the rest of this pipeline.') : null,
          r.status !== 'unavailable' ? h(F.EntryCard, {
            title: 'What we know about ' + r.issuer,
            provenance: { author: { kind: 'ai' }, verb: 'Researched', time: r.completed_at || undefined, now: store.now, sources: r.sources.length, confidence: r.confidence, conflicts: conflict ? 1 : undefined },
          },
            h('dl', { className: 'uip-facts uip-facts--wide' },
              h(FactRow, { label: 'Sector' }, r.sector ? h(Cited, { source: sourceOf(r, 'sector', r.sector) }, r.sector) : 'Not found'),
              h(FactRow, { label: 'Estimated revenue' }, r.estimated_revenue ? h(Cited, { source: sourceOf(r, 'estimated_revenue', r.estimated_revenue) }, r.estimated_revenue) : 'Not found'),
              h(FactRow, { label: 'Past projects' }, r.past_projects.length ? h('div', { className: 'uip-chips' }, r.past_projects.map(function (x) { return h(Cited, { key: x, source: sourceOf(r, 'past_projects', x) }, h(F.Chip, null, x)); })) : 'Not found'),
              h(FactRow, { label: 'Key partners' }, r.key_partners.length ? h('div', { className: 'uip-chips' }, r.key_partners.map(function (x) { return h(Cited, { key: x, source: sourceOf(r, 'key_partners', x) }, h(F.Chip, { tone: 'ice' }, x)); })) : 'Not found'))) : null,
          h(AuditTrail, { id: t.id, key: t.id + (r.completed_at || '') }),
          r.sources.length ? h(F.Card, { density: 'compact', className: 'uip-queue' },
            h('p', { className: 'fn-caption uip-cap' }, 'Sources · ' + r.sources.length),
            r.sources.map(function (u) {
              return h(F.ListRow, { key: u, variant: 'flat', file: 'url', title: host(u), subtitle: u });
            })) : null));
    }

    return h(ui.WorkPage, { world: 'ice', rail: 'research', chip: 'Research', kicker: t.title, title: t.issuer, actions: actions }, body);
  }

  return Research;
})();

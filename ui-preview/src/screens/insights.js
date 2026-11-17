// @ts-check
// Insights stage (ice): the Competitor & Budget Insights agent's market view of
// the tender — what the market paid for comparable work, who bids against you,
// and how to position against them. A should-cost check, not the deck's price.
window.UIP = window.UIP || {};
window.UIP.screens = window.UIP.screens || {};

window.UIP.screens.insights = (function () {
  var ui = window.UIP.ui;
  var h = ui.h;
  var F = ui.F;
  var copy = window.UIP.copy;
  var store = window.UIP.store;
  var flow = window.UIP.flow;

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

  function FactRow(/** @type {{ label: string, children: any }} */ p) {
    return h('div', { className: 'uip-fact' }, h('dt', { className: 'meta uip-muted' }, p.label), h('dd', { className: 'body' }, p.children));
  }

  function Bullets(/** @type {{ items: string[] }} */ p) {
    return h('ul', { className: 'uip-stack-xs' },
      p.items.map(function (/** @type {string} */ x) { return h('li', { key: x, className: 'meta' }, x.trim()); }));
  }

  /** ListRow badges never render raw urls: the host name, linked like research's cites. */
  function Evidence(/** @type {{ urls: string[] }} */ p) {
    return h('span', { className: 'uip-chips' }, p.urls.map(function (/** @type {string} */ u) { return h(Cite, { key: u, url: u }); }));
  }

  /** The agent's turns, straight from the run payload: no second fetch (compare research's on-demand audit). */
  function TraceCard(/** @type {{ run: import('../types').InsightsRun }} */ p) {
    var steps = p.run.trace || [];
    return h(F.Card, { density: 'compact', className: 'uip-queue' },
      h('p', { className: 'fn-caption uip-cap' }, 'How this was researched'),
      !steps.length ? h('p', { className: 'meta uip-muted uip-pad' }, 'No steps were recorded for this run.') : null,
      steps.map(function (/** @type {import('../types').InsightTraceStep} */ e, /** @type {number} */ i) {
        var label = (e.auto ? 'auto: ' : '') + e.action;
        var detail = [e.thought, e.error ? 'error: ' + e.error : null].filter(Boolean).join(' · ');
        return h(F.ListRow, {
          key: i,
          variant: 'flat',
          title: e.turn != null ? 'Turn ' + e.turn + ' · ' + label : label,
          subtitle: detail || (typeof e.result_preview === 'string' ? e.result_preview.slice(0, 200) : ''),
          trailing: e.error ? h(F.Chip, { tone: 'risk', size: 'sm' }, 'Failed') : e.ok === false ? h(F.Chip, { tone: 'stale', size: 'sm' }, 'Error') : null,
        });
      }));
  }

  function Insights(/** @type {{ route: any }} */ p) {
    var s = store.useStore();
    var act = ui.useAction();
    var stale = React.useState(/** @type {import('../types').InsightsRun | null} */ (null));
    var need = ui.needTender(p.route.id || ui.rememberTender(null), 'insights', 'ice');
    if (!need.tender) return need.page;
    var t = need.tender;
    ui.rememberTender(t.id);
    var stored = s.insights[t.id];
    var run = stored || stale[0];
    var running = !!s.running['insights:' + t.id];
    var r = run ? run.insights : null;
    var budget = r && r.budget;

    function runIt() {
      stale[1](null);
      act.run(function () { return store.runInsights(t.id); }).catch(function () {});
    }

    var actions = [];
    if (r && !running) {
      actions.push(h(F.Button, { key: 'f', icon: 'refresh', onClick: runIt }, 'Re-run Insights'));
      actions.push(h(F.Button, { key: 'p', variant: 'primary', icon: 'arrow-right', onClick: function () { ui.go('draft/' + t.id); } }, 'Continue to Draft'));
    }

    var body;
    if (running) {
      body = h(F.Card, null, h(ui.Runner, { icon: 'radar', world: 'ice', label: 'Sizing up the competition…', detail: 'Searching live sources for comparable budgets and rival bids, then reading every page in quarantine.' }));
    } else if (!r) {
      body = h(F.Card, null,
        act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: runIt }) : null,
        h(F.EmptyState, { world: 'ice', illustration: 'search', title: 'Read the Market First', action: { label: 'Run Insights', icon: 'play', onClick: runIt } },
          'Live sources give this tender a should-cost envelope (TND), the competitors likely to bid against you, and how to position against them — before a day rate is set in the deck.'));
    } else {
      var st = copy.INSIGHTS_STATUS[r.status || 'unavailable'];
      var b = budget;
      var priced = b && b.method !== 'none' && b.likely != null;
      body = h('div', { className: 'uip-cols' },
        h(F.Card, { density: 'compact', className: 'uip-pad uip-stack-s' },
          h('p', { className: 'fn-caption' }, 'Run'),
          h('div', { className: 'uip-chips' },
            h(F.Status, { status: st.tone, size: 'sm' }, st.label),
            h(F.Chip, { size: 'sm' }, copy.CONFIDENCE[r.confidence])),
          h('dl', { className: 'uip-facts' },
            h('div', { className: 'uip-fact' }, h('dt', { className: 'meta uip-muted' }, 'Competitors'), h('dd', { className: 'ui-strong uip-num' }, r.competitors.length)),
            h('div', { className: 'uip-fact' }, h('dt', { className: 'meta uip-muted' }, 'Sources'), h('dd', { className: 'ui-strong uip-num' }, b.sources.length)),
            run.stop_reason ? h('div', { className: 'uip-fact' }, h('dt', { className: 'meta uip-muted' }, 'Stop reason'), h('dd', { className: 'ui-strong' }, run.stop_reason)) : null),
          h(F.AdvisoryStrip, { tone: 'neutral', icon: 'scale' },
            h('span', null, 'A should-cost check against the market. The deck’s price is still the proposal service’s cost model — compare, don’t copy. ', h('a', { className: 'fn-link', href: ui.href('security') }, 'How insights stay safe')))),
        h('div', { className: 'uip-stack' },
          act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: runIt }) : null,
          b ? h(F.EntryCard, {
            title: 'Budget envelope · ' + t.issuer,
            provenance: { author: { kind: 'ai' }, verb: 'Estimated', time: run.created_at || r.completed_at || undefined, now: store.now, sources: b.sources.length, confidence: b.confidence },
          },
            h('dl', { className: 'uip-facts uip-facts--wide' },
              h(FactRow, { label: 'Envelope' }, priced
                ? h('span', { className: 'ui-strong uip-num' }, ui.money(b.min, b.currency) + ' – ' + ui.money(b.max, b.currency) + ' (likely ' + ui.money(b.likely, b.currency) + ')')
                : 'No numbers: the sources never gave an amount to price from'),
              h(FactRow, { label: 'Method' }, copy.BUDGET_METHOD[b.method]),
              b.assumptions.length ? h(FactRow, { label: 'Assumptions' }, h(Bullets, { items: b.assumptions })) : null,
              b.sources.length ? h(FactRow, { label: 'Evidence' }, h(Evidence, { urls: b.sources.slice(0, 4) })) : null)) : null,
          r.notes ? h(F.AdvisoryStrip, { tone: r.status === 'unavailable' ? 'stale' : 'neutral' }, r.notes) : null,
          h(F.Card, { density: 'compact', className: 'uip-queue' },
            h('p', { className: 'fn-caption uip-cap' }, r.competitors.length ? 'Likely Competitors · ' + r.competitors.length : 'Likely Competitors'),
            !r.competitors.length ? h('p', { className: 'meta uip-muted uip-pad' }, 'No competitor the sources could evidence. Better nobody named than a name invented.') : null,
            r.competitors.map(function (/** @type {import('../types').Competitor} */ c) {
              var parts = [c.why_likely,
                c.strengths.length ? 'Strengths: ' + c.strengths.join('; ') : null,
                c.weaknesses.length ? 'Weaknesses: ' + c.weaknesses.join('; ') : null].filter(Boolean).join(' · ');
              return h(F.ListRow, { key: c.name, variant: 'flat', title: c.name, subtitle: parts,
                trailing: c.evidence.length ? h(Evidence, { urls: c.evidence.slice(0, 2) }) : null });
            })),
          r.positioning && (r.positioning.recommended_strategy || r.positioning.risks.length || r.positioning.olivesoft_advantages.length) ? h(F.EntryCard, {
            title: 'Positioning for OliveSoft',
            provenance: { author: { kind: 'ai' }, verb: 'Drafted', time: r.completed_at || undefined, now: store.now, confidence: r.confidence },
          },
            h('dl', { className: 'uip-facts uip-facts--wide' },
              r.positioning.olivesoft_advantages.length ? h(FactRow, { label: 'Advantages' }, h(Bullets, { items: r.positioning.olivesoft_advantages })) : null,
              r.positioning.risks.length ? h(FactRow, { label: 'Risks' }, h(Bullets, { items: r.positioning.risks })) : null,
              r.positioning.recommended_strategy ? h(FactRow, { label: 'Strategy' }, r.positioning.recommended_strategy) : null,
              r.positioning.differentiators_to_emphasize.length ? h(FactRow, { label: 'Emphasize' }, h('div', { className: 'uip-chips' }, r.positioning.differentiators_to_emphasize.map(function (/** @type {string} */ x) { return h(F.Chip, { tone: 'ice' }, x); }))) : null)) : null,
          h(TraceCard, { run: run, key: String(run.run_id) })));
    }

    return h(ui.WorkPage, { world: 'ice', rail: 'insights', chip: 'Insights', kicker: t.title, title: t.issuer, actions: actions }, body);
  }

  return Insights;
})();

// @ts-check
// Match stage (sage): every requirement scored against the knowledge base, plus team and references.
window.UIP = window.UIP || {};
window.UIP.screens = window.UIP.screens || {};

window.UIP.screens.match = (function () {
  var ui = window.UIP.ui;
  var h = ui.h;
  var F = ui.F;
  var copy = window.UIP.copy;
  var store = window.UIP.store;
  var flow = window.UIP.flow;
  var ev = window.UIP.evidence;

  function Score(/** @type {{ score: number }} */ p) {
    return h('span', { className: 'uip-trail' },
      h('span', { className: 'meta uip-muted uip-num' }, copy.matchScore(p.score)),
      h(F.Fit, { level: copy.fitLevel(p.score) }));
  }

  var DELIVERED = {
    true: h(F.Status, { status: 'good', size: 'sm' }, 'Delivered'),
    false: h(F.Status, { status: 'stale', size: 'sm' }, 'Not delivered'),
    null: h(F.Status, { status: 'stale', size: 'sm' }, 'Unverified'),
  };

  function Match(/** @type {{ route: any }} */ p) {
    var s = store.useStore();
    var open = React.useState(/** @type {string | null} */ (null));
    var act = ui.useAction();
    var need = ui.needTender(p.route.id || ui.rememberTender(null), 'match', 'sage');
    if (!need.tender) return need.page;
    var t = need.tender;
    ui.rememberTender(t.id);
    var res = s.proposals[t.id];
    var rows = flow.rowsOf(res);
    var deck = /** @type {any} */ (res && res.deck);
    var inDeck = new Set(((deck && deck.requirements) || []).map(function (/** @type {any} */ r) { return r.requirement; }));
    var n = { strong: 0, partial: 0, gap: 0 };
    rows.forEach(function (/** @type {any} */ r) { n[copy.fitLevel(r.score)] += 1; });
    var generating = flow.generating(s, t.id);
    var blocked = flow.deckBlocked(t);
    function generate() { act.run(function () { return store.generateDeck(t.id); }).catch(function () {}); }

    var actions = [];
    if (res && res.artifacts.csv) actions.push(h(F.Button, { key: 'c', icon: 'download', onClick: function () { ui.go('export/' + t.id); } }, 'Download Matrix CSV'));
    if (res) actions.push(h(F.Button, { key: 'p', variant: 'primary', icon: 'list-checks', onClick: function () { ui.go('review/' + t.id + '?section=matrix'); } }, 'Review Deck'));
    else if (blocked && !generating) actions.push(h(F.Button, { key: 'p', variant: 'primary', icon: 'play', disabledReason: blocked }, 'Generate Deck'));

    var body;
    if (generating) {
      body = h(F.Card, null, h(ui.Runner, { icon: 'users', world: 'sage', ai: true, label: 'Matching requirements…', detail: 'One knowledge-base search per requirement; the deck is written once every row is scored.' }));
    } else if (!rows.length) {
      body = h(F.Card, null,
        act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: generate }) : null,
        h(F.EmptyState, { world: 'sage', illustration: 'match', title: 'Match Your People to This Tender', action: blocked ? undefined : { label: 'Generate Deck', icon: 'play', onClick: generate } },
          'Each of the ' + ui.count(t.requirements.length, 'requirement') + ' gets its best consultant or past project, rated strong, partial or gap from its match score, with the record behind every pick.'));
    } else {
      var hidden = rows.length - inDeck.size;
      body = h('div', { className: 'uip-cols' },
        h(F.Card, { density: 'compact', className: 'uip-pad uip-stack-s' },
          h('p', { className: 'fn-caption' }, 'Coverage'),
          h('div', { className: 'uip-stack-s' },
            h('span', { className: 'uip-trail uip-spread' }, h(F.Fit, { level: 'strong' }), h('span', { className: 'fn-count' }, n.strong)),
            h('span', { className: 'uip-trail uip-spread' }, h(F.Fit, { level: 'partial' }), h('span', { className: 'fn-count' }, n.partial)),
            h('span', { className: 'uip-trail uip-spread' }, h(F.Fit, { level: 'gap' }), h('span', { className: 'fn-count' }, n.gap))),
          h('p', { className: 'meta uip-muted' }, 'Strong from 0.55, partial from 0.40. Scores are retrieval similarity, set by code — never by the model.'),
          hidden > 0 ? h(F.AdvisoryStrip, { tone: 'neutral' }, inDeck.size + ' of ' + rows.length + ' shown in the deck; all are in the CSV.') : null,
          res && res.kind === 'no_bid' ? h(F.AdvisoryStrip, { tone: 'neutral' }, 'No-bid suggested — every requirement is below 0.40.') : null),
        h('div', { className: 'uip-stack' },
          h(F.Card, { density: 'compact', className: 'uip-queue' },
            h('p', { className: 'fn-caption uip-cap' }, 'Requirements · ' + rows.length),
            rows.map(function (/** @type {import('../types').RequirementRow} */ r) {
              var isOpen = open[0] === r.requirement;
              return h('div', { key: r.requirement, className: 'uip-stack-s' },
                h(F.ListRow, {
                  variant: 'flat', active: isOpen, title: r.requirement,
                  subtitle: r.evidence_id ? [r.evidence, r.evidence_id, inDeck.has(r.requirement) ? 'in the deck' : 'CSV only'].filter(Boolean).join(' · ') : 'Nothing retrieved for this requirement',
                  trailing: h(Score, { score: r.score }),
                  onClick: r.evidence_id ? function () { open[1](isOpen ? null : r.requirement); } : undefined,
                }),
                isOpen && r.evidence_id ? h(ev.Record, { key: r.evidence_id, tenderId: t.id, requirement: r.requirement, recordId: r.evidence_id, onClose: function () { open[1](null); } }) : null);
            })),
          deck && deck.team ? h(F.Card, { className: 'uip-ov-labelled' },
            h(F.FloatingLabel, { icon: 'users' }, 'Team'),
            h('div', { className: 'uip-ov-rows' }, deck.team.map(function (/** @type {any} */ c) {
              return c.cv_id
                ? h(F.ListRow, { key: c.cv_id, variant: 'flat', title: c.name + ' · ' + c.role, subtitle: [c.years != null ? ui.count(c.years, 'year') : null, c.skills, c.cv_id].filter(Boolean).join(' · '), trailing: h(Score, { score: c.score }) })
                : h(F.ListRow, { key: c.name + c.role, variant: 'flat', title: 'To be staffed', subtitle: c.role, trailing: h(F.Status, { status: 'stale', size: 'sm' }, 'Placeholder') });
            }))) : null,
          deck && deck.references ? h(F.Card, { className: 'uip-ov-labelled' },
            h(F.FloatingLabel, { icon: 'briefcase' }, 'References'),
            h('div', { className: 'uip-ov-rows' }, deck.references.map(function (/** @type {any} */ x) {
              return x.project_id
                ? h(F.ListRow, { key: x.project_id, variant: 'flat', title: x.title, subtitle: [x.summary, x.sector, x.project_id].join(' · '), trailing: h('span', { className: 'uip-trail' }, DELIVERED[String(x.delivered)], h(Score, { score: x.score })) })
                : h(F.ListRow, { key: x.title, variant: 'flat', title: 'No matching project yet', subtitle: x.summary, trailing: h(F.Status, { status: 'stale', size: 'sm' }, 'Placeholder') });
            }))) : null));
    }

    var covered = n.strong + n.partial;
    return h(ui.WorkPage, {
      world: 'sage', rail: 'match', chip: 'Match', title: 'Requirements Matrix',
      kicker: t.title + (rows.length ? ' · ' + covered + ' of ' + rows.length + ' covered' : ''),
      actions: actions,
    }, body);
  }

  return Match;
})();

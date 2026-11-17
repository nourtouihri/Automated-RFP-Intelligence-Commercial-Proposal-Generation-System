// @ts-check
// Draft (mist), Review (blush) and Export (stone): the generated deck, read section by
// section with its warnings, then downloaded.
window.UIP = window.UIP || {};
window.UIP.screens = window.UIP.screens || {};

(function () {
  var ui = window.UIP.ui;
  var h = ui.h;
  var F = ui.F;
  var copy = window.UIP.copy;
  var store = window.UIP.store;
  var api = window.UIP.api;
  var flow = window.UIP.flow;
  var ev = window.UIP.evidence;

  function sectionsOf(/** @type {import('../types').ProposalResult} */ res) {
    return res.kind === 'no_bid' ? copy.NO_BID_SECTIONS : copy.SECTIONS;
  }

  function warningsFor(/** @type {import('../types').ProposalResult} */ res, /** @type {string} */ id) {
    if (id === 'warnings') return [];
    return res.warnings.filter(function (w) { return copy.warningSections(w).indexOf(id) >= 0; });
  }

  function estimatedFor(/** @type {any} */ deck, /** @type {string} */ id) {
    var prefix = id === 'buyer' ? 'buyer.' : id === 'investment' ? 'investment.' : null;
    return prefix ? (deck.estimated || []).filter(function (/** @type {string} */ p) { return p.indexOf(prefix) === 0; }) : [];
  }

  /** @returns {{ status: 'good' | 'risk' | 'stale', label: string }} */
  function sectionStatus(/** @type {import('../types').ProposalResult} */ res, /** @type {string} */ id) {
    var ws = warningsFor(res, id);
    if (ws.some(function (w) { return copy.warningTone(w) === 'risk'; })) return { status: 'risk', label: 'Unsupported claim' };
    if (ws.length) return { status: 'stale', label: ui.count(ws.length, 'warning') };
    if (estimatedFor(res.deck, id).length) return { status: 'stale', label: 'Estimated' };
    return { status: 'good', label: 'No warnings' };
  }

  function Score(/** @type {{ score: number }} */ p) {
    return h('span', { className: 'uip-trail' }, h('span', { className: 'meta uip-muted uip-num' }, copy.matchScore(p.score)), h(F.Fit, { level: copy.fitLevel(p.score) }));
  }

  function Estimated() {
    return h(F.Chip, { tone: 'stale', size: 'sm' }, 'Estimated');
  }

  /* ------------------------------------------------------ Deck parameters */

  /** The proposal Config fields a sales manager would change (proposal/config.py), read back from the deck. */
  function paramsFrom(/** @type {any} */ deck) {
    var first = deck.investment.lines.find(function (/** @type {any} */ l) { return l.days && l.amount; });
    var phase = first && deck.approach.phases.find(function (/** @type {any} */ ph) { return ph.name === first.workstream; });
    return {
      signatory_name: deck.signatory.name,
      signatory_role: deck.signatory.role,
      signatory_contact: deck.signatory.contact,
      letter_title: deck.letter.title,
      currency: deck.investment.currency,
      day_rate: first ? String(first.amount / first.days) : '650',
      team_size: first && phase ? String(first.days / (phase.weeks * 5)) : '2',
      investment_note: deck.investment.note,
    };
  }

  /** Every value the panel holds, typed as the proposal service's DeckSettings expects: the service keeps no
   * settings between runs, so a rebuild must restate earlier overrides or it silently reverts them. */
  function settingsFrom(/** @type {Record<string, string>} */ f) {
    /** @type {Record<string, string | number>} */
    var out = {};
    Object.keys(f).forEach(function (k) {
      out[k] = k === 'day_rate' || k === 'team_size' ? Number(f[k]) : f[k];
    });
    return out;
  }

  /**
   * The agent's should-cost envelope against the deck's previewed total. Display
   * only: the price stays the proposal service's cost model — the insights agent
   * is a market check, and the strip never edits a field.
   */
  function MarketEnvelope(/** @type {{ tender: string, total: number | null, currency: string }} */ p) {
    var run = store.get().insights[p.tender];
    if (!run || !run.insights) return null;
    var b = run.insights.budget;
    if (!b || b.method === 'none' || b.min == null || b.max == null || b.likely == null)
      return h(F.AdvisoryStrip, { tone: 'neutral', icon: 'radar' },
        h('span', null, 'Market check: no amount the sources could price, so the envelope is blank. The deck’s cost model stands alone. ',
          h('a', { className: 'fn-link', href: ui.href('insights/' + p.tender) }, 'Open Insights')));
    var m = ui.money(b.min, b.currency) + ' – ' + ui.money(b.max, b.currency) + (b.likely != null ? ' (likely ' + ui.money(b.likely, b.currency) + ')' : '');
    var below = p.total != null && p.total < b.min;
    var above = p.total != null && p.total > b.max;
    var tone = p.total == null ? 'neutral' : above ? 'risk' : below ? 'stale' : 'good';
    var read = p.total == null ? null
      : above ? 'The previewed total sits above it.'
      : below ? 'The previewed total sits below it — the work may be underpriced.'
      : 'The previewed total sits inside it.';
    return h(F.AdvisoryStrip, { tone: tone, icon: 'radar' },
      h('span', null, 'Market envelope ', h('strong', null, m), read ? ' ' + read : '',
        ' · ', h('a', { className: 'fn-link', href: ui.href('insights/' + p.tender) }, 'Open Insights')));
  }

  /**
   * Sales-facing deck settings with the new pricing previewed by the service's own formula.
   * `draft` keeps the edits across the Draft screen swapping this panel for the progress view while a rebuild runs.
   */
  function DeckParameters(/** @type {{ deck: any, stamp: string, draft: { current: any }, blocked?: string | null, tender?: string, onRebuild: (settings: Record<string, string | number>) => void }} */ p) {
    var initial = React.useMemo(function () { return paramsFrom(p.deck); }, [p.deck]);
    var kept = p.draft.current && p.draft.current.stamp === p.stamp ? p.draft.current.values : null;
    var v = React.useState(kept || initial);
    var f = v[0];
    function keep(/** @type {any} */ next) {
      p.draft.current = { stamp: p.stamp, values: next };
      v[1](next);
    }
    function set(/** @type {string} */ k) {
      return function (/** @type {any} */ e) { keep(Object.assign({}, f, { [k]: e.target.value })); };
    }
    var rate = Number(f.day_rate);
    var size = Number(f.team_size);
    var rateErr = !(rate > 0) ? 'Enter a day rate above 0.' : null;
    var sizeErr = !Number.isInteger(size) || size < 1 ? 'Enter a whole team size of 1 or more.' : null;
    var phases = p.deck.approach.phases;
    var days = phases.reduce(function (/** @type {number} */ n, /** @type {any} */ ph) { return n + ph.weeks * 5 * (sizeErr ? 0 : size); }, 0);
    var changed = JSON.stringify(f) !== JSON.stringify(initial);
    var emptied = Object.keys(f).some(function (k) { return k !== 'day_rate' && k !== 'team_size' && !String(f[k]).trim(); });
    var reason = p.blocked || (rateErr || sizeErr ? 'Fix the highlighted fields first.' : emptied ? 'Text fields cannot be empty.' : !changed ? 'Change a parameter first.' : undefined);
    return h(F.Card, { density: 'compact', className: 'uip-pad uip-stack-s' },
      h('p', { className: 'fn-caption' }, 'Deck parameters'),
      h(F.TextField, { label: 'Signatory', value: f.signatory_name, onChange: set('signatory_name') }),
      h(F.TextField, { label: 'Signatory role', value: f.signatory_role, onChange: set('signatory_role') }),
      h(F.TextField, { label: 'Contact', value: f.signatory_contact, onChange: set('signatory_contact') }),
      h(F.TextField, { label: 'Letter title', value: f.letter_title, onChange: set('letter_title') }),
      h(F.TextField, { label: 'Day rate (' + f.currency + ')', type: 'number', min: 1, value: f.day_rate, onChange: set('day_rate'), error: rateErr, hint: 'Blended rate per consultant day.' }),
      h(F.TextField, { label: 'Team size', type: 'number', min: 1, value: f.team_size, onChange: set('team_size'), error: sizeErr, hint: 'Consultants staffed on every phase.' }),
      h(F.TextField, { label: 'Pricing note', multiline: true, rows: 2, value: f.investment_note, onChange: set('investment_note') }),
      !rateErr && !sizeErr ? h(F.AdvisoryStrip, { tone: changed ? 'neutral' : 'good', icon: 'scale' },
        h('span', null, (changed ? 'New total ' : 'Total ') , h('strong', null, ui.money(days * rate, f.currency)), ' · ' + ui.count(days, 'day') + ' · weeks × 5 days × team × rate')) : null,
      p.tender ? h(MarketEnvelope, { tender: p.tender, total: !rateErr && !sizeErr ? days * rate : null, currency: f.currency }) : null,
      h('div', { className: 'uip-acts' },
        changed ? h(F.Button, { variant: 'tertiary', size: 'sm', onClick: function () { keep(initial); } }, 'Reset') : null,
        h(F.Button, { size: 'sm', icon: 'refresh', disabledReason: reason, onClick: function () { p.onRebuild(settingsFrom(f)); } }, 'Rebuild Deck')));
  }

  /* --------------------------------------------------------------- Draft */

  /** Which checks ran on this deck, said plainly. A result stored before the service reported them says so. */
  function Checks(/** @type {{ checks: import('../types').ProposalResult['checks'], warnings: string[] }} */ p) {
    var c = p.checks;
    var known = !!c && Object.keys(c).length > 0;
    var unjudged = p.warnings.filter(function (w) { return /^grounding check unavailable/.test(w); }).length;
    var verifierOff = unjudged
      ? 'A second model was set up but could not judge ' + ui.count(unjudged, 'section') + ', so those claims were not rated against their sources. See the grounding check warnings below.'
      : 'No second model was set, so no claim was rated against its source. The operator sets PROPOSAL_VERIFIER_LLM_MODEL.';
    function row(/** @type {string} */ title, /** @type {boolean | undefined} */ ran, /** @type {string} */ did, /** @type {string} */ didNot, /** @type {string=} */ offLabel) {
      return h(F.ListRow, { key: title, variant: 'flat', title: title, subtitle: ran ? did : didNot,
        trailing: ran ? h(F.Status, { status: 'good', size: 'sm' }, 'Ran') : h(F.Chip, { tone: 'stale', size: 'sm' }, offLabel || 'Did not run') });
    }
    return h(F.Card, { density: 'compact', className: 'uip-queue' },
      h('p', { className: 'fn-caption uip-cap' }, 'Checks'),
      known
        ? [
          row('Grounding verifier', c && c.verifier, 'A second model rated each claim against the source it cites.', verifierOff, unjudged ? 'Could not judge' : undefined),
          row('Strict claim check', c && c.claim_check, 'Every written sentence was checked for claims its sources do not contain.', 'Off. Turn it on in Settings, then regenerate.'),
        ]
        : h('p', { className: 'ui uip-muted uip-pad' }, 'This deck was generated before checks were recorded. Regenerate it to see which ran.'));
  }

  /** The machine's work, one row per step in the order it ran; hidden for a result stored before the trace. */
  function HowWritten(/** @type {{ trace: import('../types').ProposalResult['trace'] }} */ p) {
    var steps = p.trace || [];
    if (!steps.length) return null;
    var order = [];
    steps.forEach(function (s) { if (order.indexOf(s.step) < 0) order.push(s.step); });
    return h(F.Card, { density: 'compact', className: 'uip-queue' },
      h('p', { className: 'fn-caption uip-cap' }, 'How this deck was written'),
      order.map(function (name) {
        var mine = steps.filter(function (s) { return s.step === name; });
        var bad = mine.some(function (s) { return copy.traceNeedsLook(s); });
        return h(F.ListRow, { key: name, variant: 'flat', title: copy.STEP_LABEL[name] || copy.sentence(name) + (mine.length > 1 ? ' · ' + mine.length : ''), subtitle: copy.traceLine(mine),
          trailing: bad ? h(F.Chip, { tone: 'stale', size: 'sm' }, 'Check it') : h(F.Status, { status: 'good', size: 'sm' }, 'Done') });
      }));
  }

  function Draft(/** @type {{ route: any }} */ p) {
    var s = store.useStore();
    var act = ui.useAction();
    var panel = React.useRef(/** @type {any} */ (null));
    var rebuilding = React.useRef(/** @type {Record<string, string | number> | null} */ (null));
    /* The tender whose deck came from Generate Anyway: its rebuilds stay forced, or the gate would turn the proposal back into a no-bid. */
    var forcedFor = React.useRef(/** @type {string | null} */ (null));
    var need = ui.needTender(p.route.id || ui.rememberTender(null), 'draft', 'mist');
    if (!need.tender) return need.page;
    var t = need.tender;
    ui.rememberTender(t.id);
    var res = s.proposals[t.id];
    var generating = flow.generating(s, t.id);
    var blocked = flow.deckBlocked(t);
    function generate() { rebuilding.current = null; forcedFor.current = null; act.run(function () { return store.generateDeck(t.id); }).catch(function () {}); }
    function rebuild(/** @type {Record<string, string | number>} */ settings) {
      rebuilding.current = settings;
      var options = forcedFor.current === t.id ? { settings: settings, force_bid: true } : { settings: settings };
      act.run(function () { return store.generateDeck(t.id, options); }).catch(function () {});
    }
    function generateAnyway() {
      rebuilding.current = null;
      forcedFor.current = t.id;
      act.run(function () { return store.generateDeck(t.id, { force_bid: true }); }).catch(function () {});
    }
    function retry() { if (rebuilding.current) rebuild(rebuilding.current); else if (forcedFor.current === t.id) generateAnyway(); else generate(); }

    var actions = [];
    if (res && !generating) actions.push(h(F.Button, { key: 'g', icon: 'refresh', disabledReason: blocked, onClick: generate }, 'Regenerate Deck'));
    if (res && res.kind !== 'rejected' && !generating) actions.push(h(F.Button, { key: 'p', variant: 'primary', icon: 'list-checks', onClick: function () { ui.go('review/' + t.id); } }, 'Review Deck'));
    else if (res && !generating) actions = [h(F.Button, { key: 'p', variant: 'primary', icon: 'refresh', disabledReason: blocked, onClick: generate }, 'Regenerate Deck')];
    else if (!res && blocked) actions.push(h(F.Button, { key: 'p', variant: 'primary', icon: 'play', disabledReason: blocked }, 'Generate Deck'));

    var body;
    if (generating) {
      body = h(F.Card, null, h(ui.Runner, { icon: 'presentation', world: 'mist', ai: true, label: 'Generating the deck…', detail: 'Matching each requirement, writing each section, then checking every claim against the records it cites.' }));
    } else if (!res) {
      body = h(F.Card, null,
        act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: retry }) : null,
        h(F.EmptyState, { world: 'mist', illustration: 'draft', title: 'Draft the Proposal Deck', action: blocked ? undefined : { label: 'Generate Deck', icon: 'play', onClick: generate } },
          'Cover letter, executive summary, buyer needs, approach, team, references and pricing, written from your matched records. Every claim cites the record it rests on.'));
    } else if (res.kind === 'rejected') {
      body = h(F.Card, { className: 'uip-stack-s' },
        act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: retry }) : null,
        h(F.AdvisoryStrip, { tone: 'risk' }, 'No deck written — the validator found ' + ui.count(res.warnings.length, 'issue') + '.'),
        res.warnings.map(function (w) {
          return h(F.ListRow, { key: w, variant: 'flat', title: copy.sentence(w.replace(/^no deck written: /, '')), trailing: h(F.Status, { status: 'risk', size: 'sm' }, 'Blocked') });
        }),
        h('p', { className: 'meta uip-muted' }, 'The validator refuses a deck with overflowing text, overlapping shapes, off-palette colours or a citation to a record that was not retrieved. Nothing is stored until it passes.'));
    } else {
      var deck = /** @type {any} */ (res.deck);
      body = h('div', { className: 'uip-cols' },
        h(F.Card, { density: 'compact', className: 'uip-pad uip-stack-s' },
          h('p', { className: 'fn-caption' }, 'Deck'),
          h('p', { className: 'heading' }, deck.meta.headline),
          h('p', { className: 'ui uip-muted' }, deck.meta.subtitle),
          h('div', { className: 'uip-chips' },
            res.kind === 'no_bid' ? h(F.Status, { status: 'stale', size: 'sm' }, 'No-bid suggested') : h(F.Status, { status: 'good', size: 'sm' }, 'Proposal'),
            deck.meta.sample ? h(F.Chip, { size: 'sm' }, 'Sample') : null),
          h('dl', { className: 'uip-facts' },
            h('div', { className: 'uip-fact' }, h('dt', { className: 'meta uip-muted' }, 'Reference'), h('dd', { className: 'ui-strong' }, deck.meta.reference)),
            h('div', { className: 'uip-fact' }, h('dt', { className: 'meta uip-muted' }, 'Dated'), h('dd', { className: 'ui-strong' }, deck.meta.date))),
          h(F.Provenance, { author: { kind: 'ai' }, verb: res.kind === 'no_bid' ? 'Composed' : 'Drafted', time: res.generated_at, now: store.now }),
          res.kind === 'proposal' ? h(DeckParameters, { key: res.generated_at, stamp: res.generated_at, deck: deck, draft: panel, blocked: blocked, tender: t.id, onRebuild: rebuild }) : null),
        h('div', { className: 'uip-stack' },
          act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: retry }) : null,
          res.kind === 'no_bid' ? h(F.EntryCard, { title: 'Recommendation', advisory: { tone: 'neutral', text: 'No-bid suggested — every requirement is below the 0.40 match line.' } },
            h('p', null, deck.recommendation),
            h('p', { className: 'meta uip-muted' }, 'Generating anyway writes a full proposal from the weak matches. It spends model budget, and the warnings will say how thin the evidence is.'),
            h(F.Button, { icon: 'play', disabledReason: blocked, onClick: generateAnyway }, 'Generate Anyway')) : null,
          res.kind === 'proposal' ? h(Checks, { checks: res.checks, warnings: res.warnings }) : null,
          h(HowWritten, { trace: res.trace }),
          h(F.Card, { density: 'compact', className: 'uip-queue' },
            h('p', { className: 'fn-caption uip-cap' }, 'Sections · ' + sectionsOf(res).length),
            sectionsOf(res).map(function (sec) {
              var st = sectionStatus(res, sec.id);
              return h(F.ListRow, { key: sec.id, variant: 'flat', href: ui.href('review/' + t.id + '?section=' + sec.id), title: sec.label, trailing: h(F.Status, { status: st.status, size: 'sm' }, st.label) });
            })),
          h(F.Card, { density: 'compact', className: 'uip-pad uip-stack-s' },
            h('p', { className: 'fn-caption' }, 'Bid warnings · ' + res.warnings.length),
            res.warnings.length
              ? res.warnings.map(function (w) { return h(F.AdvisoryStrip, { key: w, tone: copy.warningTone(w) }, copy.sentence(w)); })
              : h(F.Status, { status: 'good', size: 'sm' }, 'No bid warnings'))));
    }

    return h(ui.WorkPage, { world: 'mist', rail: 'draft', chip: 'Draft', kicker: t.title, title: 'Proposal Deck', actions: actions }, body);
  }

  /* -------------------------------------------------------------- Review */

  /** Shared props for every entry: the section's review status is live, section actions are not backed yet. */
  function entryFor(/** @type {string} */ tid, /** @type {string} */ section, /** @type {(status: any) => void} */ onStatus) {
    var status = store.reviewOf(tid).sections[section] || 'draft';
    return function (/** @type {any} */ extra) {
      var ctx = { tender: tid, section: section, key: extra && extra.key, title: extra && extra.title };
      return Object.assign({ status: status, statusOptions: copy.REVIEW_STATUS, onStatusChange: onStatus, actions: ui.futureActions(ctx) }, extra);
    };
  }

  function aiProv(/** @type {import('../types').ProposalResult} */ res, /** @type {number=} */ sources) {
    return { author: { kind: 'ai' }, time: res.generated_at, now: store.now, sources: sources };
  }

  function byCode() {
    return h('p', { className: 'meta uip-muted' }, 'Filled by code from the records and scores — the model does not write these values.');
  }

  /** @param {string} tid @param {import('../types').ProposalResult} res @param {string} id @param {string | null} advisory @param {(status: any) => void} onStatus */
  function sectionBody(tid, res, id, advisory, onStatus) {
    var entry = entryFor(tid, id, onStatus);
    var d = /** @type {any} */ (res.deck);
    var adv = advisory ? { tone: copy.warningTone(advisory), text: copy.sentence(advisory) } : undefined;
    switch (id) {
      case 'letter':
        if (res.kind === 'no_bid') {
          return [h(F.EntryCard, entry({ key: 'c', title: d.meta.headline, advisory: adv, provenance: aiProv(res) }), h('p', null, d.meta.subtitle))];
        }
        return [
          h(F.EntryCard, entry({ key: 'c', title: d.meta.headline, advisory: adv, provenance: aiProv(res) }), h('p', null, d.meta.subtitle)),
          h(F.EntryCard, entry({ key: 'l', title: d.letter.title, provenance: aiProv(res) }),
            h('p', null, d.letter.salutation),
            d.letter.paragraphs.map(function (/** @type {string} */ x) { return h('p', { key: x }, x); }),
            h('p', null, d.letter.closing, h('br'), h('strong', null, d.signatory.name), ', ' + d.signatory.role + ' · ' + d.signatory.contact)),
        ];
      case 'summary':
        return d.summary.pillars.map(function (/** @type {any} */ pl, /** @type {number} */ i) {
          return h(F.EntryCard, entry({ key: pl.title, title: pl.title, advisory: i === 0 ? adv : undefined, provenance: aiProv(res, pl.evidence.length) }),
            h('p', null, pl.body, ev.citations(tid, pl.evidence)));
        }).concat([h(F.EntryCard, entry({ key: 'why', title: d.summary.title, provenance: aiProv(res) }), h('p', null, d.summary.why_us))]);
      case 'buyer': {
        var est = estimatedFor(d, 'buyer');
        var pr = d.buyer.profile;
        function line(/** @type {string} */ label, /** @type {string} */ key) {
          return h('div', { className: 'uip-fact' }, h('dt', { className: 'meta uip-muted' }, label),
            h('dd', { className: 'body uip-inline' }, pr[key], est.indexOf('buyer.profile.' + key) >= 0 ? h(Estimated) : null));
        }
        var profileAdv = adv || (!d.buyer.researched ? { tone: 'neutral', text: 'Estimated from the tender — research was not run when this deck was generated.' } : undefined);
        return [
          h(F.EntryCard, entry({ key: 'p', title: 'Buyer profile', advisory: profileAdv }),
            h('dl', { className: 'uip-facts uip-facts--wide' }, line('Sector', 'sector'), line('Estimated revenue', 'estimated_revenue'), line('Key partners', 'key_partners')), byCode()),
        ].concat(d.buyer.needs.map(function (/** @type {any} */ n) {
          return h(F.EntryCard, entry({ key: n.title, title: n.title, provenance: aiProv(res) }), h('p', null, n.body));
        }));
      }
      case 'matrix':
        return [h(F.EntryCard, entry({ key: 'm', title: 'Requirements on the slide', advisory: adv }),
          h('div', { className: 'uip-ov-rows' }, d.requirements.map(function (/** @type {any} */ r) {
            return h(F.ListRow, { key: r.requirement, variant: 'flat', title: r.requirement, subtitle: r.evidence_id ? r.evidence + ' · ' + r.evidence_id : 'Nothing retrieved for this requirement', trailing: h(Score, { score: r.score }) });
          })),
          h('p', { className: 'meta' }, h('a', { className: 'fn-link', href: ui.href('match/' + tid) }, 'Open the full matrix')))];
      case 'approach':
        return d.approach.phases.map(function (/** @type {any} */ ph, /** @type {number} */ i) {
          return h(F.EntryCard, entry({ key: ph.name, title: ph.name + ' · ' + ui.count(ph.weeks, 'week'), advisory: i === 0 ? adv : undefined, provenance: aiProv(res) }), h('p', null, ph.body));
        }).concat([h(F.EntryCard, entry({ key: 'ms', title: d.approach.title, provenance: aiProv(res) }), h('p', null, d.approach.milestones))]);
      case 'team':
        return [h(F.EntryCard, entry({ key: 't', title: 'Proposed team', advisory: adv }),
          h('div', { className: 'uip-ov-rows' }, d.team.map(function (/** @type {any} */ c) {
            return h(F.ListRow, { key: c.name + c.role, variant: 'flat', title: c.cv_id ? c.name + ' · ' + c.role : 'To be staffed', subtitle: c.cv_id ? [c.years != null ? ui.count(c.years, 'year') : null, c.skills].filter(Boolean).join(' · ') : c.role, trailing: c.cv_id ? h(Score, { score: c.score }) : h(F.Status, { status: 'stale', size: 'sm' }, 'Placeholder') });
          })), byCode())];
      case 'references':
        return [h(F.EntryCard, entry({ key: 'r', title: 'Reference projects', advisory: adv }),
          h('div', { className: 'uip-ov-rows' }, d.references.map(function (/** @type {any} */ x) {
            var delivered = x.delivered === true ? h(F.Status, { status: 'good', size: 'sm' }, 'Delivered') : h(F.Status, { status: 'stale', size: 'sm' }, x.delivered === false ? 'Not delivered' : 'Unverified');
            return h(F.ListRow, { key: x.title, variant: 'flat', title: x.title, subtitle: x.summary + ' · ' + x.sector, trailing: h('span', { className: 'uip-trail' }, delivered, h(Score, { score: x.score })) });
          })), byCode())];
      case 'investment': {
        var inv = d.investment;
        var est2 = estimatedFor(d, 'investment').length > 0;
        var total = inv.lines.reduce(function (/** @type {number} */ s, /** @type {any} */ l) { return s + (l.amount || 0); }, 0);
        return [
          h(F.EntryCard, entry({ key: 'i', title: 'Indicative pricing', advisory: adv || (est2 ? { tone: 'neutral', text: 'Estimated — days × blended day rate, set by code. Re-check before sending.' } : undefined) }),
            h('div', { className: 'uip-ov-rows' },
              inv.lines.map(function (/** @type {any} */ l) {
                return h(F.ListRow, { key: l.workstream, variant: 'flat', title: l.workstream, subtitle: l.days != null ? ui.count(l.days, 'day') : 'Days to be scoped', trailing: h('span', { className: 'ui-strong uip-num' }, ui.money(l.amount, inv.currency)) });
              }),
              h(F.ListRow, { variant: 'flat', title: 'Total', trailing: h('span', { className: 'ui-strong uip-num' }, ui.money(total, inv.currency)) })),
            h('p', { className: 'meta uip-muted' }, inv.note)),
          h(F.EntryCard, entry({ key: 'n', title: 'Next steps', provenance: aiProv(res) }),
            h('div', { className: 'uip-ov-rows' }, inv.next_steps.map(function (/** @type {any} */ n) { return h(F.ListRow, { key: n.title, variant: 'flat', title: n.title, subtitle: n.detail }); }))),
        ];
      }
      case 'warnings':
        var warnings = d && Array.isArray(d.warnings) ? d.warnings : (res.warnings || []);
        return [h(F.EntryCard, entry({ key: 'w', title: 'Why this is a no-bid' }),
          warnings.map(function (/** @type {string} */ w) { return h('p', { key: w }, copy.sentence(w) + '.'); }))];
      default:
        return [];
    }
  }

  function traceNote(/** @type {import('../types').ProposalResult} */ res, /** @type {string} */ id) {
    var mine = copy.traceFor(res.trace, id);
    return mine.length ? h('p', { className: 'meta uip-muted' }, copy.traceLine(mine)) : null;
  }

  /** The typed sign-off under the Review queue: a name someone typed, not a verified account. */
  function SignOff(/** @type {{ review: import('../types').Review, busy: boolean, onSign: (name: string | null) => Promise<any> }} */ p) {
    var name = React.useState('');
    var by = p.review.signed_off_by;
    return h('div', { className: 'uip-stack uip-cap' },
      by ? h('p', { className: 'meta' }, 'Signed off by ' + by + (p.review.signed_off_at ? ' · ' + ui.date(p.review.signed_off_at) : '')) : null,
      h(F.TextField, { label: by ? 'Sign off as someone else' : 'Sign off', hint: 'Typed name, not a verified account', value: name[0], maxLength: 80, onChange: function (/** @type {any} */ e) { name[1](e.target.value); } }),
      h('div', { className: 'uip-inline' },
        h(F.Button, { size: 'sm', icon: 'check', loading: p.busy, disabledReason: name[0].trim() ? undefined : 'Type a name to sign off.', onClick: function () { p.onSign(name[0].trim()).then(function () { name[1](''); }, function () {}); } }, 'Sign Off'),
        by ? h(F.Button, { size: 'sm', variant: 'tertiary', disabled: p.busy, onClick: function () { p.onSign(null).catch(function () {}); } }, 'Clear Sign-off') : null));
  }

  function Review(/** @type {{ route: any }} */ p) {
    var s = store.useStore();
    var act = ui.useAction();
    var rev = ui.useAction();
    var decision = React.useState(/** @type {{ kind?: string, review_status?: string, warnings?: string[] } | null} */ (null));
    var saveAgain = React.useRef(/** @type {(() => Promise<any>) | null} */ (null));
    var reviewId = p.route.id || ui.rememberTender(null);
    var need = ui.needTender(p.route.id || ui.rememberTender(null), 'review', 'blush');
    if (!need.tender) return need.page;
    var t = need.tender;
    ui.rememberTender(t.id);
    var res = s.proposals[t.id];
    var share = h(ui.FutureButton, { key: 's', label: 'Share', icon: 'share', reason: ui.FUTURE.share });

    if (!res || res.kind === 'rejected') {
      return h(ui.WorkPage, {
        world: 'blush', rail: 'review', chip: 'Review', kicker: t.title, title: 'Review the Deck',
        actions: [share, h(F.Button, { key: 'e', variant: 'primary', icon: 'presentation', disabledReason: res ? 'No deck written — the validator found ' + ui.count(res.warnings.length, 'issue') + '.' : 'Generate the deck first.' }, 'Export Deck')],
      }, h(F.Card, null, h(F.EmptyState, { world: 'blush', illustration: 'review', title: res ? 'Fix the Deck Before Review' : 'Review the Deck Here', action: { label: res ? 'Open Draft' : 'Generate Deck', icon: res ? 'arrow-right' : 'play', onClick: function () { ui.go('draft/' + t.id); } } },
        res ? 'The validator refused this deck, so nothing was written. Its issues are listed on the Draft screen.' : 'Each section of the deck appears here with the records it cites and every warning the checks raised.')));
    }

    var generating = flow.generating(s, t.id);
    var review = store.reviewOf(t.id);
    var saving = !!s.running['review:' + t.id];
    function reviewRun(/** @type {() => Promise<any>} */ fn) {
      saveAgain.current = fn;
      return rev.run(fn);
    }
    function reloadReview() { reviewRun(function () { return store.reloadReview(t.id); }).catch(function () {}); }
    function setStatus(/** @type {string} */ section, /** @type {any} */ status) {
      reviewRun(function () { return store.setSectionStatus(t.id, section, status); }).catch(function () {});
    }
    function sign(/** @type {string | null} */ name) {
      return reviewRun(function () { return store.signOff(t.id, name); });
    }
    function retryReview() {
      var again = saveAgain.current;
      if (again) reviewRun(again).catch(function () {});
    }
    function regenerate() { act.run(function () { return store.generateDeck(t.id); }).catch(function () {}); }
    function accept() {
      act.run(function () { return store.acceptProposal(t.id); }).then(function (result) {
        decision[1](result);
      }).catch(function () {});
    }
    function refuse() {
      act.run(function () { return store.refuseProposal(t.id); }).then(function (result) {
        decision[1](result);
      }).catch(function () {});
    }
    var sections = sectionsOf(res);
    var cur = p.route.query.get('section') || sections[0].id;
    var current = sections.find(function (x) { return x.id === cur; }) || sections[0];
    var ws = warningsFor(res, current.id);

    return h(ui.WorkPage, {
      world: 'blush', rail: 'review', chip: 'Review', title: current.label,
      kicker: t.title + ' · ' + ui.count(res.warnings.length, 'warning'),
      actions: [
        share,
        h(F.Button, { key: 'g', icon: 'refresh', loading: generating, disabledReason: generating ? undefined : flow.deckBlocked(t), onClick: regenerate }, generating ? 'Regenerating…' : 'Regenerate Deck'),
        (!res.review_status || res.review_status === 'draft') && !res.artifacts.pptx ? h(F.Button, { key: 'r', variant: 'tertiary', icon: 'x', loading: !!s.running.proposal, onClick: refuse }, 'Refuse') : null,
        (!res.review_status || res.review_status === 'draft') && !res.artifacts.pptx ? h(F.Button, { key: 'a', variant: 'primary', icon: 'check', loading: !!s.running.proposal, onClick: accept }, 'Accept & Export') : null,
        h(F.Button, { key: 'e', variant: 'primary', icon: 'presentation', onClick: function () { ui.go('export/' + t.id); } }, 'Export Deck'),
      ],
    },
      h('div', { className: 'uip-cols' },
        h(F.Card, { density: 'compact', className: 'uip-queue' },
          h('p', { className: 'fn-caption uip-cap' }, 'Deck · ' + ui.count(sections.length, 'section')),
          sections.map(function (sec) {
            var st = sectionStatus(res, sec.id);
            return h(F.ListRow, { key: sec.id, variant: 'flat', active: sec.id === current.id, title: sec.label, href: ui.href('review/' + t.id + '?section=' + sec.id), trailing: h(F.Status, { status: st.status, size: 'sm' }, st.label) });
          }),
          h(SignOff, { key: t.id + review.signed_off_by, review: review, busy: saving, onSign: sign })),
        generating
          ? h(F.Card, null, h(ui.Runner, { icon: 'presentation', world: 'blush', ai: true, label: 'Regenerating the deck…', detail: 'The whole deck is rebuilt: every section, score and check runs again.' }))
          : h('div', { className: 'uip-stack' },
            rev.error ? h(ui.ReviewError, { error: rev.error, onReload: reloadReview, onRetry: retryReview }) : null,
            act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: regenerate }) : null,
            decision[0] && decision[0].kind === 'rejected'
              ? h(F.AdvisoryStrip, { tone: 'risk' }, 'Acceptance was blocked by the validator. Fix the issues on Draft and try again.')
              : null,
            decision[0] && decision[0].review_status === 'refused'
              ? h(F.AdvisoryStrip, { tone: 'risk' }, 'This deck was refused and will not be exported.')
              : null,
            res.review_status === 'accepted' ? h(F.AdvisoryStrip, { tone: 'good' }, 'Accepted — the generated files are ready in Export.') : null,
            res.review_status === 'refused' ? h(F.AdvisoryStrip, { tone: 'risk' }, 'Refused — this deck will not be exported.') : null,
            ws.slice(1).map(function (w) { return h(F.AdvisoryStrip, { key: w, tone: copy.warningTone(w) }, copy.sentence(w)); }),
            sectionBody(t.id, res, current.id, ws[0] || null, function (status) { setStatus(current.id, status); }),
            traceNote(res, current.id))));
  }

  /* -------------------------------------------------------------- Export */

  function Export(/** @type {{ route: any }} */ p) {
    var s = store.useStore();
    var act = ui.useAction();
    var fetching = React.useState(/** @type {string | null} */ (null));
    var last = React.useRef(/** @type {string | null} */ (null));
    var need = ui.needTender(p.route.id || ui.rememberTender(null), 'export', 'stone');
    if (!need.tender) return need.page;
    var t = need.tender;
    ui.rememberTender(t.id);
    var res = s.proposals[t.id];
    var a = res ? res.artifacts : {};
    function download(/** @type {string} */ name) {
      last.current = name;
      fetching[1](name);
      act.run(function () { return api.download(api.fileUrl(t.id, name), name); }).catch(function () {}).then(function () { fetching[1](null); });
    }
    function downloadButton(/** @type {string} */ name) {
      return h(F.Button, { size: 'sm', icon: 'download', loading: fetching[0] === name, disabled: !!fetching[0] && fetching[0] !== name, onClick: function () { download(name); } }, 'Download');
    }
    var pdfSkip = res && res.warnings.find(function (w) { return /^PDF skipped/.test(w); });
    var body;
    if (!res) {
      body = h(F.Card, null, h(F.EmptyState, { world: 'stone', illustration: 'export', title: 'Your Deck Appears Here', action: { label: 'Open Draft', icon: 'arrow-right', onClick: function () { ui.go('draft/' + t.id); } } },
        'An editable PowerPoint, a formatted PDF and the full requirements matrix as CSV, written once the deck passes the validator.'));
    } else if (res.kind === 'rejected') {
      body = h(F.Card, { className: 'uip-stack-s' },
        h(F.AdvisoryStrip, { tone: 'risk' }, 'No deck written — the validator found ' + ui.count(res.warnings.length, 'issue') + '.'),
        h('p', { className: 'ui uip-muted' }, 'No files exist for this tender. Regenerate the deck from the Draft screen.'));
    } else {
      body = h('div', { className: 'uip-narrow uip-stack' },
        h(F.Card, { density: 'compact', className: 'uip-queue' },
          h('p', { className: 'fn-caption uip-cap' }, 'Files · generated ' + ui.date(res.generated_at, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })),
          a.pptx ? h(F.ListRow, { variant: 'flat', file: 'pptx', title: a.pptx, subtitle: 'Editable PowerPoint', trailing: downloadButton(a.pptx) }) : null,
          a.pdf
            ? h(F.ListRow, { variant: 'flat', file: 'pdf', title: a.pdf, subtitle: 'Formatted PDF', trailing: downloadButton(a.pdf) })
            : h(F.ListRow, { variant: 'flat', file: 'pdf', title: 'PDF', subtitle: pdfSkip ? copy.sentence(pdfSkip) : 'PDF skipped', trailing: h(F.Status, { status: 'stale', size: 'sm' }, 'Skipped') }),
          a.csv ? h(F.ListRow, { variant: 'flat', file: 'csv', title: a.csv, subtitle: 'Requirements matrix — every requirement, shown or not', trailing: downloadButton(a.csv) }) : null),
        act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: fetching[0] || !last.current ? undefined : function () { download(/** @type {string} */ (last.current)); } }) : null,
        h(F.AdvisoryStrip, { tone: 'neutral', icon: 'layers' }, 'Files are written only after the validator passes the deck; every score, name and price in them was set by code.'));
    }
    return h(ui.WorkPage, {
      world: 'stone', rail: 'export', chip: 'Export', kicker: t.title, title: 'Download the Deck',
      actions: res && res.kind !== 'rejected' && a.pptx
        ? [h(F.Button, { key: 'd', variant: 'primary', icon: 'download', loading: fetching[0] === a.pptx, disabled: !!fetching[0] && fetching[0] !== a.pptx, onClick: function () { download(/** @type {string} */ (a.pptx)); } }, 'Download PPTX')]
        : [h(F.Button, { key: 'd', variant: 'primary', icon: 'download', disabledReason: res ? 'No deck written.' : 'Generate the deck first.' }, 'Download PPTX')],
    }, body);
  }

  window.UIP.screens.draft = Draft;
  window.UIP.screens.review = Review;
  window.UIP.screens.export = Export;
})();

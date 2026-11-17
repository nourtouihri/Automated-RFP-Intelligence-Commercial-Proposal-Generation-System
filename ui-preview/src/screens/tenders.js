// @ts-check
// Detect stage (peach): the tender list, intake from feed / TED / by hand, and one tender's detail.
window.UIP = window.UIP || {};
window.UIP.screens = window.UIP.screens || {};

window.UIP.screens.tenders = (function () {
  var ui = window.UIP.ui;
  var h = ui.h;
  var F = ui.F;
  var copy = window.UIP.copy;
  var store = window.UIP.store;
  var flow = window.UIP.flow;

  var STATUSES = ['new', 'incomplete', 'processed', 'archived'];
  var PIPELINE = flow.PIPELINE;
  var PIPELINE_DETAIL = flow.PIPELINE_DETAIL;

  function ResearchChip(/** @type {{ r: import('../types').ProspectResearch | undefined }} */ p) {
    if (!p.r) return h(F.Chip, { size: 'sm' }, 'Not researched');
    var st = copy.RESEARCH_STATUS[p.r.status || 'unavailable'];
    return p.r.status === 'unavailable' ? h(F.Chip, { tone: 'stale', size: 'sm' }, st.label) : h(F.Chip, { tone: 'ice', icon: 'building', size: 'sm' }, st.label);
  }

  function deadlineText(/** @type {import('../types').Tender} */ t) {
    if (!t.deadline) return 'No deadline';
    return (t.quality.is_expired ? 'Closed ' : 'Closes ') + ui.date(t.deadline);
  }

  function safeHref(/** @type {string} */ url) {
    try { var u = new URL(url); return u.protocol === 'http:' || u.protocol === 'https:' ? u.href : null; } catch (e) { return null; }
  }

  /** A document link, named by its file type when the path says so, else by its host. */
  function documentInfo(/** @type {string} */ url) {
    try {
      var u = new URL(url);
      var host = u.hostname.replace(/^www\./, '');
      var path = u.pathname.toLowerCase();
      if (/(\.pdf|\/pdf)$/.test(path)) return { file: 'pdf', label: 'PDF document', host: host };
      if (/\.(html?|xhtml)$/.test(path) || /\/(html|notice\/[^/]+)$/.test(path)) return { file: 'url', label: 'Notice page', host: host };
      return { file: 'url', label: host, host: host };
    } catch (e) { return { file: 'url', label: url, host: '' }; }
  }

  function StatusChip(/** @type {{ t: import('../types').Tender }} */ p) {
    var st = copy.TENDER_STATUS[p.t.status];
    return st.chip === 'good' || st.chip === 'stale'
      ? h(F.Status, { status: st.chip, size: 'sm' }, st.label)
      : h(F.Chip, { tone: st.chip, dot: true, size: 'sm' }, st.label);
  }

  /* ------------------------------------------------------- Intake panels */

  function SeedResult(/** @type {{ seed: import('../types').SeedResult }} */ p) {
    var rows = p.seed.tenders;
    var failed = rows.filter(function (r) { return r.status === 'error'; });
    var known = rows.filter(function (r) { return r.status === 'success' && r.existing; }).length;
    var added = rows.length - failed.length - known;
    return h(F.Card, { density: 'compact', className: 'uip-pad' },
      h(F.AdvisoryStrip, { tone: failed.length ? 'neutral' : 'good' },
        'Loaded ' + ui.count(added, 'new tender') + ' · ' + known + ' already known · ' + failed.length + ' failed'),
      failed.map(function (/** @type {any} */ r) {
        return h(F.ListRow, { key: r.file, variant: 'flat', file: 'txt', title: r.file, subtitle: r.error, trailing: h(F.Status, { status: 'risk', size: 'sm' }, 'Not loaded') });
      }));
  }

  var FETCH = {
    TED: { label: 'TED EU', icon: 'globe', detail: 'English notices only; each one is mapped to the tender format.' },
    SAM: { label: 'SAM.gov (USA)', icon: 'radar', detail: 'Active US federal opportunities in NAICS 541, posted in the last year.' },
  };

  /** TED carries English PDF/HTML links; SAM carries a list of attachment URLs. */
  function noticeLink(/** @type {import('../types').Notice} */ no) {
    if (Array.isArray(no.links)) {
      var first = no.links.length ? safeHref(no.links[0]) : null;
      return first ? { href: first, label: ui.count(no.links.length, 'file') } : null;
    }
    var pdfs = (no.links && no.links.pdfs) || {};
    var english = Object.keys(pdfs).find(function (k) { return k.toLowerCase() === 'eng'; });
    var pdf = safeHref(pdfs[english || Object.keys(pdfs)[0]]);
    return pdf ? { href: pdf, label: 'PDF' } : null;
  }

  function FetchPanel(/** @type {{ source: string | null }} */ p) {
    var s = store.useStore();
    var on = s.prefs.sources;
    var enabled = Object.keys(FETCH).filter(function (k) { return on[k] !== false; });
    var src = React.useState(p.source && enabled.indexOf(p.source) >= 0 ? p.source : enabled[0]);
    var page = React.useState(String(s.prefs.tedPage || 1));
    var act = ui.useAction();
    var source = /** @type {'TED' | 'SAM'} */ (src[0]);
    var n = Number(page[0]);
    var batch = s.fetched && s.fetched.source === source ? s.fetched : null;
    var bad = !Number.isInteger(n) || n < 1 ? 'Enter a page number of 1 or more.'
      : batch && n > batch.page_cap ? 'This source has ' + ui.count(batch.page_cap, 'page') + '.' : null;
    if (!source) {
      return h(F.Card, null, h(F.EmptyState, { world: 'peach', illustration: 'sources', layout: 'inline', title: 'Turn On a Notice Source', action: { label: 'Open Settings', icon: 'sliders', variant: 'secondary', onClick: function () { ui.go('settings'); } } },
        'TED EU and SAM.gov are both off. Turn one on in Settings to fetch notices here.'));
    }
    var meta = FETCH[source];
    function fetchPage() { act.run(function () { return store.fetchNotices(source, n); }).catch(function () {}); }
    if (s.running.fetch) return h(F.Card, null, h(ui.Runner, { icon: meta.icon, world: 'peach', label: 'Fetching ' + meta.label + ' notices…', detail: meta.detail }));
    if (s.running.send) return h(F.Card, null, h(ui.Runner, { icon: 'send', world: 'peach', label: 'Sending notices to detection…', detail: 'Each notice is validated, deduplicated and tagged with a service line.' }));
    return h(F.Card, { className: 'uip-stack-s' },
      h('p', { className: 'fn-caption' }, 'Fetch notices'),
      h('form', {
        className: 'uip-inline-form',
        onSubmit: function (/** @type {Event} */ e) { e.preventDefault(); if (!bad) fetchPage(); },
      },
        h('div', { className: 'uip-fact uip-fetch-source' },
          h('span', { className: 'fn-field-label' }, 'Source'),
          h(F.StatusSelect, { value: source, label: 'Notice source', options: enabled.map(function (k) { return { value: k, label: FETCH[k].label }; }), onChange: function (/** @type {string} */ v) { act.clear(); src[1](v); } })),
        h(F.TextField, { label: 'Page', type: 'number', min: 1, value: page[0], onChange: function (/** @type {any} */ e) { page[1](e.target.value); }, error: bad, hint: batch ? 'Page 1 to ' + batch.page_cap + ' of ' + meta.label + '.' : 'A page of ' + meta.label + ' results.' }),
        h(F.Button, { type: 'submit', icon: meta.icon }, 'Fetch Page')),
      act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: fetchPage }) : null,
      batch ? h('div', { className: 'uip-stack-s' },
        h('p', { className: 'fn-caption' }, meta.label + ' · page ' + batch.page + ' of ' + batch.page_cap + ' · ' + ui.count(batch.notices.length, 'notice')),
        batch.notices.length
          ? [
            h(F.AdvisoryStrip, { key: 'a', tone: 'neutral' }, 'Fetched notices are not stored until you send them to detection.'),
            batch.notices.map(function (no) {
              var link = noticeLink(no);
              return h(F.ListRow, {
                key: no.id, variant: 'flat', file: 'url', title: no.title,
                subtitle: [no.issuer, no.issuer_country, 'closes ' + ui.date(no.deadline), 'published ' + ui.date(no.published_at)].join(' · '),
                trailing: h('span', { className: 'uip-trail' },
                  no.notice_type ? h(F.Chip, { size: 'sm' }, no.notice_type) : null,
                  no.raw_text ? null : h(F.Status, { status: 'risk', size: 'sm' }, 'No text'),
                  link ? h('a', { className: 'fn-link meta', href: link.href, target: '_blank', rel: 'noopener noreferrer' }, link.label) : null),
              });
            }),
            h('div', { key: 'b' },
              h(F.Button, { icon: 'send', onClick: function () { act.run(function () { return store.sendNotices(batch.notices); }).catch(function () {}); } }, 'Send ' + batch.notices.length + ' to Detection')),
          ]
          : h(F.EmptyState, { world: 'peach', illustration: 'sources', layout: 'inline', title: 'No Notices on This Page' }, 'Try an earlier page; this source returns notices that match its search.'))
        : null);
  }

  /* ---------------------------------------------------------------- List */

  function List(/** @type {{ route: any }} */ p) {
    var s = store.useStore();
    var act = ui.useAction();
    var q = p.route.query;
    var status = q.get('status');
    var source = q.get('source');
    var stage = q.get('stage');
    var country = q.get('country');
    var on = s.prefs.sources;
    var showFetch = (q.get('panel') === 'fetch' || q.get('panel') === 'ted') && (on.TED !== false || on.SAM !== false);
    var fresh = s.tenders.filter(function (t) { return t.status === 'new'; }).length;
    var stageDef = PIPELINE.find(function (x) { return x.id === stage; });
    var shown = s.tenders.filter(function (t) {
      return (!status || t.status === status) && (!source || t.source === source) && (!country || t.issuer_country === country) && (!stageDef || stageDef.has(s, t.id));
    });
    var track = PIPELINE.map(function (x) {
      var n = s.tenders.filter(function (t) { return x.has(s, t.id); }).length;
      return { id: x.id, label: x.label, world: x.world, status: x.id === (stage || 'detect') ? 'current' : n ? 'done' : 'next', detail: n + ' ' + PIPELINE_DETAIL[x.id] };
    });
    function seed() { act.run(store.seedFeed).catch(function () {}); }

    var sections = [
      { id: 'status', title: 'Status', items: [{ id: 'all', label: 'All tenders', icon: 'inbox', count: s.tenders.length }].concat(STATUSES.map(function (st) {
        return { id: 'status:' + st, label: copy.TENDER_STATUS[st].label, icon: st === 'archived' ? 'folder' : 'circle-dashed', count: s.tenders.filter(function (t) { return t.status === st; }).length };
      })) },
      { id: 'sources', title: 'Sources', items: Object.keys(copy.SOURCE).map(function (src) {
        return { id: 'source:' + src, label: copy.SOURCE[src], icon: src === 'TED' ? 'globe' : src === 'SAM' ? 'radar' : src === 'manual' ? 'pen-line' : 'inbox', count: s.tenders.filter(function (t) { return t.source === src; }).length };
      }) },
    ];
    var countries = Array.from(new Set(s.tenders.map(function (t) { return t.issuer_country; }).filter(Boolean))).sort();
    if (countries.length) {
      sections.push({ id: 'countries', title: 'Country', items: countries.map(function (c) {
        return { id: 'country:' + c, label: c, icon: 'globe', count: s.tenders.filter(function (t) { return t.issuer_country === c; }).length };
      }) });
    }
    var value = status ? 'status:' + status : source ? 'source:' + source : country ? 'country:' + country : 'all';

    var list;
    if (!s.tenders.length) {
      list = h(F.Card, null, h(F.EmptyState, { world: 'peach', illustration: 'tender', title: 'Bring In Your First Tender', action: { label: 'Load Simulated Feed', icon: 'play', onClick: seed } },
        'Load the simulated feed, fetch a page of TED notices or add one by hand. Each tender gets a service line, its requirements and a data-quality check.'));
    } else if (!shown.length) {
      list = h(F.Card, null, h(F.EmptyState, { world: 'peach', illustration: 'search', layout: 'inline', title: 'No Tenders Here Yet' },
        status === 'archived' ? 'Tenders you archive from their detail page appear here.' : stageDef ? 'Tenders appear here once they reach ' + stageDef.label.toLowerCase() + '.' : 'Tenders matching this filter appear here as they are detected.'));
    } else {
      list = h(F.Card, { density: 'compact', className: 'uip-queue' },
        h('p', { className: 'fn-caption uip-cap' }, ui.count(shown.length, 'tender')),
        shown.map(function (t) {
          var notes = t.quality.warnings.length;
          return h(F.ListRow, {
            key: t.id, variant: 'flat', href: ui.href('tenders/' + t.id), title: t.title,
            subtitle: [t.issuer, t.issuer_country, deadlineText(t), copy.SOURCE[t.source]].filter(Boolean).join(' · '),
            progress: t.quality.completeness, progressLabel: 'Data completeness of ' + t.title,
            trailing: h('span', { className: 'uip-trail' },
              t.notice_type ? h(F.Chip, { size: 'sm' }, t.notice_type) : null,
              notes ? h(F.Chip, { tone: 'stale', size: 'sm' }, ui.count(notes, 'quality note')) : null,
              h(ResearchChip, { r: s.research[t.id] }),
              h(StatusChip, { t: t })),
          });
        }));
    }

    return h(ui.WorkPage, {
      world: 'peach', rail: 'tenders', chip: 'Detect', title: 'Tenders',
      kicker: ui.count(s.tenders.length, 'tender') + ' · ' + fresh + ' new',
      actions: [
        on.simulated_feed !== false ? h(F.Button, { key: 's', icon: 'inbox', onClick: seed, loading: !!s.running.seed }, s.running.seed ? 'Loading…' : 'Load Simulated Feed') : null,
        on.TED !== false || on.SAM !== false ? h(F.Button, { key: 't', icon: 'globe', onClick: function () { ui.go(showFetch ? 'tenders' : 'tenders?panel=fetch'); } }, 'Fetch Notices') : null,
        on.manual !== false ? h(F.Button, { key: 'a', variant: 'primary', icon: 'plus', onClick: function () { ui.go('tenders/new'); } }, 'Add Tender') : null,
      ],
    },
      h(F.StageTrack, { label: 'Pipeline', stages: track, onSelect: function (/** @type {string} */ id) { ui.go(id === 'detect' ? 'tenders' : 'tenders?stage=' + id); } }),
      h('div', { className: 'uip-cols' },
        h(F.Card, { density: 'compact', className: 'uip-queue' },
          h(F.TreeNav, { label: 'Tender filters', sections: sections, value: value, onChange: function (/** @type {string} */ id) {
            if (id === 'all') return ui.go('tenders');
            var parts = id.split(':');
            ui.go('tenders?' + parts[0] + '=' + encodeURIComponent(parts[1]));
          } })),
        h('div', { className: 'uip-stack' },
          s.running.seed ? h(F.Card, null, h(ui.Runner, { icon: 'inbox', world: 'peach', label: 'Loading the simulated feed…', detail: 'Each file is validated, deduplicated and tagged with a service line.' })) : null,
          act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: seed }) : null,
          s.seed && !s.running.seed ? h(SeedResult, { seed: s.seed }) : null,
          showFetch ? h(FetchPanel, { key: q.get('from') || 'any', source: q.get('from') }) : null,
          list)));
  }

  /* -------------------------------------------------------------- Detail */

  function Fact(/** @type {{ label: string, children: any }} */ p) {
    return h('div', { className: 'uip-fact' }, h('dt', { className: 'meta uip-muted' }, p.label), h('dd', { className: 'ui-strong' }, p.children));
  }

  function Detail(/** @type {{ id: string }} */ p) {
    var s = store.useStore();
    var act = ui.useAction();
    var need = ui.needTender(p.id, 'tenders', 'peach');
    if (!need.tender) return need.page;
    var t = need.tender;
    ui.rememberTender(t.id);
    var q = t.quality;
    var dup = q.warnings.find(function (w) { return w.indexOf('possible_duplicate_of:') === 0; });
    var sanitized = q.warnings.indexOf('sanitized_chars') >= 0;
    var pct = Math.round(q.completeness * 100);
    var archived = t.status === 'archived';
    function toggleArchive() { act.run(function () { return store.setTenderArchived(t.id, !archived); }).catch(function () {}); }

    return h(ui.WorkPage, {
      world: 'peach', rail: 'tenders', chip: 'Detect', title: t.title,
      kicker: copy.SOURCE[t.source] + ' · detected ' + ui.date(t.detected_at),
      actions: [
        h(F.Button, { key: 'a', icon: archived ? 'undo' : 'folder', onClick: toggleArchive, loading: !!s.running.archive }, archived ? 'Restore Tender' : 'Archive Tender'),
        h(F.Button, { key: 'r', variant: 'primary', icon: 'arrow-right', onClick: function () { ui.go('research/' + t.id); } }, 'Open Research'),
      ],
    },
      act.error ? h(ui.ErrorNotice, { error: act.error, onRetry: toggleArchive }) : null,
      h('div', { className: 'uip-cols' },
        h(F.Card, { density: 'compact', className: 'uip-pad uip-stack-s' },
          h('p', { className: 'fn-caption' }, 'Data quality'),
          h(F.Progress, { value: q.completeness, label: 'Data completeness', tone: pct >= 100 ? 'good' : 'link' }),
          h('p', { className: 'meta uip-muted uip-num' }, pct + '% complete'),
          q.missing_fields.length || q.warnings.length
            ? h('div', { className: 'uip-chips' },
              q.missing_fields.map(function (f) { return h(F.Chip, { key: f, tone: 'stale', size: 'sm' }, 'Missing ' + f.replace('_', ' ')); }),
              q.warnings.map(function (w) { return h(F.Status, { key: w, status: 'stale', size: 'sm' }, copy.qualityWord(w)); }))
            : h(F.Status, { status: 'good', size: 'sm' }, 'No quality notes'),
          h('dl', { className: 'uip-facts' },
            h(Fact, { label: 'Issuer' }, t.issuer),
            h(Fact, { label: 'Deadline' }, deadlineText(t)),
            t.issuer_country ? h(Fact, { label: 'Country' }, h(F.Chip, { size: 'sm' }, t.issuer_country)) : null,
            t.notice_type ? h(Fact, { label: 'Notice type' }, h(F.Chip, { size: 'sm' }, t.notice_type)) : null,
            t.published_at ? h(Fact, { label: 'Published' }, ui.date(t.published_at)) : null,
            h(Fact, { label: 'Service line' }, h(F.Chip, { tone: t.sector === 'unknown' ? 'stale' : 'peach', size: 'sm' }, copy.sectorLabel(t.sector))),
            h(Fact, { label: 'Status' }, h(StatusChip, { t: t })),
            h(Fact, { label: 'Tender ID' }, h('code', { className: 'uip-code' }, t.id)))),
        h('div', { className: 'uip-stack' },
          q.is_expired ? h(F.AdvisoryStrip, { tone: 'neutral' }, 'Closed ' + ui.date(t.deadline) + ' — research skips closed tenders unless you ask for it.') : null,
          !q.is_expired && q.missing_fields.length ? h(F.AdvisoryStrip, { tone: 'neutral' }, 'Accepted with gaps — kept as incomplete until the missing fields arrive.') : null,
          dup ? h(F.AdvisoryStrip, { tone: 'neutral' }, h('span', null, 'Looks like ', h('a', { className: 'fn-link', href: ui.href('tenders/' + dup.slice(22)) }, dup.slice(22)), ' — check before researching both.')) : null,
          sanitized ? h(F.AdvisoryStrip, { tone: 'neutral', icon: 'layers' }, h('span', null, 'Unsafe characters were removed at intake. ', h('a', { className: 'fn-link', href: ui.href('security') }, 'How intake is checked'))) : null,
          h(F.Card, { density: 'compact', className: 'uip-queue' },
            h('p', { className: 'fn-caption uip-cap' }, 'Requirements · ' + t.requirements.length),
            t.requirements.length
              ? t.requirements.map(function (r) { return h(F.ListRow, { key: r, variant: 'flat', title: r }); })
              : h(F.EmptyState, { world: 'peach', illustration: 'tender', layout: 'inline', title: 'No Requirements Found' }, 'A deck needs at least one requirement to match against. Re-ingest the notice with its requirements.')),
          h(F.Card, null,
            h('p', { className: 'fn-caption' }, 'Tender text'),
            h('p', { className: 'body uip-prose' }, t.raw_text || 'No tender text supplied.')),
          t.links && t.links.length ? h(F.Card, { density: 'compact', className: 'uip-queue' },
            h('p', { className: 'fn-caption uip-cap' }, 'Tender documents · ' + t.links.length),
            t.links.map(function (url) {
              var d = documentInfo(url);
              var href = safeHref(url);
              return h(F.ListRow, {
                key: url, variant: 'flat', file: d.file, title: d.label, subtitle: d.host,
                trailing: href ? h('a', { className: 'fn-link meta', href: href, target: '_blank', rel: 'noopener noreferrer', title: url }, 'Open') : null,
              });
            })) : null)));
  }

  /* ---------------------------------------------------------------- Form */

  var FIELD_LABEL = { title: 'title', issuer: 'issuer', deadline: 'deadline', requirements: 'requirements', raw_text: 'tender text' };

  /** The service's validation message, said as the fix. */
  function fieldError(/** @type {{ field: string | null, message: string }} */ e) {
    var label = FIELD_LABEL[e.field || ''] || 'field';
    var cap = /exceeds (\d+) (character|item) cap/.exec(e.message);
    if (/^Missing required field/.test(e.message)) return 'Add the ' + label + ' — every tender needs one.';
    if (cap) return 'Shorten the ' + label + ' to ' + new Intl.NumberFormat().format(Number(cap[1])) + ' ' + cap[2] + 's or fewer.';
    if (/must be at most/.test(e.message)) return 'Shorten each requirement to ' + new Intl.NumberFormat().format(store.limits.REQ_MAX_CHARS) + ' characters or fewer.';
    if (e.field === 'deadline') return 'Pick a date in the form YYYY-MM-DD.';
    return copy.sentence(e.message) + '.';
  }

  function NewTender() {
    var s = store.useStore();
    var act = ui.useAction();
    var f = React.useState({ title: '', issuer: '', deadline: '', requirements: '', raw_text: '' });
    var errs = React.useState(/** @type {Record<string, string>} */ ({}));
    var L = store.limits;
    function set(/** @type {string} */ k) {
      return function (/** @type {any} */ e) { f[1](Object.assign({}, f[0], { [k]: e.target.value })); };
    }
    function payload() {
      return {
        title: f[0].title, issuer: f[0].issuer, deadline: f[0].deadline || undefined, raw_text: f[0].raw_text, source: /** @type {'manual'} */ ('manual'),
        requirements: f[0].requirements.split('\n').map(function (r) { return r.trim(); }).filter(Boolean),
      };
    }
    function submit(/** @type {Event} */ e) {
      e.preventDefault();
      var bad = store.validateIngest(payload());
      if (bad) {
        errs[1]({ [bad.body.error.field || 'form']: fieldError(bad.body.error) });
        return;
      }
      errs[1]({});
      act.run(function () { return store.ingest(payload()); }).then(function (t) { ui.go('tenders/' + t.id); }).catch(function () {});
    }
    var E = errs[0];
    var body = s.running.ingest
      ? h(ui.Runner, { icon: 'file-text', world: 'peach', label: 'Reading the tender…', detail: 'Checking each field, tagging a service line and scoring data quality.' })
      : h('form', { className: 'uip-form', onSubmit: submit, noValidate: true },
        act.error ? h(ui.ErrorNotice, { error: act.error }) : null,
        h(F.TextField, { label: 'Title', required: true, value: f[0].title, onChange: set('title'), placeholder: 'Fleet telematics renewal…', error: E.title, hint: 'Required. Up to ' + L.TITLE_MAX + ' characters.' }),
        h(F.TextField, { label: 'Issuer', required: true, value: f[0].issuer, onChange: set('issuer'), placeholder: 'Northvale Transit Authority…', error: E.issuer, hint: 'Required. The buying organisation, as the notice names it.' }),
        h(F.TextField, { label: 'Deadline', type: 'date', value: f[0].deadline, onChange: set('deadline'), error: E.deadline, hint: 'Optional. Without one, the tender is kept as incomplete.' }),
        h(F.TextField, { label: 'Requirements', multiline: true, rows: 5, value: f[0].requirements, onChange: set('requirements'), placeholder: 'One requirement per line…', error: E.requirements, hint: 'One per line. Up to ' + L.REQ_MAX_ITEMS + ', each up to ' + new Intl.NumberFormat().format(L.REQ_MAX_CHARS) + ' characters.' }),
        h(F.TextField, { label: 'Tender text', multiline: true, rows: 8, value: f[0].raw_text, onChange: set('raw_text'), placeholder: 'Paste the notice text…', error: E.raw_text, hint: 'Optional, up to ' + new Intl.NumberFormat().format(L.RAW_TEXT_MAX) + ' characters. Unsafe characters are removed at intake.' }),
        h('div', { className: 'uip-acts' },
          h(F.Button, { variant: 'tertiary', onClick: function () { ui.go('tenders'); } }, 'Cancel'),
          h(F.Button, { variant: 'primary', type: 'submit', icon: 'plus' }, 'Add Tender')));
    return h(ui.WorkPage, { world: 'peach', rail: 'tenders', chip: 'Detect', kicker: 'Manual intake', title: 'Add a Tender' },
      h('div', { className: 'uip-narrow' }, h(F.Card, null, body)));
  }

  function Tenders(/** @type {{ route: any }} */ p) {
    if (p.route.id === 'new') return h(NewTender);
    if (p.route.id) return h(Detail, { id: p.route.id });
    return h(List, { route: p.route });
  }

  return Tenders;
})();

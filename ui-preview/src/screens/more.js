// @ts-check
// Library (RAG search), Security (the controls the backend ships), Settings and Alerts.
window.UIP = window.UIP || {};
window.UIP.screens = window.UIP.screens || {};

(function () {
  var ui = window.UIP.ui;
  var h = ui.h;
  var F = ui.F;
  var copy = window.UIP.copy;
  var store = window.UIP.store;
  var ev = window.UIP.evidence;

  /* ------------------------------------------------------------- Library */

  var TYPES = [
    { id: 'all', label: 'All records', icon: 'library' },
    { id: 'cv', label: 'Consultants', icon: 'users' },
    { id: 'project', label: 'Past projects', icon: 'briefcase' },
    { id: 'tool', label: 'Tools', icon: 'command' },
  ];
  var SCOPES = {
    all: [{ label: 'tenders', world: 'peach' }, { label: 'consultants', world: 'sage' }, { label: 'past projects', world: 'sage' }, { label: 'tools', world: 'sage' }],
    cv: [{ label: 'consultants', world: 'sage' }],
    project: [{ label: 'past projects', world: 'sage' }],
    tool: [{ label: 'tools', world: 'sage' }],
  };

  var TENDER_ROWS = 6;

  /** The record types with their live counts; no count at all until the RAG service has answered. */
  function typeItems(/** @type {import('../types').LibraryStats | null} */ stats) {
    return TYPES.map(function (t) {
      var n = !stats ? undefined : t.id === 'all' ? stats.cv + stats.project + stats.tool : stats[/** @type {import('../types').DocType} */ (t.id)];
      return n === undefined ? t : Object.assign({}, t, { count: n });
    });
  }

  function Library(/** @type {{ route: any }} */ p) {
    var s = store.useStore();
    var q = p.route.query;
    var text = q.get('q') || '';
    var type = q.get('type') || 'all';
    var k = React.useState(String(s.prefs.topK));
    var min = React.useState(String(s.prefs.minSimilarity));
    var results = React.useState(/** @type {import('../types').QueryResult[] | null} */ (null));
    var open = React.useState(/** @type {string | null} */ (null));
    var act = ui.useAction();
    var kN = Number(k[0]);
    var minN = Number(min[0]);
    var kErr = !Number.isInteger(kN) || kN < 1 || kN > 20 ? 'Choose 1 to 20 results.' : null;
    var minErr = isNaN(minN) || minN < 0 || minN > 1 ? 'Choose a value from 0 to 1.' : null;
    var tooShort = text.trim().length > 0 && text.trim().length < 3;
    var tooLong = text.length > 10000;

    function search() {
      if (!text.trim() || tooShort || tooLong || kErr || minErr) return;
      act.run(function () {
        return store.query({ text: text, top_k: kN, doc_type: type === 'all' ? null : /** @type {any} */ (type), similarity_threshold: minN });
      }).then(results[1]).catch(function () {});
    }
    React.useEffect(search, [text, type, k[0], min[0]]);
    React.useEffect(function () { if (!s.stats) store.loadStats(); }, []);

    function setQuery(/** @type {string} */ key, /** @type {string} */ value) {
      var next = new URLSearchParams(q);
      if (value && value !== 'all') next.set(key, value); else next.delete(key);
      ui.go('library' + (next.toString() ? '?' + next.toString() : ''));
    }

    // Tenders live in the detection store, not the knowledge base: matched here from the loaded list.
    var tenderHits = type === 'all' && !tooShort && !tooLong ? store.matchTenders(s.tenders, text) : [];
    var tenders = tenderHits.length ? h(F.Card, { density: 'compact', className: 'uip-queue' },
      h('p', { className: 'fn-caption uip-cap' }, tenderHits.length > TENDER_ROWS ? TENDER_ROWS + ' of ' + ui.count(tenderHits.length, 'tender') : ui.count(tenderHits.length, 'tender')),
      tenderHits.slice(0, TENDER_ROWS).map(function (t) {
        return h(F.ListRow, {
          key: t.id, variant: 'flat', href: ui.href('tenders/' + t.id), title: t.title,
          subtitle: [t.issuer, t.issuer_country, copy.SOURCE[t.source], t.id].filter(Boolean).join(' · '),
          trailing: h(F.Chip, { size: 'sm' }, copy.TENDER_STATUS[t.status].label),
        });
      })) : null;

    var body;
    if (!text.trim()) {
      body = h(F.Card, null, h(F.EmptyState, { world: 'sage', illustration: 'search', title: 'Search Your People and Projects' },
        'Describe a requirement in plain words. The closest CVs, past projects and tools come back with a similarity score and the record behind them.'));
    } else if (tooShort || tooLong) {
      body = h(F.AdvisoryStrip, { tone: 'neutral' }, tooShort ? 'Type at least 3 characters to search.' : 'Shorten the search to 10,000 characters or fewer.');
    } else if (s.running.query) {
      body = h(F.Card, null, h(ui.Runner, { icon: 'search', world: 'sage', label: 'Searching the knowledge base…', detail: 'Finding the closest CVs, past projects and tools.' }));
    } else if (act.error) {
      body = h(ui.ErrorNotice, { error: act.error, onRetry: search });
    } else if (results[0] && !results[0].length) {
      body = h(F.Card, null, h(F.EmptyState, { world: 'sage', illustration: 'search', layout: 'inline', title: 'No Records Match Yet' }, 'Try the words the tender uses, choose another record type or lower the minimum similarity.'));
    } else if (results[0]) {
      body = h(F.Card, { density: 'compact', className: 'uip-queue' },
        h('p', { className: 'fn-caption uip-cap' }, ui.count(results[0].length, 'result')),
        results[0].map(function (r) {
          var m = r.metadata;
          var id = m.record_id;
          var isOpen = open[0] === id;
          return h('div', { key: id, className: 'uip-stack-s' },
            h(F.ListRow, {
              variant: 'flat', active: isOpen,
              title: r.doc_type === 'cv' ? (m.person || id) + (m.role ? ' · ' + m.role : '') : m.project_name || id,
              subtitle: [r.doc_type === 'cv' ? 'CV' : r.doc_type === 'project' ? 'Past project' : 'Tool', m.client_sector, (m.tech_stack || []).slice(0, 4).join(', '), id].filter(Boolean).join(' · '),
              trailing: h('span', { className: 'uip-trail' }, h('span', { className: 'meta uip-muted uip-num' }, 'Similarity ' + r.similarity.toFixed(2)), h(F.Fit, { level: copy.fitLevel(r.similarity) })),
              onClick: function () { open[1](isOpen ? null : id); },
            }),
            isOpen ? h(F.EvidenceLayer, { source: ev.fromHit(r, id), className: 'uip-evidence', onClose: function () { open[1](null); } }) : null);
        }),
        h('p', { className: 'meta uip-muted uip-cap' }, 'Preview: recorded retrieval hits, filtered by your words.'));
    }

    return h(ui.WorkPage, { world: 'sage', rail: 'library', chip: 'Library', kicker: 'Knowledge base', title: 'Consultants, Projects and Tools' },
      h('div', { className: 'uip-cols' },
        h(F.Card, { density: 'compact', className: 'uip-queue uip-stack-s' },
          h(F.TreeNav, { label: 'Record type', sections: [{ id: 'type', title: 'Record type', items: typeItems(s.stats) }], value: type, onChange: function (/** @type {string} */ id) { setQuery('type', id); } }),
          h('div', { className: 'uip-pad uip-stack-s' },
            h(F.TextField, { label: 'Results', type: 'number', min: 1, max: 20, value: k[0], onChange: function (/** @type {any} */ e) { k[1](e.target.value); }, error: kErr, hint: '1 to 20.' }),
            h(F.TextField, { label: 'Minimum similarity', type: 'number', min: 0, max: 1, step: 0.05, value: min[0], onChange: function (/** @type {any} */ e) { min[1](e.target.value); }, error: minErr, hint: '0 to 1. Strong matches start at 0.55.' }))),
        h('div', { className: 'uip-stack' },
          h(F.SearchBar, { key: type + text, scopes: SCOPES[type] || SCOPES.all, defaultValue: text, onSubmit: function (/** @type {string} */ v) { setQuery('q', v.trim()); } }),
          tenders,
          body)));
  }

  /* ------------------------------------------------------------ Security */

  var CONTROLS = [
    { icon: 'link', title: 'Access between services', items: [
      ['Internal token on every call', 'Every endpoint except health checks requires the internal service token. An unset token refuses everyone rather than letting everyone in.', 'shared/auth.py'],
      ['Constant-time token check', 'Tokens are compared in constant time, so response timing reveals nothing about a guess.', 'shared/auth.py'],
      ['No credentials in the interface', 'This interface stores no keys or tokens; the token belongs to the services and the workflow that calls them.', 'ui-preview'],
    ] },
    { icon: 'check-circle', title: 'AI that shows its evidence', items: [
      ['Quarantined web reading', 'The only model that reads web pages has no tools, gets untrusted text apart from its instructions, and must answer in a fixed shape. Any deviation yields zero facts.', 'research/tests/test_injection_resistance.py'],
      ['Confidence from distinct sources', 'Research confidence is computed from how many separate sources agree, never reported by the model. A repeated fact is not a new source.', 'research/runner.py'],
      ['Citations limited to retrieved records', 'Each writing step may cite only the records in its own inputs; a reply citing anything else is rejected and retried.', 'proposal/compose.py'],
      ['Facts written by code', 'Every score, name, year and price in the deck is copied in by code, not written by the model.', 'proposal/schemas.py'],
      ['Validator gate', 'A deck with overflowing text, overlaps, off-palette colours or an unretrieved citation is refused before any file is written.', 'proposal/validate.py'],
      ['Grounding verifier', 'A judge on a different model than the writers rates each claim against its source; partial and unsupported claims become bid warnings. It runs when PROPOSAL_VERIFIER_LLM_MODEL is set, and every deck says whether it ran.', 'proposal/verifier.py', 'optional'],
    ] },
    { icon: 'filter', title: 'Input and web fetching', items: [
      ['Strict schemas and bounds', 'Titles up to 400 characters, tender text up to 20,000, up to 100 requirements; unknown fields are reported, unexpected request fields refused.', 'detection/normalize.py'],
      ['Unsafe characters removed', 'Control and invisible direction characters are stripped at intake and flagged on the tender.', 'detection/normalize.py'],
      ['Untrusted text cleaned at every entry', 'SAM.gov descriptions pass through the same cleaner as tender intake before they reach the pipeline.', 'ingestion/utils/helpers.py'],
      ['Safe file names', 'Tender IDs must match a strict pattern before they name any file, so a path cannot escape the output folder.', 'proposal/main.py'],
      ['Server-side request forgery guard', 'Web fetches allow http and https only, block private and loopback addresses and never follow redirects. Research, TED and SAM.gov ingestion share this client; research web fetches are capped at 256 KiB (FETCH_MAX_BYTES), TED API responses at 4 MiB and SAM.gov API responses at 64 MiB.', 'research/tools/fetch.py'],
      ['Duplicate detection', 'Near-identical tenders are flagged as possible duplicates instead of being researched twice.', 'shared/dedup.py'],
    ] },
    { icon: 'history', title: 'Logs and traceability', items: [
      ['Request ID on every response', 'Each response, including failures, carries a request ID that ties one action’s log lines together across services.', 'shared/errors.py'],
      ['One error format', 'Every service answers failures with the same code, message, field and a retryable flag, so the interface knows when retrying can help.', 'shared/errors.py'],
      ['Secrets scrubbed from logs', 'The model key, search key, service token and SAM.gov API key (INGEST_API_KEYS) are removed from log messages and tracebacks before any handler sees them, in the research extractor and in every service’s error logs.', 'shared/redaction.py'],
      ['Tamper-evident audit log', 'Research steps are logged one line each, hashed with SHA-256 per entry and grouped by a run ID.', 'research/audit.py'],
    ] },
    { icon: 'layers', title: 'Data and supply chain', items: [
      ['Row-level security on the knowledge base', 'Row-level security is on, the search function runs with the caller’s rights and a pinned search path, and public roles have no privileges.', 'sql/schema.sql'],
      ['Scanned on every change', 'Secret scanning, Bandit, Semgrep and dependency audits run in CI and weekly, with actions pinned to exact commits.', '.github/workflows/security.yml'],
      ['Hardened containers', 'Services run as a non-root user on a pinned base image with locked dependencies.', 'Dockerfile'],
    ] },
    { icon: 'clock', title: 'Budget protection', items: [
      ['One run at a time per tender', 'Concurrent requests for the same research or deck share a single run instead of paying twice.', 'research/main.py · proposal/main.py'],
      ['Closed tenders skipped', 'Research does not spend search or model budget on a tender whose deadline has passed, unless asked to.', 'research/runner.py'],
      ['Per-tender cache', 'An unchanged repeat request is served from the stored result.', 'research/runner.py'],
    ] },
  ];

  function Security() {
    var total = CONTROLS.reduce(function (n, g) { return n + g.items.filter(function (it) { return it[3] !== 'optional'; }).length; }, 0);
    return h(ui.WorkPage, { rail: 'security', kicker: 'Built into every service', title: 'Security Controls' },
      h(F.AdvisoryStrip, { tone: 'good', icon: 'check-circle' }, total + ' controls in place across detection, research, retrieval, proposal and ingestion.'),
      h('div', { className: 'uip-ov-panels uip-sec' },
        CONTROLS.map(function (g, i) {
          return h(F.Card, { key: g.title, className: 'uip-ov-labelled fn-enter', style: { '--i': i } },
            h(F.FloatingLabel, { icon: g.icon }, g.title),
            h('ul', { className: 'uip-ctls' }, g.items.map(function (it) {
              return h('li', { key: it[0], className: 'uip-ctl' },
                h('div', null,
                  h('p', { className: 'ui-strong' }, it[0]),
                  h('p', { className: 'ui uip-muted' }, it[1]),
                  h('code', { className: 'uip-code' }, it[2])),
                it[3] === 'optional' ? h(F.Chip, { tone: 'stale', size: 'sm' }, 'Optional') : h(F.Status, { status: 'good', size: 'sm' }, 'In place'));
            })));
        })));
  }

  /* ------------------------------------------------------------ Settings */

  var ON_OFF = [{ value: 'on', label: 'On', tone: 'good' }, { value: 'off', label: 'Off', tone: 'stale' }];
  var INTAKE = [
    { id: 'TED', title: 'TED EU', detail: 'Fetch Notices · POST /ingest/TED, then each notice to detection. 30 per page by default (INGEST_LIMITS).', icon: 'globe' },
    { id: 'SAM', title: 'SAM.gov (USA)', detail: 'Fetch Notices · POST /ingest/SAM, then each notice to detection. Needs a SAM API key in INGEST_API_KEYS.', icon: 'radar' },
    { id: 'simulated_feed', title: 'Simulated feed', detail: 'Load Simulated Feed · POST /tenders/seed', icon: 'inbox' },
    { id: 'manual', title: 'Manual intake', detail: 'Add Tender · POST /tenders/ingest', icon: 'pen-line' },
  ];
  var N8N = 'http://localhost:5678';

  /** Light or dark, applied at once. Two Final buttons on a sunken track: the pressed one is raised. */
  function ThemeSwitch() {
    var cur = React.useState(document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light');
    function pick(/** @type {string} */ v) {
      store.setPref('theme', v);
      ui.applyTheme(v);
      cur[1](v);
    }
    return h('div', { className: 'uip-switch', role: 'group', 'aria-label': 'Theme' },
      [{ v: 'light', label: 'Light' }, { v: 'dark', label: 'Dark' }].map(function (o) {
        var on = cur[0] === o.v;
        return h(F.Button, { key: o.v, size: 'sm', variant: on ? 'secondary' : 'tertiary', 'aria-pressed': on, onClick: function () { pick(o.v); } }, o.label);
      }));
  }

  /** A labelled row with its control at the far end: the Settings layout unit. */
  function Row(/** @type {{ icon?: string, title: string, detail?: any, children?: any }} */ p) {
    return h('li', { className: 'uip-ctl' },
      h('div', { className: 'uip-inline uip-ctl-main' },
        p.icon ? h(F.Icon, { name: p.icon, size: 18, className: 'uip-muted' }) : null,
        h('div', null, h('p', { className: 'ui-strong' }, p.title), p.detail ? h('p', { className: 'ui uip-muted' }, p.detail) : null)),
      p.children);
  }

  function Group(/** @type {{ icon: string, title: string, i: number, children: any }} */ p) {
    return h(F.Card, { className: 'uip-ov-labelled fn-enter', style: { '--i': p.i } },
      h(F.FloatingLabel, { icon: p.icon }, p.title),
      h('ul', { className: 'uip-ctls' }, p.children));
  }

  function Settings() {
    var s = store.useStore();
    var pr = s.prefs;
    React.useEffect(function () { if (!s.health) store.checkHealth(); }, []);
    function source(/** @type {string} */ id, /** @type {string} */ v) {
      store.setPref('sources', Object.assign({}, pr.sources, { [id]: v === 'on' }));
    }
    var tedErr = !Number.isInteger(Number(pr.tedPage)) || Number(pr.tedPage) < 1 ? 'Enter a page number of 1 or more.' : null;
    var kErr = !Number.isInteger(Number(pr.topK)) || pr.topK < 1 || pr.topK > 20 ? 'Choose 1 to 20 results.' : null;
    var minErr = isNaN(Number(pr.minSimilarity)) || pr.minSimilarity < 0 || pr.minSimilarity > 1 ? 'Choose a value from 0 to 1.' : null;
    var health = s.health;
    var down = health ? health.services.filter(function (x) { return !x.up; }).length : 0;

    return h(ui.WorkPage, { rail: 'settings', kicker: 'Saved in this browser', title: 'Settings' },
      h('div', { className: 'uip-ov-panels uip-sec' },
        h(Group, { icon: 'eye', title: 'Appearance', i: 0 },
          h(Row, { title: 'Theme', detail: 'Starts from your system setting; your choice is kept in this browser.' }, h(ThemeSwitch))),

        h(Group, { icon: 'inbox', title: 'Tender sources', i: 0 },
          INTAKE.map(function (x) {
            return h(Row, { key: x.id, icon: x.icon, title: x.title, detail: x.detail },
              h(F.StatusSelect, { value: pr.sources[x.id] === false ? 'off' : 'on', options: ON_OFF, label: x.title + ' on Tenders', onChange: function (/** @type {string} */ v) { source(x.id, v); } }));
          }),
          h(Row, { icon: 'grid', title: 'Google Sheet', detail: 'Read on a schedule by the n8n Phase 1 workflow, then sent to detection.' },
            h('a', { className: 'fn-link ui', href: N8N, target: '_blank', rel: 'noopener noreferrer' }, 'Open n8n')),
          h('li', null, h(F.TextField, { label: 'First page to fetch', type: 'number', min: 1, value: String(pr.tedPage), error: tedErr, hint: 'Used by TED EU and SAM.gov.', onChange: function (/** @type {any} */ e) { store.setPref('tedPage', Number(e.target.value)); } }))),

        h(Group, { icon: 'building', title: 'Research', i: 1 },
          h(Row, { title: 'Closed tenders', detail: 'Skipping saves search and model budget. Research anyway sends force=true.' },
            h(F.StatusSelect, { value: pr.researchClosed ? 'on' : 'off', options: [{ value: 'off', label: 'Skip', tone: 'good' }, { value: 'on', label: 'Research anyway', tone: 'stale' }], label: 'Research closed tenders', onChange: function (/** @type {string} */ v) { store.setPref('researchClosed', v === 'on'); } })),
          h(Row, { title: 'Confidence', detail: 'Computed from how many distinct sources agree, never by the model. Not adjustable.' })),

        h(Group, { icon: 'library', title: 'Library search', i: 2 },
          h('li', null, h(F.TextField, { label: 'Results per search', type: 'number', min: 1, max: 20, value: String(pr.topK), error: kErr, hint: '1 to 20.', onChange: function (/** @type {any} */ e) { store.setPref('topK', Number(e.target.value)); } })),
          h('li', null, h(F.TextField, { label: 'Minimum similarity', type: 'number', min: 0, max: 1, step: 0.05, value: String(pr.minSimilarity), error: minErr, hint: '0 to 1. Strong matches start at 0.55.', onChange: function (/** @type {any} */ e) { store.setPref('minSimilarity', Number(e.target.value)); } }))),

        h(Group, { icon: 'check-circle', title: 'Deck checks', i: 3 },
          h(Row, { title: 'Strict claim check', detail: 'Also checks every written sentence for claims its sources do not contain. Off by default; the grounding verifier is set by the operator and each deck says whether it ran.' },
            h(F.StatusSelect, { value: pr.claimCheck ? 'on' : 'off', options: ON_OFF, label: 'Strict claim check', onChange: function (/** @type {string} */ v) { store.setPref('claimCheck', v === 'on'); } }))),

        h(Group, { icon: 'scale', title: 'Fit thresholds', i: 4 },
          h(Row, { title: 'Strong fit', detail: 'Match score 0.55 or more.' }, h(F.Fit, { level: 'strong' })),
          h(Row, { title: 'Partial fit', detail: 'Match score 0.40 to 0.55. Worth a human check.' }, h(F.Fit, { level: 'partial' })),
          h(Row, { title: 'Gap', detail: 'Below 0.40. When every requirement is a gap, the deck becomes a no-bid.' }, h(F.Fit, { level: 'gap' })),
          h('li', null, h('p', { className: 'meta uip-muted' }, 'Set in code (proposal/schemas.py) so a score always maps to the same label. 7 rows fit on the matrix slide; the rest go to the CSV.'))),

        h(Group, { icon: 'radar', title: 'Service health', i: 5 },
          health ? health.services.map(function (x) {
            return h(Row, { key: x.id, title: x.name, detail: 'GET ' + x.path + ' · port ' + x.port },
              x.up ? h(F.Status, { status: 'good', size: 'sm' }, 'Up') : h(F.Status, { status: 'risk', size: 'sm' }, 'Not responding'));
          }) : null,
          h('li', { className: 'uip-ctl' },
            h('p', { className: 'meta uip-muted' }, health ? (down ? down + ' not responding · ' : 'All up · ') + 'checked ' + ui.date(health.checkedAt, { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : 'Checking…'),
            h(F.Button, { size: 'sm', icon: 'refresh', loading: !!s.running.health, onClick: function () { store.checkHealth(); } }, s.running.health ? 'Checking…' : 'Check Again'))),

        h(Group, { icon: 'link', title: 'Integrations', i: 6 },
          h(Row, { icon: 'grid', title: 'Google Sheets', detail: 'Live through n8n (OliveSoft is an n8n Certified Partner).' }, h(F.Status, { status: 'good', size: 'sm' }, 'Available')),
          h(Row, { icon: 'briefcase', title: 'Salesforce', detail: 'Push tenders and decks to opportunities. OliveSoft is a Salesforce Integration Partner.' }, h(ui.FutureTag, { reason: ui.FUTURE.salesforce })),
          h(Row, { icon: 'folder', title: 'Google Drive', detail: 'Save decks next to the tender folder. OliveSoft is a Google Cloud Partner.' }, h(ui.FutureTag, { reason: ui.FUTURE.googleDrive })),
          h(Row, { icon: 'message', title: 'Email and push alerts', detail: 'Today alerts live on the Alerts screen.' }, h(ui.FutureTag, { reason: ui.FUTURE.pushNotifications }))),

        h(Group, { icon: 'users', title: 'Team and access', i: 7 },
          h(Row, { icon: 'user', title: 'Single sign-on', detail: 'Sign in with the company identity provider.' }, h(ui.FutureTag, { reason: ui.FUTURE.sso })),
          h(Row, { icon: 'users', title: 'Team workspace', detail: 'Review one deck together, without version chaos.' }, h(ui.FutureTag, { reason: ui.FUTURE.collaboration })),
          h(Row, { icon: 'sliders', title: 'Server settings', detail: 'Tokens, models and service addresses stay with the operator.' }, h(ui.FutureTag, { reason: ui.FUTURE.serverSettings })))));
  }

  /* -------------------------------------------------------------- Alerts */

  var GROUPS = [
    { id: 'security', title: 'Security', icon: 'alert-triangle', status: 'risk' },
    { id: 'attention', title: 'Needs attention', icon: 'alert-circle', status: 'stale' },
    { id: 'info', title: 'For your information', icon: 'info', status: 'stale' },
  ];

  function Alerts() {
    store.useStore();
    var list = store.alerts();
    var body = list.length
      ? GROUPS.map(function (g, i) {
        var items = list.filter(function (a) { return a.group === g.id; });
        if (!items.length) return null;
        return h(F.Card, { key: g.id, className: 'uip-ov-labelled fn-enter', style: { '--i': i } },
          h(F.FloatingLabel, { icon: g.icon }, g.title + ' · ' + items.length),
          h('div', { className: 'uip-ov-rows' }, items.map(function (a) {
            return h(F.ListRow, { key: a.id, variant: 'flat', href: ui.href(a.href), title: a.title, subtitle: a.detail, trailing: h(F.Status, { status: /** @type {any} */ (g.status), size: 'sm' }, g.id === 'security' ? 'Check' : 'Open') });
          })));
      })
      : h(F.Card, null, h(F.EmptyState, { world: 'peach', illustration: 'review', title: 'No Alerts Right Now' },
        'Hidden characters in a tender, possible duplicates, refused decks and degraded research runs show up here as soon as a service reports them.'));
    return h(ui.WorkPage, {
      rail: 'alerts', kicker: 'From detection, research and the deck checks', title: 'Alerts',
      actions: h('span', { className: 'meta uip-muted uip-inline' }, 'Email and push', h(ui.FutureTag, { reason: ui.FUTURE.pushNotifications })),
    }, h('div', { className: 'uip-stack' }, body));
  }

  window.UIP.screens.library = Library;
  window.UIP.screens.security = Security;
  window.UIP.screens.settings = Settings;
  window.UIP.screens.alerts = Alerts;
})();

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadStore(api, win) {
  const context = { window: Object.assign({ UIP: { api, copy: {} } }, win) };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'src', 'store.js'), 'utf8'), context);
  return context.window.UIP.store;
}

test('a notice is sent with its country, type, publication date and links', () => {
  const store = loadStore({});
  const links = { pdfs: { ENG: 'https://ted.example/n.pdf' } };
  const body = store.noticePayload({
    id: '42-2026', title: 'T', issuer: 'I', issuer_country: 'FRA', source: 'TED', notice_type: 'cn-standard',
    deadline: '2026-12-01', published_at: '2026-10-22', raw_text: 'text', links,
  });

  assert.equal(body.id, 'ted-42-2026');
  assert.equal(body.issuer_country, 'FRA');
  assert.equal(body.notice_type, 'cn-standard');
  assert.equal(body.published_at, '2026-10-22');
  assert.deepEqual(body.links, links);
});

test('an insights run is stored per tender and served back by insightsOf', async () => {
  const run = { run_id: 7, insights: { tender_id: 'tender-001', status: 'complete' }, trace: [] };
  const posts = [];
  const api = { get: () => Promise.resolve({}), post: (url) => { posts.push(url); return Promise.resolve(run); } };
  const store = loadStore(api);
  assert.equal(store.insightsOf('tender-001'), null);
  await store.runInsights('tender-001');
  assert.deepEqual(posts, ['/api/insights/tender-001']);
  assert.equal(store.insightsOf('tender-001'), run);
});

const GENERATED_AT = '2026-01-01T00:00:00+00:00';

function reviewHarness(getReview) {
  const puts = [];
  const api = {
    get: (url) => (url.endsWith('/review') ? getReview() : Promise.resolve({})),
    put: (url, body) => { puts.push(body); return Promise.resolve(Object.assign({ signed_off_at: null }, body)); },
  };
  const store = loadStore(api);
  store.get().proposals = { t1: { generated_at: GENERATED_AT, kind: 'proposal' } };
  return { store, puts };
}

test('a review save loads the stored review first, so it cannot wipe other sections or the sign-off', async () => {
  const stored = { deck_generated_at: GENERATED_AT, sections: { team: 'approved' }, signed_off_by: 'Ama', signed_off_at: 'x' };
  const { store, puts } = reviewHarness(() => Promise.resolve(stored));
  await store.setSectionStatus('t1', 'summary', 'review');
  assert.deepEqual(JSON.parse(JSON.stringify(puts[0].sections)), { team: 'approved', summary: 'review' });
  assert.equal(puts[0].signed_off_by, 'Ama');
});

test('a review save is refused, and nothing is written, while the review cannot be loaded', async () => {
  const { store, puts } = reviewHarness(() => Promise.reject(new Error('down')));
  await assert.rejects(store.setSectionStatus('t1', 'summary', 'review'), /down/);
  await assert.rejects(store.signOff('t1', 'Ama'), /down/);
  assert.equal(puts.length, 0);
});

test('a second send while one is in flight posts nothing more', async () => {
  let posts = 0;
  let release;
  const api = {
    get: () => Promise.resolve([]),
    post: () => { posts += 1; return new Promise((resolve) => { release = () => resolve({ results: [] }); }); },
  };
  const store = loadStore(api);
  const first = store.sendNotices([]);
  const second = store.sendNotices([]);
  release();
  await Promise.all([first, second]);
  assert.equal(posts, 1);
  const third = store.sendNotices([]);
  release();
  await third;
  assert.equal(posts, 2);
});

test('a search finds tenders whose title, buyer, id or country hold every word', () => {
  const store = loadStore({});
  const tenders = [
    { id: 'tender-001', title: 'Global HRIS Integration Across 11 Countries', issuer: 'Meridian Group', issuer_country: 'FRA' },
    { id: 'ted-42-2026', title: 'Cloud hosting', issuer: 'Ville de Lyon', issuer_country: 'FRA' },
    { id: 'tender-003', title: 'Payroll migration', issuer: 'Meridian Group', issuer_country: null },
  ];
  const ids = (text) => Array.from(store.matchTenders(tenders, text), (t) => t.id);
  assert.deepEqual(ids('hris integration'), ['tender-001']);
  assert.deepEqual(ids('MERIDIAN'), ['tender-001', 'tender-003']);
  assert.deepEqual(ids('ted-42'), ['ted-42-2026']);
  assert.deepEqual(ids('fra cloud'), ['ted-42-2026']);
  assert.deepEqual(ids('meridian cloud'), []);
  assert.deepEqual(ids('   '), []);
});

function pipelineHarness(statuses) {
  const timers = [];
  const gets = [];
  const posts = [];
  const api = {
    get: (url) => {
      gets.push(url);
      if (url.startsWith('/api/pipeline/runs/')) {
        const next = statuses.shift();
        return next instanceof Error ? Promise.reject(next.captured) : Promise.resolve(next);
      }
      return Promise.resolve(url === '/api/tenders' ? [{ id: 'ted-1' }] : {});
    },
    post: (url, body) => { posts.push({ url, body }); return Promise.resolve({ execution_id: 41 }); },
  };
  const store = loadStore(api, { setTimeout: (fn) => { timers.push(fn); } });
  async function tick() {
    timers.shift()();
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
  }
  return { store, timers, gets, posts, tick };
}

function failed(status) {
  const e = new Error('failed');
  e.captured = { status, request_id: '', body: { error: { code: 'NOT_FOUND', message: 'x', field: null, retryable: false, request_id: null } } };
  return e;
}

test('a pipeline run re-reads the services every tick and stops when n8n reports success', async () => {
  const { store, timers, gets, posts, tick } = pipelineHarness([{ status: 'running', workflow_id: 'w1' }, { status: 'success' }]);
  await store.runPipeline();
  assert.equal(posts[0].url, '/api/pipeline/run');
  assert.equal(store.get().running.pipeline, true);
  assert.equal(store.get().pipeline.id, '41');
  await tick();
  assert.ok(gets.includes('/api/pipeline/runs/41') && gets.includes('/api/proposals'));
  assert.equal(store.get().tenders.length, 1);
  assert.equal(store.get().pipeline.workflowId, 'w1');
  assert.equal(timers.length, 1);
  await tick();
  assert.equal(store.get().pipeline.status, 'success');
  assert.equal(store.get().running.pipeline, undefined);
  assert.equal(timers.length, 0);
});

test('a second click while a run is in flight starts nothing more', async () => {
  const { store, posts } = pipelineHarness([]);
  await store.runPipeline();
  await store.runPipeline();
  assert.equal(posts.length, 1);
});

test('a run n8n has not saved yet keeps being watched', async () => {
  const { store, timers, tick } = pipelineHarness([failed(404), { status: 'running' }]);
  await store.runPipeline();
  await tick();
  assert.equal(store.get().pipeline.status, 'running');
  assert.equal(store.get().pipeline.tracked, true);
  assert.equal(timers.length, 1);
});

test('without an n8n API key the run keeps refreshing but is marked untracked', async () => {
  const { store, timers, tick } = pipelineHarness([failed(503)]);
  await store.runPipeline();
  await tick();
  assert.equal(store.get().pipeline.tracked, false);
  assert.equal(timers.length, 1);
});

test('a failed run names the node that stopped it', async () => {
  const { store, tick } = pipelineHarness([{ status: 'error', error: 'connect ECONNREFUSED', failed_node: 'Fetch One TED Page', workflow_id: 'w1' }]);
  await store.runPipeline();
  await tick();
  const run = store.get().pipeline;
  assert.equal(run.status, 'error');
  assert.equal(run.workflowId, 'w1');
  assert.equal(run.error.body.error.message, 'Fetch One TED Page: connect ECONNREFUSED');
  assert.equal(store.get().running.pipeline, undefined);
});

test('a webhook that refuses the start ends the run with its error', async () => {
  const err = failed(404).captured;
  const api = { post: () => Promise.reject(err), get: () => Promise.resolve([]) };
  const refused = loadStore(api, { setTimeout: () => {} });
  await assert.rejects(refused.runPipeline());
  assert.equal(refused.get().pipeline.status, 'error');
  assert.equal(refused.get().pipeline.error, err);
  assert.equal(refused.get().running.pipeline, undefined);
});

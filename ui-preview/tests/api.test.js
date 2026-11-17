const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const context = { window: {} };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'src', 'api.js'), 'utf8'), context);
const api = context.window.UIP.api;

test('an envelope passes through', () => {
  const c = api.toCaptured(404, '{"error":{"code":"NOT_FOUND","message":"Tender not found","field":null,"retryable":false,"request_id":"r1"}}', 'r1');
  assert.equal(c.body.error.code, 'NOT_FOUND');
  assert.equal(c.status, 404);
  assert.equal(c.request_id, 'r1');
});

test('FastAPI detail is wrapped', () => {
  assert.equal(api.toCaptured(404, '{"detail":"Not Found"}', null).body.error.code, 'NOT_FOUND');
});

test('non-JSON 502 becomes retryable UPSTREAM_UNAVAILABLE', () => {
  const e = api.toCaptured(502, '<html>Bad Gateway</html>', null).body.error;
  assert.equal(e.code, 'UPSTREAM_UNAVAILABLE');
  assert.equal(e.retryable, true);
});

test('a request that never reached the server is retryable UPSTREAM_UNAVAILABLE', () => {
  const c = api.toCaptured(0, '', null);
  assert.equal(c.body.error.code, 'UPSTREAM_UNAVAILABLE');
  assert.equal(c.body.error.retryable, true);
});

test('the response request id fills an envelope that lacks one', () => {
  const c = api.toCaptured(503, '{"error":{"code":"UPSTREAM_UNAVAILABLE","message":"down","field":null,"retryable":true,"request_id":null}}', 'hdr-1');
  assert.equal(c.request_id, 'hdr-1');
  assert.equal(c.body.error.request_id, 'hdr-1');
});

test('a wrapped detail keeps its text and takes the header request id', () => {
  const c = api.toCaptured(401, '{"detail":"Not authenticated"}', 'r2');
  assert.equal(c.body.error.code, 'UNAUTHORIZED');
  assert.equal(c.body.error.message, 'Not authenticated');
  assert.equal(c.body.error.request_id, 'r2');
});

test('a list of validation details becomes BAD_REQUEST', () => {
  const c = api.toCaptured(422, '{"detail":[{"loc":["body","page"],"msg":"field required"}]}', null);
  assert.equal(c.body.error.code, 'BAD_REQUEST');
  assert.equal(c.body.error.retryable, false);
});

test('a non-JSON 500 is a retryable INTERNAL', () => {
  const e = api.toCaptured(500, 'oops', null).body.error;
  assert.equal(e.code, 'INTERNAL');
  assert.equal(e.retryable, true);
});

test('a deck file url encodes the tender id and the file name', () => {
  assert.equal(api.fileUrl('sam-abc/1', 'Deck v2.pptx'), '/api/files/sam-abc%2F1/Deck%20v2.pptx');
});

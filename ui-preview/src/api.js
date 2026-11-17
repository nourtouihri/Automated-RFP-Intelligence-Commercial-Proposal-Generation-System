// @ts-check
// The one door to the services: calls the UI proxy (/api/*) and turns every failure
// into the shared error envelope, so screens only ever handle a CapturedError.
window.UIP = window.UIP || {};

window.UIP.api = (function () {
  var UNAVAILABLE = [502, 503, 504];
  var CODE_BY_STATUS = { 400: 'BAD_REQUEST', 401: 'UNAUTHORIZED', 404: 'NOT_FOUND', 409: 'BAD_REQUEST', 413: 'PAYLOAD_TOO_LARGE', 422: 'BAD_REQUEST' };

  function parse(/** @type {string} */ text) {
    try { return JSON.parse(text); } catch (e) { return null; }
  }

  /**
   * Builds a CapturedError from a failed response. An envelope passes through; FastAPI's
   * `{"detail"}` and non-JSON bodies (a proxy's HTML page, a dropped connection as status 0)
   * are wrapped so the screens never see a second shape.
   * @param {number} status @param {string} text @param {string | null} requestId @returns {import('./types').CapturedError}
   */
  function toCaptured(status, text, requestId) {
    var body = parse(text);
    var envelope = body && typeof body === 'object' && body.error && typeof body.error === 'object' && body.error.code ? body.error : null;
    if (!envelope) {
      var unavailable = status === 0 || UNAVAILABLE.indexOf(status) >= 0;
      var detail = body && typeof body === 'object' && typeof body.detail === 'string' ? body.detail : null;
      envelope = {
        code: unavailable ? 'UPSTREAM_UNAVAILABLE' : CODE_BY_STATUS[status] || 'INTERNAL',
        message: detail || (status === 0 ? 'The server could not be reached' : 'The server answered ' + status + ' without a usable body'),
        field: null,
        retryable: unavailable || status >= 500,
        request_id: null,
      };
    }
    var id = envelope.request_id || requestId || null;
    envelope.request_id = id;
    return { status: status, request_id: id || '', body: { error: envelope } };
  }

  /** @param {string} method @param {string} path @param {Record<string, any> | undefined} params @param {any} body */
  function send(method, path, params, body) {
    var query = new URLSearchParams();
    Object.keys(params || {}).forEach(function (k) {
      var v = /** @type {Record<string, any>} */ (params)[k];
      if (v !== undefined && v !== null) query.set(k, String(v));
    });
    var url = path + (query.toString() ? '?' + query.toString() : '');
    /** @type {RequestInit} */
    var init = { method: method, headers: { Accept: 'application/json' } };
    if (body !== undefined) {
      init.headers = { Accept: 'application/json', 'Content-Type': 'application/json' };
      init.body = JSON.stringify(body);
    }
    return fetch(url, init).then(
      function (res) {
        return res.text().then(function (text) {
          var id = res.headers.get('X-Request-ID');
          if (!res.ok) throw toCaptured(res.status, text, id);
          if (!text) return null;
          try { return JSON.parse(text); } catch (e) { throw toCaptured(502, text, id); }
        });
      },
      function () { throw toCaptured(0, '', null); }
    );
  }

  /** The proxy's download route for a deck file; both parts are encoded, so an odd tender id cannot change the path. */
  function fileUrl(/** @type {string} */ tenderId, /** @type {string} */ name) {
    return '/api/files/' + encodeURIComponent(tenderId) + '/' + encodeURIComponent(name);
  }

  /** Fetches a file and hands it to the browser as a download. A failed response rejects with a CapturedError, never a saved error page. */
  function download(/** @type {string} */ url, /** @type {string} */ name) {
    return fetch(url).then(
      function (res) {
        if (!res.ok) return res.text().then(function (text) { throw toCaptured(res.status, text, res.headers.get('X-Request-ID')); });
        return res.blob().then(function (blob) {
          var href = URL.createObjectURL(blob);
          var a = document.createElement('a');
          a.href = href;
          a.download = name;
          document.body.appendChild(a);
          a.click();
          a.remove();
          setTimeout(function () { URL.revokeObjectURL(href); }, 10000);
        });
      },
      function () { throw toCaptured(0, '', null); }
    );
  }

  return {
    toCaptured: toCaptured,
    fileUrl: fileUrl,
    download: download,
    /** @param {string} path @param {Record<string, any>=} params */
    get: function (path, params) { return send('GET', path, params, undefined); },
    /** @param {string} path @param {any=} body @param {Record<string, any>=} params */
    post: function (path, body, params) { return send('POST', path, params, body === undefined ? {} : body); },
    /** @param {string} path @param {any} body */
    patch: function (path, body) { return send('PATCH', path, undefined, body); },
    /** @param {string} path @param {any} body */
    put: function (path, body) { return send('PUT', path, undefined, body); },
  };
})();

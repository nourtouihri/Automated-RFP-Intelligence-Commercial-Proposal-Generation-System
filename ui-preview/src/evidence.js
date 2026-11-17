// @ts-check
// Evidence: turns knowledge-base record ids (CV-0028, PRJ-0001) into Final `Source`s,
// from the RAG hit that was retrieved for them.
window.UIP = window.UIP || {};

window.UIP.evidence = (function () {
  var h = React.createElement;
  var F = window.Final;
  var store = window.UIP.store;

  /** @param {import('./types').QueryResult | null} hit @param {string} id */
  function fromHit(hit, id) {
    if (!hit) return { title: id, type: 'txt', excerpt: 'Record ' + id + ' from the knowledge base. Its text is shown for decks generated in this session; generate the deck again to see it.' };
    var m = hit.metadata;
    var name = hit.doc_type === 'cv' ? (m.person || id) + (m.role ? ', ' + m.role : '') : m.project_name || id;
    return {
      title: id + ' · ' + name,
      type: 'txt',
      location: [hit.doc_type === 'cv' ? 'CV' : hit.doc_type === 'project' ? 'Past project' : 'Tool', m.client_sector].filter(Boolean).join(' · '),
      excerpt: hit.content,
    };
  }

  /** @param {string} tenderId @param {string | null} recordId @param {string=} requirement */
  function recordSource(tenderId, recordId, requirement) {
    if (!recordId) return null;
    return fromHit(store.hitFor(tenderId, requirement || '', recordId), recordId);
  }

  /** Numbered citation dots for the record ids a sentence rests on. */
  function citations(/** @type {string} */ tenderId, /** @type {string[]} */ ids) {
    return (ids || []).map(function (id, i) {
      return h(F.Citation, { key: id, n: i + 1, source: recordSource(tenderId, id) });
    });
  }

  /**
   * A requirement row's evidence layer. The record comes from the last generation when it is in memory;
   * otherwise the requirement is searched again and the layer says so while it waits.
   * @param {{ tenderId: string, requirement: string, recordId: string, onClose: () => void }} p
   */
  function Record(p) {
    var ui = window.UIP.ui;
    var known = store.hitFor(p.tenderId, p.requirement, p.recordId);
    var outcome = React.useState(/** @type {{ hit: import('./types').QueryResult | null } | { error: any } | null} */ (null));
    var attempt = React.useState(0);
    React.useEffect(function () {
      if (known) return undefined;
      var live = true;
      outcome[1](null);
      store.loadHit(p.tenderId, p.requirement, p.recordId).then(
        function (hit) { if (live) outcome[1]({ hit: hit }); },
        function (e) { if (live) outcome[1]({ error: e }); }
      );
      return function () { live = false; };
    }, [p.tenderId, p.requirement, p.recordId, attempt[0]]);

    var o = /** @type {any} */ (outcome[0]);
    if (known) return h(F.EvidenceLayer, { source: fromHit(known, p.recordId), className: 'uip-evidence', onClose: p.onClose });
    if (o && o.error) {
      return h('div', { className: 'uip-stack-s uip-evidence' },
        h(ui.ErrorNotice, { error: o.error, onRetry: function () { attempt[1](attempt[0] + 1); } }),
        h(F.Button, { variant: 'tertiary', size: 'sm', onClick: p.onClose }, 'Close'));
    }
    var excerpt = !o
      ? 'Loading the record…'
      : 'Record ' + p.recordId + ' is not among the top 5 results for this requirement now, so its text cannot be shown here.';
    return h(F.EvidenceLayer, { source: { title: p.recordId, type: 'txt', excerpt: excerpt }, className: 'uip-evidence', onClose: p.onClose });
  }

  return { fromHit: fromHit, recordSource: recordSource, citations: citations, Record: Record };
})();

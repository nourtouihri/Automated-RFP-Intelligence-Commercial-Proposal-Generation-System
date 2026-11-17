// @ts-check
// Entry point: loads the services' data, then picks the screen from the hash route and renders it.
(function () {
  var ui = window.UIP.ui;
  var store = window.UIP.store;
  var screens = window.UIP.screens;
  var pipeline = window.UIP.pipeline;
  var h = ui.h;
  var F = ui.F;

  /** A page-wide state shown before any screen has data to draw. */
  function Standby(/** @type {{ children: any }} */ p) {
    return h('div', { className: 'uip-stage uip-canvas' }, h('div', { className: 'uip-narrow' }, h(F.Card, null, p.children)));
  }

  function App() {
    var s = store.useStore();
    var route = ui.useRoute();
    React.useEffect(function () { store.load(); }, []);
    if (s.loading) {
      return h(Standby, null, h(ui.Runner, { icon: 'inbox', world: 'peach', label: 'Loading tenders…', detail: 'Reading your tenders, research and decks from the services.' }));
    }
    if (s.loadError) {
      return h(Standby, null, h('p', { className: 'heading' }, 'Tenders Could Not Load'), h(ui.ErrorNotice, { error: s.loadError, onRetry: function () { store.load(); } }));
    }
    var Screen = screens[route.screen] || screens.overview;
    return h(React.Fragment, null, h(Screen, { key: route.screen + '/' + (route.id || ''), route: route }), h(pipeline.Popout, { route: route }));
  }

  ReactDOM.createRoot(/** @type {HTMLElement} */ (document.getElementById('root'))).render(h(App));
})();

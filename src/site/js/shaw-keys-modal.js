// Lean wrapper around the shaw-keys submodule's ShawKeys.
// Assets are served at /shaw-keys/ so the widget resolves its own
// html/layout/png relative to import.meta.url — no urlResolver needed.
// Exposes window.ShawSpellKeyboard = { toggle, openSettings } for buttons.
// Cmd+K (Mac) / Ctrl+K toggles; openSettings opens the layout picker.
//
// The import pulls in custom-layouts.js and layout-editor.js as well: the
// library is one module graph, so the load order a host used to hand-write
// is now the browser's job.
//
// Root-relative, not './': this one file is served at /js/ by the site and at
// the docroot root by the editor, and both mount the library at
// /shaw-keys/.
import { ShawKeys } from '/shaw-keys/shaw-keys.js';

(function () {
  'use strict';

  function detectMac() {
    if (typeof navigator === 'undefined') return false;
    const p = navigator.platform || '', ua = navigator.userAgent || '';
    return /Mac|iPhone|iPad/.test(p) || /Mac|iPhone|iPad/.test(ua);
  }

  function isShortcutMatch(e) {
    if (e.key !== 'k' && e.key !== 'K') return false;
    return detectMac() ? (e.metaKey && !e.ctrlKey) : (e.ctrlKey && !e.metaKey);
  }

  function isInterceptable(el) {
    if (!el || typeof el.tagName !== 'string') return false;
    if (el.tagName === 'TEXTAREA') return true;
    if (el.tagName !== 'INPUT') return false;
    const t = (el.type || 'text').toLowerCase();
    return ['text', 'search', 'email', 'url', 'tel', 'password'].includes(t);
  }

  function create() {
    if (!ShawKeys._internal ||
        typeof ShawKeys._internal.openSettings !== 'function') {
      throw new Error('ShawSpellKeyboard: ShawKeys._internal.openSettings missing — shaw-keys moved it; re-point openSettings');
    }

    let host = document.getElementById('shaw-keys-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'shaw-keys-host';
      document.body.appendChild(host);
    }

    // init() renders blank keys until setLayout() registers labels + the
    // interception map — chain it so both arrive together.
    const ready = ShawKeys.init(host, '', null, {
      autoShowOnFocus: false,
      autoLigatures: true,
    }).then(function () {
      const st = ShawKeys.getState && ShawKeys.getState();
      return ShawKeys.setLayout((st && st.layout) || 'imperial');
    });

    // Capture phase + stopImmediatePropagation shadows Shaw Keys' own
    // bubble-phase Mac Cmd+K handler so the toggle never double-fires.
    document.addEventListener('keydown', function (e) {
      if (!isShortcutMatch(e)) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      ShawKeys.toggle();
    }, true);

    let attachReady = false;
    function attach(el) {
      if (el._shawKeysAttached) return;
      el._shawKeysAttached = true;
      ShawKeys.enableInterception(el);
    }
    function scan(root) {
      const list = root.querySelectorAll ? root.querySelectorAll('input, textarea') : [];
      list.forEach(function (el) { if (isInterceptable(el)) attach(el); });
      if (document.activeElement && isInterceptable(document.activeElement)) {
        attach(document.activeElement);
      }
    }

    ready.then(function () { attachReady = true; scan(document); });

    document.addEventListener('focusin', function (e) {
      const el = e.target;
      if (!isInterceptable(el) || el._shawKeysAttached) return;
      if (attachReady) { attach(el); return; }
      ready.then(function () { if (document.contains(el)) attach(el); });
    });

    // Editor builds filter chips + an edit modal after init — catch those.
    if (typeof MutationObserver !== 'undefined') {
      new MutationObserver(function (muts) {
        if (!attachReady) return;
        muts.forEach(function (m) {
          m.addedNodes && m.addedNodes.forEach(function (n) {
            if (n.nodeType !== 1) return;
            if (isInterceptable(n)) attach(n);
            const inner = n.querySelectorAll && n.querySelectorAll('input, textarea');
            if (inner) inner.forEach(function (el) { if (isInterceptable(el)) attach(el); });
          });
        });
      }).observe(document.body || document.documentElement,
                 { subtree: true, childList: true });
    }

    return {
      toggle: function () { ShawKeys.toggle(); },
      openSettings: function () {
        // The self-contained settings dialog lives on _internal; the public
        // mountSettings needs a host container we don't have.
        return ready.then(function () {
          return ShawKeys._internal.openSettings();
        });
      },
      ready: ready,
    };
  }

  let instance = null;
  window.ShawSpellKeyboard = {
    isMac: detectMac(),
    shortcutLabel: detectMac() ? 'Cmd+K' : 'Ctrl+K',
    toggle: function () {
      if (!instance) instance = create();
      instance.toggle();
    },
    openSettings: function () {
      if (!instance) instance = create();
      return instance.openSettings();
    },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { instance = create(); });
  } else {
    instance = create();
  }
})();

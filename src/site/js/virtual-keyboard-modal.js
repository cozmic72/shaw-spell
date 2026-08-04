// Lean wrapper around the shaw-type submodule's window.VirtualKeyboard.
// Assets are served at /virtual-keyboard/ so the widget resolves its own
// html/layout/png relative to its <script src> — no urlResolver needed.
// Exposes window.ShawSpellKeyboard = { toggle, openSettings } for buttons.
// Cmd+K (Mac) / Ctrl+K toggles; openSettings opens the layout picker.

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
    if (!window.VirtualKeyboard) {
      throw new Error('ShawSpellKeyboard: window.VirtualKeyboard missing — load /virtual-keyboard/virtual-keyboard.js first');
    }
    if (!window.VirtualKeyboard._internal ||
        typeof window.VirtualKeyboard._internal.openSettings !== 'function') {
      throw new Error('ShawSpellKeyboard: VirtualKeyboard._internal.openSettings missing — shaw-type moved it; re-point openSettings');
    }

    let host = document.getElementById('virtual-keyboard-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'virtual-keyboard-host';
      document.body.appendChild(host);
    }

    // init() renders blank keys until setLayout() registers labels + the
    // interception map — chain it so both arrive together.
    const ready = window.VirtualKeyboard.init(host, '', null, {
      autoShowOnFocus: false,
      autoLigatures: true,
    }).then(function () {
      const st = window.VirtualKeyboard.getState && window.VirtualKeyboard.getState();
      return window.VirtualKeyboard.setLayout((st && st.layout) || 'imperial');
    });

    // Capture phase + stopImmediatePropagation shadows shaw-type's own
    // bubble-phase Mac Cmd+K handler so the toggle never double-fires.
    document.addEventListener('keydown', function (e) {
      if (!isShortcutMatch(e)) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      window.VirtualKeyboard.toggle();
    }, true);

    let attachReady = false;
    function attach(el) {
      if (el._ssvkAttached) return;
      el._ssvkAttached = true;
      window.VirtualKeyboard.enableInterception(el);
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
      if (!isInterceptable(el) || el._ssvkAttached) return;
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
      toggle: function () { window.VirtualKeyboard.toggle(); },
      openSettings: function () {
        // The self-contained settings dialog lives on _internal; the public
        // mountSettings needs a host container we don't have.
        return ready.then(function () {
          return window.VirtualKeyboard._internal.openSettings();
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

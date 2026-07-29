/*
 * DripCut client behaviour.
 *
 * Injected into the document head by ui/app.py. Everything here is progressive
 * enhancement: if this file fails to load the interface still works, you just
 * lose the keyboard shortcuts, the palette and the resize handle.
 *
 * Two rules keep this robust against Gradio re-rendering its tree:
 *   1. Handlers are delegated from `document`, never bound to a Gradio node.
 *   2. Nothing is cached across renders except the overlays we create ourselves.
 *
 * The class contract comes from styles.css and is not invented here:
 * `.dc-palette` / `.dc-palette-backdrop` toggle the `dc-open` class, palette rows
 * are `.dc-palette-item` with `aria-selected`, and transient messages reuse the
 * server-side `.dc-note` cards. Sidebar width is driven through inline styles
 * because the stylesheet pins it with `!important`.
 *
 * There is deliberately no localStorage. Durable preferences (theme) live in
 * settings.json and are written by the server; sidebar width is session state and
 * is allowed to reset on reload.
 */
(function () {
  "use strict";

  if (window.__dripcutReady) return;
  window.__dripcutReady = true;

  var SIDEBAR_MIN = 188;
  var SIDEBAR_MAX = 380;
  var SIDEBAR_DEFAULT = 232;

  var reduceMotion = false;
  try {
    reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (e) {
    reduceMotion = false;
  }

  /* ------------------------------------------------------------------ utils */

  function $(selector, root) {
    return (root || document).querySelector(selector);
  }

  function $$(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function isTypingTarget(el) {
    if (!el) return false;
    var tag = (el.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
  }

  function closestOf(node, selector) {
    return node && node.closest ? node.closest(selector) : null;
  }

  /* --------------------------------------------------------------- messages */

  /* Reuses the stylesheet's `.dc-note` card. Only positioning is inline, because
     a floating message stack is layout rather than theme. */
  function messageLayer() {
    var layer = document.getElementById("dc-live-notes");
    if (!layer) {
      layer = document.createElement("div");
      layer.id = "dc-live-notes";
      layer.setAttribute("aria-live", "polite");
      layer.style.cssText =
        "position:fixed;right:18px;bottom:52px;z-index:130;width:min(320px,80vw);" +
        "display:flex;flex-direction:column-reverse;pointer-events:none";
      document.body.appendChild(layer);
    }
    return layer;
  }

  var NOTE_ICONS = { success: "\u2714", warning: "\u25b2", error: "\u2716", info: "\u00b7" };

  function notify(message, kind) {
    var level = NOTE_ICONS[kind] ? kind : "info";
    var note = document.createElement("div");
    note.className = "dc-note dc-note-" + level;
    note.style.transition = reduceMotion ? "none" : "opacity 200ms ease";
    var icon = document.createElement("div");
    icon.className = "dc-note-icon";
    icon.textContent = NOTE_ICONS[level];
    var body = document.createElement("div");
    body.className = "dc-note-body";
    var text = document.createElement("div");
    text.className = "dc-note-message";
    text.textContent = message;
    body.appendChild(text);
    note.appendChild(icon);
    note.appendChild(body);
    messageLayer().appendChild(note);

    window.setTimeout(function () {
      note.style.opacity = "0";
      window.setTimeout(function () {
        if (note.parentNode) note.parentNode.removeChild(note);
      }, reduceMotion ? 0 : 220);
    }, 2400);
  }

  window.dripcutNotify = notify;

  /* -------------------------------------------------------------- clipboard */

  function copyText(text) {
    if (!text) return;
    var label = text.length > 30 ? text.slice(0, 30) + "\u2026" : text;
    function ok() {
      notify("Copied " + label, "success");
    }
    function fail() {
      notify("Could not copy to the clipboard", "error");
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(ok, function () {
        if (legacyCopy(text)) ok();
        else fail();
      });
      return;
    }
    if (legacyCopy(text)) ok();
    else fail();
  }

  function legacyCopy(text) {
    var scratch = document.createElement("textarea");
    scratch.value = text;
    scratch.setAttribute("readonly", "readonly");
    scratch.style.cssText = "position:fixed;top:-1000px;opacity:0";
    document.body.appendChild(scratch);
    scratch.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }
    document.body.removeChild(scratch);
    return ok;
  }

  window.dripcutCopy = copyText;

  /* --------------------------------------------------------------- commands */

  /* The page publishes its commands as JSON in a script tag, so the palette needs
     no server round trip to open. Running a command clicks the real Gradio
     control, which keeps the server-side router the single source of truth. */
  function commands() {
    /* Injected by ui/app.py alongside this script. The JSON <script> block below
       is a fallback for hosts that keep it in the DOM. */
    if (Array.isArray(window.__dripcutCommands)) return window.__dripcutCommands;
    var holder = document.getElementById("dc-commands-data");
    if (!holder) return [];
    try {
      var parsed = JSON.parse(holder.textContent || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function clickTarget(elementId) {
    var host = elementId ? document.getElementById(elementId) : null;
    if (!host) return false;
    var button = host.tagName === "BUTTON" ? host : $("button", host);
    (button || host).click();
    return true;
  }

  function runCommand(command) {
    closeOverlays();
    if (!command) return;
    switch (command.kind) {
      case "copy":
        copyText(command.value || "");
        return;
      case "theme":
        if (!clickTarget("dc-theme-toggle")) notify("Theme control is not on this page", "warning");
        return;
      case "sidebar":
        toggleSidebar();
        return;
      case "shortcuts":
        showShortcuts();
        return;
      default:
        if (!clickTarget(command.target)) {
          notify("That command is not available right now", "warning");
        }
    }
  }

  /* ---------------------------------------------------------------- palette */

  function buildPalette() {
    var existing = document.getElementById("dc-palette");
    if (existing) return existing;

    var backdrop = document.createElement("div");
    backdrop.id = "dc-palette-backdrop";
    backdrop.className = "dc-palette-backdrop";
    backdrop.setAttribute("data-dc-close", "1");
    document.body.appendChild(backdrop);

    var panel = document.createElement("div");
    panel.id = "dc-palette";
    panel.className = "dc-palette";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-label", "Command palette");
    panel.innerHTML =
      '<input type="text" class="dc-palette-input" placeholder="Search commands\u2026"' +
      ' autocomplete="off" spellcheck="false" aria-label="Search commands">' +
      '<div class="dc-palette-list" role="listbox"></div>';
    document.body.appendChild(panel);

    var input = $(".dc-palette-input", panel);
    input.addEventListener("input", function () {
      renderPalette(input.value);
    });
    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveSelection(1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        moveSelection(-1);
      } else if (event.key === "Enter") {
        event.preventDefault();
        var active = $('.dc-palette-item[aria-selected="true"]', panel);
        if (active) runCommand(readCommand(active));
      } else if (event.key === "Escape") {
        event.preventDefault();
        closeOverlays();
      }
    });
    return panel;
  }

  function readCommand(node) {
    try {
      return JSON.parse(node.getAttribute("data-dc-command") || "null");
    } catch (e) {
      return null;
    }
  }

  function score(command, query) {
    var needle = (query || "").toLowerCase().trim();
    if (!needle) return 0;
    var haystack = (
      (command.label || "") +
      " " +
      (command.group || "") +
      " " +
      (command.keywords || "")
    ).toLowerCase();
    var index = haystack.indexOf(needle);
    if (index >= 0) return 100 - Math.min(index, 60);
    /* Subsequence match, so "spl sc" still finds "Split - Scene detection". */
    var cursor = 0;
    for (var i = 0; i < needle.length; i++) {
      if (needle[i] === " ") continue;
      cursor = haystack.indexOf(needle[i], cursor);
      if (cursor < 0) return -1;
      cursor += 1;
    }
    return 10;
  }

  function renderPalette(query) {
    var panel = buildPalette();
    var list = $(".dc-palette-list", panel);
    var matches = commands()
      .map(function (command) {
        return { command: command, rank: score(command, query) };
      })
      .filter(function (entry) {
        return entry.rank >= 0;
      })
      .sort(function (a, b) {
        return b.rank - a.rank;
      })
      .slice(0, 14);

    list.textContent = "";
    if (!matches.length) {
      var empty = document.createElement("div");
      empty.className = "dc-palette-item";
      empty.style.color = "var(--dc-faint)";
      empty.textContent = "No matching commands";
      list.appendChild(empty);
      return;
    }

    matches.forEach(function (entry, index) {
      var row = document.createElement("div");
      row.className = "dc-palette-item";
      row.setAttribute("role", "option");
      row.setAttribute("aria-selected", index === 0 ? "true" : "false");
      row.setAttribute("data-dc-command", JSON.stringify(entry.command));

      if (entry.command.group) {
        var group = document.createElement("span");
        group.style.cssText = "color:var(--dc-faint);font-size:11.5px";
        group.textContent = entry.command.group;
        row.appendChild(group);
      }
      var label = document.createElement("span");
      label.textContent = entry.command.label || "";
      row.appendChild(label);
      if (entry.command.hint) {
        var hint = document.createElement("span");
        hint.className = "dc-palette-hint";
        hint.textContent = entry.command.hint;
        row.appendChild(hint);
      }

      row.addEventListener("mouseenter", function () {
        select(row);
      });
      row.addEventListener("click", function () {
        runCommand(entry.command);
      });
      list.appendChild(row);
    });
  }

  function select(row) {
    $$(".dc-palette-item", row.parentNode).forEach(function (node) {
      node.setAttribute("aria-selected", "false");
    });
    row.setAttribute("aria-selected", "true");
  }

  function moveSelection(delta) {
    var list = $(".dc-palette-list");
    if (!list) return;
    var rows = $$(".dc-palette-item", list);
    if (!rows.length) return;
    var current = 0;
    rows.forEach(function (node, index) {
      if (node.getAttribute("aria-selected") === "true") current = index;
    });
    var next = (current + delta + rows.length) % rows.length;
    select(rows[next]);
    if (rows[next].scrollIntoView) rows[next].scrollIntoView({ block: "nearest" });
  }

  function openPalette() {
    var panel = buildPalette();
    renderPalette("");
    document.getElementById("dc-palette-backdrop").classList.add("dc-open");
    panel.classList.add("dc-open");
    var input = $(".dc-palette-input", panel);
    input.value = "";
    window.setTimeout(function () {
      input.focus();
    }, reduceMotion ? 0 : 40);
  }

  function paletteOpen() {
    var panel = document.getElementById("dc-palette");
    return !!panel && panel.classList.contains("dc-open");
  }

  function togglePalette() {
    if (paletteOpen()) closeOverlays();
    else openPalette();
  }

  window.dripcutPalette = { open: openPalette, close: closeOverlays, toggle: togglePalette };

  /* -------------------------------------------------------------- shortcuts */

  var SHORTCUTS = [
    ["\u2318 K", "Command palette"],
    ["\u2318 \\", "Collapse or show the sidebar"],
    ["\u2318 \u21e7 T", "Switch theme"],
    ["\u2318 \u21b5", "Run the current action"],
    ["J K L", "Previous \u00b7 play \u00b7 next"],
    ["\u2190 \u2192", "Nudge the playhead"],
    ["?", "Show this list"],
    ["esc", "Close overlays"],
  ];

  /* Rendered with palette styling so there is one visual language for overlays. */
  function showShortcuts() {
    if (document.getElementById("dc-shortcuts")) {
      closeOverlays();
      return;
    }
    var backdrop = document.createElement("div");
    backdrop.id = "dc-shortcuts-backdrop";
    backdrop.className = "dc-palette-backdrop dc-open";
    backdrop.setAttribute("data-dc-close", "1");
    document.body.appendChild(backdrop);

    var panel = document.createElement("div");
    panel.id = "dc-shortcuts";
    panel.className = "dc-palette dc-open";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Keyboard shortcuts");
    var rows = SHORTCUTS.map(function (pair) {
      return (
        '<div class="dc-palette-item">' +
        "<span>" +
        pair[1] +
        '</span><span class="dc-palette-hint">' +
        pair[0] +
        "</span></div>"
      );
    }).join("");
    panel.innerHTML =
      '<div class="dc-palette-input" style="cursor:default">Keyboard shortcuts</div>' +
      '<div class="dc-palette-list">' +
      rows +
      "</div>";
    document.body.appendChild(panel);
  }

  function closeOverlays() {
    ["dc-palette", "dc-palette-backdrop"].forEach(function (id) {
      var node = document.getElementById(id);
      if (node) node.classList.remove("dc-open");
    });
    ["dc-shortcuts", "dc-shortcuts-backdrop"].forEach(function (id) {
      var node = document.getElementById(id);
      if (node && node.parentNode) node.parentNode.removeChild(node);
    });
  }

  /* ---------------------------------------------------------------- sidebar */

  function sidebar() {
    return $(".dc-sidebar");
  }

  function setSidebarWidth(width) {
    var panel = sidebar();
    if (!panel) return;
    var clamped = Math.max(SIDEBAR_MIN, Math.min(SIDEBAR_MAX, Math.round(width)));
    /* The stylesheet pins these with !important, so match that specificity. */
    panel.style.setProperty("min-width", clamped + "px", "important");
    panel.style.setProperty("max-width", clamped + "px", "important");
  }

  function toggleSidebar() {
    var panel = sidebar();
    if (!panel) return;
    var hidden = panel.getAttribute("data-dc-collapsed") === "1";
    if (hidden) {
      panel.style.removeProperty("display");
      panel.removeAttribute("data-dc-collapsed");
      notify("Sidebar shown", "info");
    } else {
      panel.style.setProperty("display", "none", "important");
      panel.setAttribute("data-dc-collapsed", "1");
      notify("Sidebar hidden \u2014 \u2318\\ to bring it back", "info");
    }
  }

  /* A one-pixel grab strip on the sidebar's trailing edge. Idempotent: it is
     re-created after Gradio replaces the sidebar node. */
  function installResizer() {
    var panel = sidebar();
    if (!panel || panel.__dcResizer) return;
    panel.__dcResizer = true;
    panel.style.position = panel.style.position || "relative";

    var handle = document.createElement("div");
    handle.className = "dc-resize-handle";
    handle.setAttribute("role", "separator");
    handle.setAttribute("aria-orientation", "vertical");
    handle.setAttribute("aria-label", "Resize sidebar");
    handle.setAttribute("tabindex", "0");
    handle.title = "Drag to resize, double-click to reset";
    handle.style.cssText =
      "position:absolute;top:0;right:-3px;width:7px;height:100%;cursor:col-resize;z-index:5";
    panel.appendChild(handle);

    var dragging = false;

    handle.addEventListener("pointerdown", function (event) {
      dragging = true;
      document.body.style.userSelect = "none";
      if (handle.setPointerCapture) handle.setPointerCapture(event.pointerId);
      event.preventDefault();
    });
    handle.addEventListener("pointermove", function (event) {
      if (!dragging) return;
      var left = panel.getBoundingClientRect().left;
      setSidebarWidth(event.clientX - left);
      event.preventDefault();
    });
    function stop() {
      if (!dragging) return;
      dragging = false;
      document.body.style.removeProperty("user-select");
    }
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
    handle.addEventListener("dblclick", function () {
      setSidebarWidth(SIDEBAR_DEFAULT);
    });
    handle.addEventListener("keydown", function (event) {
      var current = panel.getBoundingClientRect().width || SIDEBAR_DEFAULT;
      if (event.key === "ArrowLeft") {
        setSidebarWidth(current - 16);
        event.preventDefault();
      } else if (event.key === "ArrowRight") {
        setSidebarWidth(current + 16);
        event.preventDefault();
      }
    });
  }

  /* ---------------------------------------------------- transport shortcuts */

  /* Pages opt in by tagging a control with data-dc-action, so the same keys work
     on any page that has an equivalent control and are inert where they do not. */
  function visible(node) {
    return !!node && node.offsetParent !== null;
  }

  function fireAction(name) {
    var node = $('[data-dc-action="' + name + '"]');
    if (!node && name === "primary") {
      /* Each page names its main button dc-primary-<page>; exactly one is on
         screen at a time, so the visible one is the active page's. */
      node = $$('[id^="dc-primary-"]').filter(visible)[0];
    }
    if (!node) return false;
    var button = node.tagName === "BUTTON" ? node : $("button", node);
    (button || node).click();
    return true;
  }

  var TRANSPORT = {
    j: "prev",
    k: "play",
    l: "next",
    ArrowLeft: "nudge-back",
    ArrowRight: "nudge-forward",
  };

  document.addEventListener("keydown", function (event) {
    var meta = event.metaKey || event.ctrlKey;

    if (meta && (event.key === "k" || event.key === "K")) {
      event.preventDefault();
      togglePalette();
      return;
    }
    if (event.key === "Escape") {
      closeOverlays();
      return;
    }
    if (meta && event.key === "\\") {
      event.preventDefault();
      toggleSidebar();
      return;
    }
    if (meta && event.shiftKey && (event.key === "t" || event.key === "T")) {
      event.preventDefault();
      clickTarget("dc-theme-toggle");
      return;
    }
    if (meta && event.key === "Enter") {
      if (fireAction("primary")) event.preventDefault();
      return;
    }
    if (isTypingTarget(event.target) || meta || event.altKey) return;

    if (event.key === "?") {
      event.preventDefault();
      showShortcuts();
      return;
    }
    var action = TRANSPORT[event.key] || TRANSPORT[String(event.key).toLowerCase()];
    if (action && fireAction(action)) event.preventDefault();
  });

  /* ------------------------------------------------------- delegated clicks */

  document.addEventListener("click", function (event) {
    if (closestOf(event.target, "[data-dc-close]")) {
      closeOverlays();
      return;
    }
    if (closestOf(event.target, "[data-dc-palette]")) {
      event.preventDefault();
      openPalette();
      return;
    }
    var copier = closestOf(event.target, "[data-dc-copy]");
    if (copier) {
      copyText(copier.getAttribute("data-dc-copy") || copier.textContent.trim());
      return;
    }
    var timecode = closestOf(event.target, ".dc-tc") || closestOf(event.target, ".dc-mono");
    if (timecode && timecode.textContent.trim()) copyText(timecode.textContent.trim());
  });

  /* -------------------------------------------------------------- lifecycle */

  function boot() {
    installResizer();
    buildPalette();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  /* Gradio mounts asynchronously and swaps nodes on navigation; the installers
     above are idempotent, so re-running them on mutation is safe and cheap. */
  var pending = null;
  var observer = new MutationObserver(function () {
    if (pending) return;
    pending = window.setTimeout(function () {
      pending = null;
      installResizer();
    }, 120);
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();

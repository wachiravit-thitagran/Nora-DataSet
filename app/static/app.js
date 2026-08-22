/* Nora Dataset — catalogue page.
 *
 * No framework, no build step. The page is driven entirely by /api/catalog,
 * so publishing a new bundle or filling in the licence is a data change,
 * never a code change.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "nora_access";
  var state = {
    lang: "th",
    strings: {},
    manifest: null,
    poses: null,
    access: null,
    // The bundle whose button opened the form, so the download the visitor
    // actually asked for starts by itself once access is granted.
    pendingBundle: null
  };

  // ---------------------------------------------------------------- helpers

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function t(key) {
    var table = state.strings[state.lang] || {};
    return table[key] !== undefined ? table[key] : key;
  }

  /* Picks the current language out of a {th, en} object, falling back to the
     other language rather than rendering an empty cell. */
  function pick(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "string") return value;
    return value[state.lang] || value.th || value.en || "";
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function formatBytes(bytes) {
    if (bytes === null || bytes === undefined) return "—";
    var units = ["B", "KB", "MB", "GB", "TB"];
    var i = 0;
    var value = bytes;
    while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1; }
    return (value >= 10 || i === 0 ? Math.round(value) : value.toFixed(1)) + " " + units[i];
  }

  function formatDate(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(state.lang === "th" ? "th-TH" : "en-GB",
      { year: "numeric", month: "short", day: "numeric" });
  }

  function formatTime(epochSeconds) {
    var d = new Date(epochSeconds * 1000);
    return d.toLocaleString(state.lang === "th" ? "th-TH" : "en-GB",
      { dateStyle: "medium", timeStyle: "short" });
  }

  // ------------------------------------------------------------ access token

  function loadAccess() {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      var parsed = JSON.parse(raw);
      if (!parsed.token || !parsed.expires_at) return null;
      if (parsed.expires_at * 1000 <= Date.now()) {
        sessionStorage.removeItem(STORAGE_KEY);
        return null;
      }
      return parsed;
    } catch (err) {
      return null;
    }
  }

  function saveAccess(access) {
    state.access = access;
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(access)); } catch (err) { /* private mode */ }
  }

  // ------------------------------------------------------------- translation

  function applyStaticStrings() {
    $$("[data-i18n]").forEach(function (node) {
      node.textContent = t(node.getAttribute("data-i18n"));
    });
    document.documentElement.lang = state.lang;
    $$("#lang-toggle, #lang-toggle-sm").forEach(function (btn) {
      btn.textContent = t("switch_to");
    });
  }

  // ---------------------------------------------------------------- rendering

  function renderDataset() {
    var ds = state.manifest.dataset;

    $$('[data-field="dataset.title"]').forEach(function (n) { n.textContent = pick(ds.title); });
    document.title = pick(ds.title);

    $$('[data-field="dataset.summary"]').forEach(function (n) { n.textContent = pick(ds.summary); });
    $$('[data-field="dataset.description"]').forEach(function (n) { n.textContent = pick(ds.description); });
    $$('[data-field="dataset.version"]').forEach(function (n) { n.textContent = ds.version || "—"; });
    $$('[data-field="dataset.released_at"]').forEach(function (n) { n.textContent = formatDate(ds.released_at); });

    var licenceName = pick((ds.license && ds.license.name) || "");
    $$('[data-field="dataset.license"]').forEach(function (n) { n.textContent = licenceName || "—"; });
    $$('[data-field="dataset.license_note"]').forEach(function (n) {
      n.textContent = pick((ds.license && ds.license.note) || "");
    });

    /* Both citation formats, with {version} filled in from the manifest so a
       new release cannot leave the citation pointing at the old one. */
    function withVersion(text) {
      return String(text || "").replace(/\{version\}/g, ds.version || "");
    }

    var citation = $("#citation-text");
    if (citation) {
      citation.textContent = withVersion((ds.citation && ds.citation.text) || "—");
    }
    var bibtex = $("#citation-bibtex");
    if (bibtex) {
      bibtex.textContent = withVersion((ds.citation && ds.citation.bibtex) || "—");
    }

    var contact = $("#contact-text");
    if (contact && ds.contact && ds.contact.email) {
      contact.textContent = "";
      var mail = el("a", null, ds.contact.email);
      mail.href = "mailto:" + ds.contact.email;
      contact.appendChild(mail);
    }
  }

  function renderBundles() {
    var grid = $("#bundle-grid");
    if (!grid) return;
    grid.textContent = "";

    (state.manifest.bundles || []).forEach(function (bundle) {
      var card = el("div", "bundle");
      card.appendChild(el("h3", null, pick(bundle.title)));
      card.appendChild(el("p", null, pick(bundle.description)));

      var meta = el("div", "bundle-meta");
      function addMeta(label, value) {
        var span = el("span");
        span.appendChild(document.createTextNode(label + " "));
        span.appendChild(el("b", null, value));
        meta.appendChild(span);
      }
      addMeta(t("bundle_size"), formatBytes(bundle.bytes));
      addMeta(t("bundle_files"), bundle.file_count === null || bundle.file_count === undefined
        ? "—" : String(bundle.file_count));
      if (bundle.formats && bundle.formats.length) {
        addMeta(t("bundle_formats"), bundle.formats.join(", "));
      }
      card.appendChild(meta);

      if (bundle.sha256) {
        var sum = el("p", "checksum", t("checksum_label") + " " + bundle.sha256);
        card.appendChild(sum);
      }

      /* A bundle held back on purpose says why. Without this the card is
         indistinguishable from one whose upload simply failed. */
      var pending = pick(bundle.pending_note);
      if (pending && !bundle.available) {
        card.appendChild(el("p", "pending-note", pending));
      }

      var button = el("button", bundle.available
        ? "btn btn-primary mt-6 w-full rounded-full text-white"
        : "btn mt-6 w-full rounded-full");
      button.type = "button";
      if (!bundle.available) {
        // Neutral styling, not a dimmed primary button: an unpublished bundle
        // should not read as the main action on the card.
        button.textContent = t("bundle_unavailable");
        button.disabled = true;
      } else if (!state.access) {
        button.textContent = t("btn_download");
        button.addEventListener("click", function () {
          openAccess(bundle.id);
        });
      } else {
        button.textContent = t("btn_download");
        button.addEventListener("click", function () { startDownload(bundle.id); });
      }
      card.appendChild(button);

      grid.appendChild(card);
    });
  }

  /* The zip layout, described bundle by bundle. Like everything else on this
     page it comes from the manifest, so repackaging a bundle differently is a
     data edit rather than a code edit. */
  function renderContents() {
    var host = $("#contents-list");
    if (!host) return;
    host.textContent = "";

    (state.manifest.bundles || []).forEach(function (bundle) {
      var entries = bundle.contents || [];
      if (!entries.length) return;

      var block = el("section", "contents");
      block.appendChild(el("h3", null, pick(bundle.title)));

      // The archive name is what people actually see in their downloads
      // folder, so lead with it when we know it.
      if (bundle.filename) {
        block.appendChild(el("p", "contents-file", bundle.filename));
      } else {
        block.appendChild(el("p", "contents-file muted", t("contents_unavailable")));
      }

      var pendingNote = pick(bundle.pending_note);
      if (pendingNote && !bundle.available) {
        block.appendChild(el("p", "pending-note", pendingNote));
      }

      var list = el("ul", "tree");
      entries.forEach(function (entry) {
        var kind = entry.kind || "file";
        var li = el("li", "tree-item is-" + kind);
        li.appendChild(el("code", null, entry.path));
        var note = pick(entry.note);
        if (note) li.appendChild(el("span", "tree-note", note));
        list.appendChild(li);
      });
      block.appendChild(list);

      host.appendChild(block);
    });
  }

  function renderGrantBanner() {
    var banner = $("#grant-banner");
    if (!banner) return;

    if (state.access) {
      banner.hidden = false;
      $("#grant-detail").textContent =
        t("access_granted_detail").replace("{time}", formatTime(state.access.expires_at));
    } else {
      banner.hidden = true;
    }
  }

  function renderAll() {
    applyStaticStrings();
    if (!state.manifest) return;
    renderDataset();
    renderGrantBanner();
    renderBundles();
    renderContents();
  }

  // ---------------------------------------------------------------- download

  function startDownload(bundleId) {
    if (!state.access) return;
    /* Navigating rather than fetching lets the browser own the transfer: it
       shows native progress, survives a page change, and resumes if the
       server supports ranges. */
    var url = "api/download/" + encodeURIComponent(bundleId) +
              "?t=" + encodeURIComponent(state.access.token);
    window.location.href = url;
  }

  // -------------------------------------------------------------------- form

  function showFormError(key) {
    var box = $("#form-error");
    box.textContent = t(key);
    box.hidden = false;
  }

  function clearFormError() {
    var box = $("#form-error");
    box.hidden = true;
    box.textContent = "";
  }

  function handleSubmit(event) {
    event.preventDefault();
    clearFormError();

    var email = $("#f-email").value.trim();
    var purpose = $("#f-purpose").value;
    var detail = $("#f-detail").value.trim();
    var org = $("#f-org").value.trim();
    var consent = $("#f-consent").checked;

    if (!email || email.indexOf("@") < 1) { showFormError("form_error_email"); $("#f-email").focus(); return; }
    if (!purpose) { $("#f-purpose").focus(); return; }
    if (purpose === "other" && !detail) { showFormError("form_detail_required"); $("#f-detail").focus(); return; }
    if (!consent) { showFormError("form_error_consent"); $("#f-consent").focus(); return; }

    var button = $("#submit-btn");
    button.disabled = true;
    button.textContent = t("form_submitting");

    fetch("api/access", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email,
        organization: org || null,
        purpose: purpose,
        purpose_detail: detail || null,
        consent: true,
        // Record the exact sentence the visitor agreed to, so the stored
        // consent stays meaningful even after this wording is revised.
        consent_text: $("#consent-text").textContent.trim(),
        lang: state.lang
      })
    }).then(function (response) {
      if (response.status === 429) throw new Error("rate");
      if (!response.ok) throw new Error("generic");
      return response.json();
    }).then(function (data) {
      saveAccess({ token: data.token, expires_at: data.expires_at });
      closeAccess();
      renderGrantBanner();
      renderBundles();

      // Carry on with the download the visitor actually asked for. Without
      // this they would fill in the form, watch the dialog close, and have to
      // find the same button again.
      var wanted = state.pendingBundle;
      state.pendingBundle = null;
      if (wanted) {
        startDownload(wanted);
      } else {
        $("#grant-banner").scrollIntoView({ block: "center" });
      }
    }).catch(function (err) {
      showFormError(err.message === "rate" ? "form_error_rate" : "form_error_generic");
    }).finally(function () {
      button.disabled = false;
      button.textContent = t("form_submit");
    });
  }

  // ------------------------------------------------------------ access form

  function openAccess(bundleId) {
    state.pendingBundle = bundleId || null;
    clearFormError();
    var dialog = $("#access-dialog");
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    // Focus the first field rather than the close button, so a keyboard user
    // lands where the work is.
    var email = $("#f-email");
    if (email) email.focus();
  }

  function closeAccess() {
    var dialog = $("#access-dialog");
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  // ------------------------------------------------------------------ privacy

  function openPrivacy() {
    var dialog = $("#privacy-dialog");
    $("#privacy-body").innerHTML = (window.PRIVACY_NOTICE || {})[state.lang] || "";
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  function closePrivacy() {
    var dialog = $("#privacy-dialog");
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  // --------------------------------------------------------------------- init

  function setLang(lang) {
    state.lang = lang;
    try { localStorage.setItem("nora_lang", lang); } catch (err) { /* ignore */ }
    var url = new URL(window.location.href);
    url.searchParams.set("lang", lang);
    window.history.replaceState({}, "", url);
    renderAll();
  }

  function initialLang() {
    var fromQuery = new URL(window.location.href).searchParams.get("lang");
    if (fromQuery === "th" || fromQuery === "en") return fromQuery;
    try {
      var stored = localStorage.getItem("nora_lang");
      if (stored === "th" || stored === "en") return stored;
    } catch (err) { /* ignore */ }
    return (navigator.language || "").toLowerCase().indexOf("th") === 0 ? "th" : "en";
  }

  function boot() {
    state.access = loadAccess();

    Promise.all([
      fetch("i18n.json").then(function (r) { return r.json(); }),
      fetch("api/catalog").then(function (r) {
        if (!r.ok) throw new Error("catalog");
        return r.json();
      })
    ]).then(function (results) {
      state.strings = results[0];
      state.manifest = results[1].manifest;
      state.poses = results[1].poses;
      state.lang = initialLang();
      renderAll();
    }).catch(function () {
      var grid = $("#bundle-grid");
      if (grid) {
        grid.textContent = "";
        grid.appendChild(el("p", "muted", t("load_error")));
      }
    });

    // Two toggles now: one in the desktop navbar, one in the mobile bar.
    $$("#lang-toggle, #lang-toggle-sm").forEach(function (btn) {
      btn.addEventListener("click", function () {
        setLang(state.lang === "th" ? "en" : "th");
      });
    });
    $("#access-form").addEventListener("submit", handleSubmit);
    $("#close-access").addEventListener("click", closeAccess);
    // Esc fires `cancel` on a native dialog; let it through but keep the
    // pending bundle from leaking into the next attempt.
    $("#access-dialog").addEventListener("close", function () {
      state.pendingBundle = null;
    });
    $("#open-privacy").addEventListener("click", openPrivacy);
    $("#close-privacy").addEventListener("click", closePrivacy);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();

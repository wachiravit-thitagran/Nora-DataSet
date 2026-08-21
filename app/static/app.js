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
    access: null
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
    var toggle = $("#lang-toggle");
    if (toggle) toggle.textContent = t("switch_to");
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

    var disclaimerBox = $("#disclaimer-box");
    var disclaimer = pick(ds.disclaimer);
    if (disclaimer) {
      $('[data-field="dataset.disclaimer"]').textContent = disclaimer;
    } else if (disclaimerBox) {
      disclaimerBox.hidden = true;
    }

    var pill = $("#status-pill");
    if (pill) {
      var released = ds.status === "released" || ds.status === "published";
      pill.textContent = released ? t("status_published") : t("status_draft");
      pill.classList.toggle("is-released", released);
      pill.hidden = false;
    }

    var citation = $("#citation-text");
    if (citation) {
      citation.textContent = (ds.citation && (ds.citation.bibtex || ds.citation.text)) || "TBD";
    }

    var credits = $("#credits-list");
    if (credits) {
      credits.textContent = "";
      (ds.credits || []).forEach(function (item) {
        var li = el("li");
        li.appendChild(el("strong", null, pick(item.role) + ": "));
        li.appendChild(document.createTextNode(pick(item.value)));
        credits.appendChild(li);
      });
    }

    var contact = $("#contact-text");
    if (contact && ds.contact) {
      var parts = [ds.contact.name, ds.contact.organization, ds.contact.email]
        .filter(function (p) { return p && p !== "TBD"; });
      contact.textContent = parts.length ? parts.join(" · ") : "TBD";
    }
  }

  function identityTag(match, hasRestored) {
    if (hasRestored === false) return { label: t("no_restored"), cls: "tag-none" };
    switch (match) {
      case "verified": return { label: t("identity_verified"), cls: "tag-verified" };
      case "mismatch": return { label: t("identity_mismatch"), cls: "tag-mismatch" };
      case "partial": return { label: t("identity_partial"), cls: "tag-partial" };
      default: return { label: t("identity_not_applicable"), cls: "tag-none" };
    }
  }

  function renderPoses() {
    var tbody = $("#pose-rows");
    if (!tbody) return;
    tbody.textContent = "";

    (state.poses.poses || []).forEach(function (pose) {
      var tr = el("tr");

      tr.appendChild(el("td", "pose-id", pose.id));

      var nameCell = el("td");
      nameCell.appendChild(el("span", "pose-name", state.lang === "th" ? pose.name_th : pose.name_en));
      nameCell.appendChild(el("span", "pose-name-en", state.lang === "th" ? pose.name_en : pose.name_th));
      tr.appendChild(nameCell);

      tr.appendChild(el("td", null, state.lang === "th" ? pose.description_th : pose.description_en));

      var aliases = (pose.aliases || []).filter(function (a) { return !/^[a-z_]+$/.test(a); });
      tr.appendChild(el("td", "alias-list", aliases.length ? aliases.join(", ") : "—"));

      var tag = identityTag(pose.identity_match, pose.has_restored);
      var statusCell = el("td");
      statusCell.appendChild(el("span", "tag " + tag.cls, tag.label));
      tr.appendChild(statusCell);

      tbody.appendChild(tr);
    });

    var unmapped = state.poses.unmapped || [];
    var block = $("#unmapped-block");
    var list = $("#unmapped-list");
    if (block && list) {
      list.textContent = "";
      if (unmapped.length) {
        unmapped.forEach(function (item) {
          list.appendChild(el("li", null,
            (state.lang === "th" ? item.note_th : item.note_en) || item.status));
        });
        block.hidden = false;
      } else {
        block.hidden = true;
      }
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

      var button = el("button", bundle.available ? "btn btn-primary" : "btn");
      button.type = "button";
      if (!bundle.available) {
        // Neutral styling, not a dimmed primary button: an unpublished bundle
        // should not read as the main action on the card.
        button.textContent = t("bundle_unavailable");
        button.disabled = true;
      } else if (!state.access) {
        button.textContent = t("btn_download");
        button.addEventListener("click", function () {
          $("#access-card").scrollIntoView({ block: "center" });
          $("#f-email").focus();
        });
      } else {
        button.textContent = t("btn_download");
        button.addEventListener("click", function () { startDownload(bundle.id); });
      }
      card.appendChild(button);

      grid.appendChild(card);
    });
  }

  function renderGrantBanner() {
    var banner = $("#grant-banner");
    var card = $("#access-card");
    if (!banner || !card) return;

    if (state.access) {
      banner.hidden = false;
      $("#grant-detail").textContent =
        t("access_granted_detail").replace("{time}", formatTime(state.access.expires_at));
      card.hidden = true;
    } else {
      banner.hidden = true;
      card.hidden = false;
    }
  }

  function renderAll() {
    applyStaticStrings();
    if (!state.manifest) return;
    renderDataset();
    renderPoses();
    renderGrantBanner();
    renderBundles();
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
      renderGrantBanner();
      renderBundles();
      $("#grant-banner").scrollIntoView({ block: "center" });
    }).catch(function (err) {
      showFormError(err.message === "rate" ? "form_error_rate" : "form_error_generic");
    }).finally(function () {
      button.disabled = false;
      button.textContent = t("form_submit");
    });
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
      var tbody = $("#pose-rows");
      if (tbody) tbody.textContent = "";
      var row = el("tr");
      row.appendChild(el("td", "muted", t("load_error")));
      row.firstChild.colSpan = 5;
      if (tbody) tbody.appendChild(row);
    });

    $("#lang-toggle").addEventListener("click", function () {
      setLang(state.lang === "th" ? "en" : "th");
    });
    $("#access-form").addEventListener("submit", handleSubmit);
    $("#open-privacy").addEventListener("click", openPrivacy);
    $("#open-privacy-footer").addEventListener("click", openPrivacy);
    $("#close-privacy").addEventListener("click", closePrivacy);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();

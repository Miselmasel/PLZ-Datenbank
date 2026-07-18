/* PLZ-Umkreissuche — clientseitige Umkreisberechnung (Haversine) */

(() => {
  "use strict";

  const EARTH_RADIUS_KM = 6371;

  const els = {
    themeToggle: document.getElementById("theme-toggle"),
    form: document.getElementById("search-form"),
    plzInput: document.getElementById("plz-input"),
    radiusSlider: document.getElementById("radius-slider"),
    radiusInput: document.getElementById("radius-input"),
    formError: document.getElementById("form-error"),
    stateEmpty: document.getElementById("state-empty"),
    stateLoading: document.getElementById("state-loading"),
    stateNoMatch: document.getElementById("state-no-match"),
    stateResults: document.getElementById("state-results"),
    resultsSummary: document.getElementById("results-summary"),
    resultsTbody: document.getElementById("results-tbody"),
    sortSelect: document.getElementById("sort-select"),
    sortDirection: document.getElementById("sort-direction"),
    btnCsv: document.getElementById("btn-csv"),
  };

  let dataset = null; // Array<{plz, ort, bundesland, lat, lon, einwohner}>
  let datasetPromise = null;
  let byPlz = null;

  // Letzte Suche merken, damit Sortieren/CSV-Export ohne Neuberechnung funktionieren.
  let lastMatches = null;
  let lastOriginPlz = null;
  let lastRadiusKm = null;
  let sortField = "distanceKm"; // "distanceKm" | "plz" | "einwohner"
  let sortDir = "asc"; // "asc" | "desc"

  // ---------------- Theme ----------------

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }

  function initTheme() {
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(prefersDark ? "dark" : "light");
  }

  els.themeToggle.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "light";
    applyTheme(current === "dark" ? "light" : "dark");
  });

  initTheme();

  // ---------------- Data loading ----------------

  function loadDataset() {
    if (datasetPromise) return datasetPromise;
    datasetPromise = fetch("data/plz_umkreisdaten.json")
      .then((res) => {
        if (!res.ok) throw new Error("Datenabruf fehlgeschlagen (" + res.status + ")");
        return res.json();
      })
      .then((rows) => {
        dataset = rows;
        byPlz = new Map(rows.map((r) => [r.plz, r]));
        return rows;
      });
    return datasetPromise;
  }

  // ---------------- Haversine ----------------

  function toRad(deg) {
    return (deg * Math.PI) / 180;
  }

  function haversineKm(lat1, lon1, lat2, lon2) {
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return EARTH_RADIUS_KM * c;
  }

  // ---------------- Formatting ----------------

  const numberFmtDistance = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const numberFmtEinwohner = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  function formatDistance(km) {
    return numberFmtDistance.format(km) + " km";
  }

  function formatEinwohnerTausend(einwohner) {
    return numberFmtEinwohner.format(einwohner / 1000);
  }

  // ---------------- State management ----------------

  function showState(name) {
    els.stateEmpty.hidden = name !== "empty";
    els.stateLoading.hidden = name !== "loading";
    els.stateNoMatch.hidden = name !== "no-match";
    els.stateResults.hidden = name !== "results";
  }

  function showFormError(message) {
    if (!message) {
      els.formError.hidden = true;
      els.formError.textContent = "";
      return;
    }
    els.formError.hidden = false;
    els.formError.textContent = message;
  }

  // ---------------- Sorting ----------------

  function sortComparator(field) {
    switch (field) {
      case "plz":
        return (a, b) => a.plz.localeCompare(b.plz);
      case "einwohner":
        return (a, b) => a.einwohner - b.einwohner;
      case "distanceKm":
      default:
        return (a, b) => a.distanceKm - b.distanceKm;
    }
  }

  function sortMatches(matches, field, dir) {
    const sorted = matches.slice().sort(sortComparator(field));
    if (dir === "desc") sorted.reverse();
    return sorted;
  }

  function applySortAndRender() {
    if (!lastMatches) return;
    const sorted = sortMatches(lastMatches, sortField, sortDir);
    renderResults(lastOriginPlz, lastRadiusKm, sorted);
  }

  els.sortSelect.addEventListener("change", () => {
    sortField = els.sortSelect.value;
    applySortAndRender();
  });

  els.sortDirection.addEventListener("click", () => {
    sortDir = sortDir === "asc" ? "desc" : "asc";
    els.sortDirection.dataset.dir = sortDir;
    els.sortDirection.setAttribute(
      "aria-label",
      "Sortierrichtung umschalten (aktuell " + (sortDir === "asc" ? "aufsteigend" : "absteigend") + ")"
    );
    applySortAndRender();
  });

  // ---------------- CSV-Export ----------------

  function toCsvValue(value) {
    const str = String(value);
    if (/[;"\n]/.test(str)) {
      return '"' + str.replace(/"/g, '""') + '"';
    }
    return str;
  }

  function buildCsv(originPlz, matches) {
    const header = ["PLZ", "Ort", "Bundesland", "Entfernung (km)", "Einwohner (Tsd.)"];
    const lines = [header.join(";")];

    for (const m of matches) {
      const distance = m.plz === originPlz ? 0 : m.distanceKm;
      const row = [
        m.plz,
        m.ort,
        m.bundesland,
        numberFmtDistance.format(distance),
        formatEinwohnerTausend(m.einwohner),
      ];
      lines.push(row.map(toCsvValue).join(";"));
    }

    return lines.join("\r\n");
  }

  function downloadCsv() {
    if (!lastMatches) return;
    const sorted = sortMatches(lastMatches, sortField, sortDir);
    const csv = buildCsv(lastOriginPlz, sorted);
    const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "plz-umkreissuche_" + lastOriginPlz + "_" + lastRadiusKm + "km.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  els.btnCsv.addEventListener("click", downloadCsv);

  // ---------------- Rendering ----------------

  function renderResults(originPlz, radiusKm, matches) {
    els.resultsTbody.innerHTML = "";

    for (const m of matches) {
      const tr = document.createElement("tr");
      if (m.plz === originPlz) tr.classList.add("row-origin");

      const isOrigin = m.plz === originPlz;

      tr.innerHTML =
        '<td class="cell-plz">' + m.plz + "</td>" +
        '<td class="cell-ort">' + escapeHtml(m.ort) + (isOrigin ? '<span class="badge-origin">Start</span>' : "") + "</td>" +
        "<td>" + escapeHtml(m.bundesland) + "</td>" +
        '<td class="col-num cell-num">' + (isOrigin ? "0,0 km" : formatDistance(m.distanceKm)) + "</td>" +
        '<td class="col-num cell-num">' + formatEinwohnerTausend(m.einwohner) + "</td>";

      els.resultsTbody.appendChild(tr);
    }

    const totalEinwohner = matches.reduce((sum, m) => sum + m.einwohner, 0);
    els.resultsSummary.textContent =
      matches.length +
      (matches.length === 1 ? " Treffer" : " Treffer") +
      " im Umkreis von " +
      radiusKm +
      " km um " +
      originPlz +
      " · zusammen ca. " +
      numberFmtEinwohner.format(totalEinwohner / 1000) +
      " Tsd. Einwohner";

    showState("results");
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }

  // ---------------- Search ----------------

  function runSearch(plz, radiusKm) {
    const origin = byPlz.get(plz);
    if (!origin) {
      showFormError(
        "Postleitzahl „" + plz + "“ wurde nicht in der Datengrundlage gefunden. Bitte prüfe die Eingabe."
      );
      showState("empty");
      return;
    }
    showFormError(null);

    const matches = [];
    for (const row of dataset) {
      const distanceKm = haversineKm(origin.lat, origin.lon, row.lat, row.lon);
      if (distanceKm <= radiusKm) {
        matches.push({ ...row, distanceKm });
      }
    }
    if (matches.length === 0) {
      lastMatches = null;
      lastOriginPlz = null;
      lastRadiusKm = null;
      showState("no-match");
      return;
    }

    lastMatches = matches;
    lastOriginPlz = plz;
    lastRadiusKm = radiusKm;

    const sorted = sortMatches(matches, sortField, sortDir);
    renderResults(plz, radiusKm, sorted);
  }

  // ---------------- Form wiring ----------------

  els.radiusSlider.addEventListener("input", () => {
    els.radiusInput.value = els.radiusSlider.value;
  });

  els.radiusInput.addEventListener("input", () => {
    const val = Number(els.radiusInput.value);
    if (!Number.isNaN(val)) {
      const clamped = Math.min(Math.max(val, Number(els.radiusSlider.min)), Number(els.radiusSlider.max));
      els.radiusSlider.value = String(clamped);
    }
  });

  els.form.addEventListener("submit", (e) => {
    e.preventDefault();

    const rawPlz = els.plzInput.value.trim();
    const radiusRaw = Number(els.radiusInput.value);

    if (!/^\d{5}$/.test(rawPlz)) {
      showFormError("Bitte gib eine gültige 5-stellige Postleitzahl ein.");
      return;
    }
    if (!Number.isFinite(radiusRaw) || radiusRaw <= 0) {
      showFormError("Bitte gib einen gültigen Umkreis in km ein (größer als 0).");
      return;
    }
    const radiusKm = Math.min(radiusRaw, 500);

    showFormError(null);
    showState("loading");

    loadDataset()
      .then(() => runSearch(rawPlz, radiusKm))
      .catch((err) => {
        showFormError("Die Datengrundlage konnte nicht geladen werden: " + err.message);
        showState("empty");
      });
  });

  // Vorab im Hintergrund laden, damit die erste Suche schnell reagiert.
  loadDataset().catch(() => {
    /* Fehler wird beim ersten Suchversuch angezeigt */
  });
})();

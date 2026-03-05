console.log("GS home_map.js VERSION = 2026-03-03-01");

document.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("map");
  if (!el) return;

  // Prevent double init if script is accidentally included twice
  if (el.dataset.mapInit === "1") return;
  el.dataset.mapInit = "1";

  if (typeof L === "undefined") {
    console.error("Leaflet (L) not loaded.");
    return;
  }

  // Config injected by template
  const cfg = window.GARAGE_SALE || {};

  const baseMapDataUrl = cfg.mapDataUrl || cfg.mapData;
  if (!baseMapDataUrl) {
    console.error("window.GARAGE_SALE.mapDataUrl missing.");
    return;
  }

  const center =
    (cfg.defaultMap &&
      Array.isArray(cfg.defaultMap.center) &&
      cfg.defaultMap.center.length === 2)
      ? cfg.defaultMap.center
      : [-37.8136, 144.9631];

  const zoom =
    (cfg.defaultMap && Number.isFinite(cfg.defaultMap.zoom))
      ? cfg.defaultMap.zoom
      : 4;

  const urls = cfg.urls || {};

  // Basic HTML escaping for titles/names coming from the server
  const esc = (s) =>
    String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  const map = L.map("map").setView(center, zoom);

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  // Use a layer group so we can clear/reload pins easily
  const pinsLayer = L.layerGroup().addTo(map);

  // ---- Range filter (Today / Tomorrow / Week / Month) ----
  function getRange() {
    const sel = document.getElementById("gsRange");
    return (sel && sel.value) ? sel.value : "today";
  }

  function buildMapDataUrl() {
    const u = new URL(baseMapDataUrl, window.location.origin);
    u.searchParams.set("range", getRange());
    return u.toString();
  }

  async function fetchJSON(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    const ct = (r.headers.get("content-type") || "").toLowerCase();
    const text = await r.text();

    if (!ct.includes("application/json")) {
      throw new Error(
        `Map data returned non-JSON (${r.status}). First 120 chars: ${text.slice(0, 120)}`
      );
    }
    return JSON.parse(text);
  }

  async function loadPins() {
    pinsLayer.clearLayers();

    const dataUrl = buildMapDataUrl();
    const data = await fetchJSON(dataUrl);

    const pins = (data && data.pins) || [];

    if (!pins.length) {
      L.popup()
        .setLatLng(map.getCenter())
        .setContent(`<b>No garage sales found for this range.</b>`)
        .openOn(map);
      return;
    }

    const bounds = [];

    pins.forEach((p) => {
      const lat = p && p.lat;
      const lng = p && p.lng;
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;

      bounds.push([lat, lng]);

      const title = esc(p.title || "Garage Sale");

      const dateLine = p.start_date
        ? `<div class="text-muted small">
             From: ${esc(p.start_date)}${p.end_date ? ` → ${esc(p.end_date)}` : ""}
           </div>`
        : "";

      // Always safe (fallback keeps local dev working)
      let eventDetailBase = urls.eventDetailBase || "/garage-sale/event/";
      if (!eventDetailBase.endsWith("/")) eventDetailBase += "/";
          const isOwner = window.CURRENT_USER_ID &&
            p.owner_id === window.CURRENT_USER_ID;

          const detailUrl = isOwner
            ? `${eventDetailBase}${p.id}/manage/`
            : `${eventDetailBase}${p.id}/`;

      const action = `<a class="btn btn-success" href="${detailUrl}">View details</a>`;

      const marker = L.marker([lat, lng]).addTo(pinsLayer);
      marker.bindPopup(`
        <div style="min-width:240px">
          <strong>${title}</strong>
          ${dateLine}
          <div style="margin-top:10px">${action}</div>
        </div>
      `);
    });

    // Fit once AFTER markers are created
    if (bounds.length) {
      map.fitBounds(bounds, { padding: [30, 30], maxZoom: 10 });
    }
  }

  // Wire up range dropdown if it exists
  const rangeSelect = document.getElementById("gsRange");
  if (rangeSelect) {
    rangeSelect.addEventListener("change", () => {
      loadPins().catch((err) => console.error("Garage Sale map error:", err));
    });
  }

  // Initial load
  loadPins().catch((err) => {
    console.error("Garage Sale map error:", err);

    L.popup()
      .setLatLng(map.getCenter())
      .setContent(
        `<b>Couldn’t load garage sale pins.</b><br/>
         <span class="muted">${esc(err.message || "Unknown error")}</span>`
      )
      .openOn(map);
  });
});
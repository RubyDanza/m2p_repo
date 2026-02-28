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
      : 10;

  const urls = cfg.urls || {};
  const eventsListUrl = urls.eventsList || "/garage-sale/";
  const createEventUrl = urls.createEvent || eventsListUrl;

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

  const isLoggedIn = !!cfg.isLoggedIn;
  const userRole = cfg.userRole || "";
  const canShop = isLoggedIn && userRole === "CUSTOMER";

  // ---- Range filter (Today / Tomorrow / Week / Month) ----
  // We look for a <select id="gsRange"> in the page.
  // If you haven’t added it yet, this will silently default to "today".
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
    // Clear existing markers
    pinsLayer.clearLayers();

    const dataUrl = buildMapDataUrl();
    const data = await fetchJSON(dataUrl);

    // ✅ backend returns "pins"
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

      const marker = L.marker([lat, lng]).addTo(pinsLayer);

      const title = esc(p.title || "Garage Sale");
      const dateLine = p.start_date
        ? `<div class="muted">From: ${esc(p.start_date)}${p.end_date ? ` → ${esc(p.end_date)}` : ""}</div>`
        : "";

      const detailUrl = p.detail_url || "#";

      const action = canShop
        ? `<a class="btn btn-dark btn-sm" href="${detailUrl}">View details</a>`
        : `<span class="muted">Login as a Customer to view details.</span>`;

      marker.bindPopup(`
        <div style="min-width:240px">
          <strong>${title}</strong><br/>
          ${dateLine}
          <div style="margin-top:10px">${action}</div>
        </div>
      `);
    });

    if (bounds.length) {
      map.fitBounds(bounds, { padding: [30, 30] });
    }
  }

  // Wire up range dropdown if it exists
  const rangeSelect = document.getElementById("gsRange");
  if (rangeSelect) {
    rangeSelect.addEventListener("change", () => {
      loadPins().catch((err) => {
        console.error("Garage Sale map error:", err);
      });
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
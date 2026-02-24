document.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("map");
  if (!el) return;

  if (typeof L === "undefined") {
    console.error("Leaflet (L) not loaded.");
    return;
  }

  // Config injected by template
  const cfg = window.GARAGE_SALE || {};

  // Prefer either key name (supports old/new template vars)
  const mapDataUrl = cfg.mapDataUrl || cfg.mapData || cfg.mapDataUrl;

  const center =
    (cfg.defaultMap && Array.isArray(cfg.defaultMap.center) && cfg.defaultMap.center.length === 2)
      ? cfg.defaultMap.center
      : [-37.8136, 144.9631];

  const zoom =
    (cfg.defaultMap && Number.isFinite(cfg.defaultMap.zoom))
      ? cfg.defaultMap.zoom
      : 10;

  const urls = cfg.urls || {};
  const eventsListUrl = urls.eventsList || "/garage-sale/";
  const createEventUrl = urls.createEvent;;

  if (!mapDataUrl) {
    console.error("window.GARAGE_SALE.mapDataUrl missing.");
    return;
  }

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

  const isLoggedIn = !!cfg.isLoggedIn;
  const userRole = cfg.userRole || "";
  const canShop = isLoggedIn && userRole === "CUSTOMER";

  fetch(mapDataUrl, { credentials: "same-origin" })
    .then(async (r) => {
      const ct = (r.headers.get("content-type") || "").toLowerCase();
      const text = await r.text();

      if (!ct.includes("application/json")) {
        throw new Error(
          `Map data returned non-JSON (${r.status}). First 120 chars: ${text.slice(0, 120)}`
        );
      }

      return JSON.parse(text);
    })
    .then((data) => {
      const events = (data && data.events) || [];

      if (!events.length) {
        L.popup()
          .setLatLng(map.getCenter())
          .setContent(
            `<b>No active garage sales today.</b><br/>
             <span class="muted">
               Try <a href="${eventsListUrl}">View Events</a> or
               <a href="${createEventUrl}">Create Event</a>.
             </span>`
          )
          .openOn(map);
        return;
      }

      const bounds = [];

      events.forEach((ev) => {
        const lat = ev && ev.lat;
        const lng = ev && ev.lng;

        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;

        bounds.push([lat, lng]);

        const marker = L.marker([lat, lng]).addTo(map);

        const title = esc(ev.title || "Garage Sale");
        const locationName = esc(ev.location_name || "");

        const itemsUrl = ev.items_url || "#";

        const itemsAction = canShop
          ? `<a class="btn btn-black" href="${itemsUrl}">View items</a>`
          : `<span class="muted">Login as a Customer to view items.</span>`;

        const popupHtml = `
          <div style="min-width:240px">
            <strong>${title}</strong><br/>
            <div class="muted">${locationName}</div>
            <div style="margin-top:10px">
              ${itemsAction}
            </div>
          </div>
        `;

        marker.bindPopup(popupHtml);
      });

      if (bounds.length) {
        map.fitBounds(bounds, { padding: [30, 30] });
      }
    })
    .catch((err) => {
      console.error("Garage Sale map error:", err);

      // Optional: show a user-friendly popup instead of “nothing happens”
      L.popup()
        .setLatLng(map.getCenter())
        .setContent(
          `<b>Couldn’t load garage sale pins.</b><br/>
           <span class="muted">${esc(err.message || "Unknown error")}</span>`
        )
        .openOn(map);
    });
});

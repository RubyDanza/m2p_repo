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

  const cfg = window.PHYSIO || {};
  const center = (cfg.defaultMap && cfg.defaultMap.center) || [-37.8136, 144.9631];
  const zoom = (cfg.defaultMap && cfg.defaultMap.zoom) || 10;

  const map = L.map("map").setView(center, zoom);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(map);

  const csrfToken = (() => {
    const name = "csrftoken=";
    const parts = (document.cookie || "").split(";").map((s) => s.trim());
    for (const p of parts) {
      if (p.startsWith(name)) return decodeURIComponent(p.slice(name.length));
    }
    return "";
  })();

  const esc = (s) =>
    String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));

  function todayISO() {
    const d = new Date();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${d.getFullYear()}-${mm}-${dd}`;
  }

  async function fetchJSON(url, opts = {}) {
    const res = await fetch(url, { credentials: "same-origin", ...opts });

    const contentType = (res.headers.get("content-type") || "").toLowerCase();
    const text = await res.text();

    if (!res.ok) {
      console.error("API error:", res.status, text.slice(0, 300));
      return { ok: false, error: `Server error (${res.status}). Check runserver console.` };
    }

    if (!contentType.includes("application/json")) {
      console.error("Non-JSON response:", text.slice(0, 300));
      return { ok: false, error: "Server returned non-JSON response. Check runserver console." };
    }

    return JSON.parse(text);
  }

  async function loadPins() {
    if (!cfg.mapDataUrl) throw new Error("PHYSIO.mapDataUrl is missing");

    const data = await fetchJSON(cfg.mapDataUrl);
    if (!data || data.ok === false) throw new Error(data?.error || "Failed to load map data");

    const locs = data.locations || [];
    locs.forEach((loc) => {
      const lat = Number(loc.lat);
      const lng = Number(loc.lng);
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;

      const m = L.marker([lat, lng]).addTo(map);
      m.on("click", () => openLocationWorkflow(m, loc));
    });
  }

  async function openLocationWorkflow(marker, loc) {
    const dateVal = todayISO();

    marker
      .bindPopup(`
        <div style="min-width:260px">
          <div><b>${esc(loc.name)}</b></div>
          <div class="text-muted" style="font-size:12px;margin-bottom:6px">Choose date → time → consultant</div>

          <label style="font-size:12px">Date</label>
          <input id="p_date_${loc.id}" type="date" value="${dateVal}"
                 style="width:100%;padding:6px;margin-bottom:8px"/>

          <div id="p_slots_${loc.id}" style="margin-bottom:8px">Loading times…</div>
          <div id="p_cons_${loc.id}" style="margin-bottom:8px"></div>
          <div id="p_msg_${loc.id}" style="font-size:12px;color:#666"></div>
        </div>
      `)
      .openPopup();

    async function loadSlots() {
      const dateInput = document.getElementById(`p_date_${loc.id}`);
      if (!dateInput) return;

      const dateStr = dateInput.value;

      const slotDiv = document.getElementById(`p_slots_${loc.id}`);
      const consDiv = document.getElementById(`p_cons_${loc.id}`);
      const msgDiv = document.getElementById(`p_msg_${loc.id}`);

      if (!slotDiv || !consDiv || !msgDiv) return;

      consDiv.innerHTML = "";
      msgDiv.textContent = "";

      if (!cfg.timeslotsUrl) {
        slotDiv.innerHTML = `<div style="color:#b00">timeslotsUrl not configured.</div>`;
        return;
      }

      const url = `${cfg.timeslotsUrl}?location_id=${loc.id}&date=${encodeURIComponent(dateStr)}`;
      const data = await fetchJSON(url);

      if (!data.ok) {
        slotDiv.innerHTML = `<div style="color:#b00">${esc(data.error || "Error loading times")}</div>`;
        return;
      }

      const slots = data.slots || [];
      if (!slots.length) {
        slotDiv.innerHTML = `<div class="text-muted">No times available.</div>`;
        return;
      }

      slotDiv.innerHTML = slots
        .map(
          (t) => `
          <button type="button" data-time="${t}"
            style="margin:2px 4px 2px 0;padding:4px 8px;border:1px solid #ccc;border-radius:8px;background:#fff;cursor:pointer">
            ${t}
          </button>
        `
        )
        .join("");

      slotDiv.onclick = (e) => {
        const btn = e.target.closest("button[data-time]");
        if (!btn) return;
        loadConsultants(btn.getAttribute("data-time"));
      };
    }

    async function loadConsultants(timeStr) {
      const dateInput = document.getElementById(`p_date_${loc.id}`);
      if (!dateInput) return;

      const dateStr = dateInput.value;

      const consDiv = document.getElementById(`p_cons_${loc.id}`);
      const msgDiv = document.getElementById(`p_msg_${loc.id}`);
      if (!consDiv || !msgDiv) return;

      consDiv.innerHTML = "";
      msgDiv.style.color = "#666";
      msgDiv.textContent = `Loading consultants for ${timeStr}...`;

      if (!cfg.isLoggedIn) {
        msgDiv.innerHTML = `Please <a href="${cfg.loginUrl}">login</a> to see consultants.`;
        return;
      }
      if (cfg.userRole !== "CUSTOMER") {
        msgDiv.textContent = "Only customers can book appointments.";
        return;
      }
      if (!cfg.consultantsUrl) {
        msgDiv.style.color = "#b00";
        msgDiv.textContent = "consultantsUrl not configured.";
        return;
      }

      const url =
        `${cfg.consultantsUrl}?location_id=${loc.id}` +
        `&date=${encodeURIComponent(dateStr)}&time=${encodeURIComponent(timeStr)}`;

      const data = await fetchJSON(url);
      msgDiv.textContent = "";

      if (!data.ok) {
        consDiv.innerHTML = `<div style="color:#b00">${esc(data.error || "Error loading consultants")}</div>`;
        return;
      }

      const consultants = data.consultants || [];
      if (!consultants.length) {
        consDiv.innerHTML = `<div class="text-muted">No consultants available for ${esc(timeStr)}.</div>`;
        return;
      }

      consDiv.innerHTML = `
        <div style="font-size:12px;margin:6px 0 4px">Available consultants for <b>${esc(timeStr)}</b>:</div>
        ${consultants
          .map(
            (c) => `
          <button data-cid="${c.id}"
            style="margin:2px 4px 2px 0;padding:4px 8px;border:1px solid #0a7;border-radius:8px;background:#eafff7;cursor:pointer">
            ${esc(c.name)}
          </button>
        `
          )
          .join("")}
      `;

      consDiv.querySelectorAll("button[data-cid]").forEach((btn) => {
        btn.addEventListener("click", () => book(timeStr, btn.getAttribute("data-cid")));
      });
    }

    async function book(timeStr, consultantId) {
      const dateInput = document.getElementById(`p_date_${loc.id}`);
      const msgDiv = document.getElementById(`p_msg_${loc.id}`);
      if (!dateInput || !msgDiv) return;

      const dateStr = dateInput.value;

      msgDiv.style.color = "#666";
      msgDiv.textContent = "Booking…";

      if (!cfg.bookUrl) {
        msgDiv.style.color = "#b00";
        msgDiv.textContent = "bookUrl not configured.";
        return;
      }

      const payload = {
        location_id: loc.id,
        consultant_id: consultantId,
        date: dateStr,
        time: timeStr,
      };

      const data = await fetchJSON(cfg.bookUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify(payload),
      });

      if (!data.ok) {
        msgDiv.style.color = "#b00";
        msgDiv.textContent = data.error || "Booking failed";
        return;
      }

      msgDiv.style.color = "#0a7";
      msgDiv.textContent = `✅ Requested! (Appointment #${data.appointment_id})`;
    }

    // Wire date change + initial load
    setTimeout(() => {
      const dateInput = document.getElementById(`p_date_${loc.id}`);
      if (dateInput) dateInput.addEventListener("change", loadSlots);
      loadSlots();
    }, 0);
  }

  loadPins().catch((err) => console.error("Physio map error:", err));
});
"use strict";

/**
 * Rafraîchissement AJAX du dashboard (aucune dépendance externe).
 * Chaque élément [data-field="a.b.c"] est mis à jour avec la valeur
 * correspondante du JSON renvoyé par l'endpoint de statut.
 */

function getByPath(obj, path) {
  return path.split(".").reduce(function (acc, key) {
    return acc == null ? undefined : acc[key];
  }, obj);
}

function formatDuration(seconds) {
  if (seconds == null) return "-";
  seconds = Math.floor(seconds);
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (d) return d + "j " + String(h).padStart(2, "0") + "h" + String(m).padStart(2, "0");
  if (h) return h + "h" + String(m).padStart(2, "0");
  return m + "m" + String(s).padStart(2, "0");
}

function applyStatus(data) {
  document.querySelectorAll("[data-field]").forEach(function (el) {
    const value = getByPath(data, el.getAttribute("data-field"));

    if (el.hasAttribute("data-bool")) {
      el.textContent = value ? "Oui" : "Non";
    } else if (el.hasAttribute("data-duration")) {
      el.textContent = formatDuration(value);
    } else if (el.hasAttribute("data-badge")) {
      const active = Boolean(value);
      el.textContent = active ? "ACTIF" : "repos";
      el.classList.toggle("badge-on", active);
      el.classList.toggle("badge-off", !active);
    } else {
      el.textContent = value == null ? "-" : value;
    }
  });
}

function startDashboardPolling(url, intervalMs) {
  intervalMs = intervalMs || 5000;
  async function refresh() {
    try {
      const resp = await fetch(url, { headers: { "Accept": "application/json" } });
      if (resp.ok) applyStatus(await resp.json());
    } catch (err) {
      /* réseau indisponible : on réessaiera au prochain tick */
    } finally {
      // setTimeout (et non setInterval) : on ne replanifie qu'une fois le
      // fetch précédent terminé, pour ne jamais empiler plusieurs requêtes
      // /api/status en vol si une réponse tarde.
      setTimeout(refresh, intervalMs);
    }
  }
  refresh();
}

window.startDashboardPolling = startDashboardPolling;

/**
 * Ouvre/ferme le tiroir de navigation mobile.
 * @param {boolean} [force] true pour ouvrir, false pour fermer, absent = bascule.
 */
function toggleNav(force) {
  const nav = document.getElementById("main-nav");
  const backdrop = document.getElementById("nav-backdrop");
  const toggle = document.querySelector(".nav-toggle");
  if (!nav) return;
  const open = force === undefined ? !nav.classList.contains("open") : force;
  nav.classList.toggle("open", open);
  if (backdrop) backdrop.classList.toggle("open", open);
  if (toggle) toggle.setAttribute("aria-expanded", String(open));
}

window.toggleNav = toggleNav;

// Ferme le tiroir avec la touche Échap.
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") toggleNav(false);
});

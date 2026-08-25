/* PolyTrade Engine — front sans dépendance ni étape de build.
 *
 * Principe directeur : ne jamais inventer de donnée. Quand l'API renvoie une
 * erreur, l'interface affiche la cause exacte. Un tableau vide reste vide,
 * un prix indisponible reste un tiret. C'est le pendant côté front du choix
 * fait dans market.py (suppression du fallback vers des données factices) :
 * un opérateur doit pouvoir distinguer « pas de liquidité » de « API en
 * panne », sinon il prend des décisions sur du vide.
 */

"use strict";

const $ = (id) => document.getElementById(id);

/** Appelle l'API et remonte le `detail` de FastAPI en message d'erreur. */
async function api(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // Réponse non-JSON : on garde payload à null et on retombe sur le statut.
  }
  if (!response.ok) {
    const detail = payload && payload.detail ? payload.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return payload;
}

/* ------------------------------------------------------------- formatage */

const dash = "—";

function price(value) {
  return typeof value === "number" ? value.toFixed(4) : dash;
}

function integer(value) {
  return typeof value === "number" ? value.toLocaleString("fr-FR", { maximumFractionDigits: 0 }) : dash;
}

function money(value) {
  return typeof value === "number"
    ? "$" + value.toLocaleString("fr-FR", { maximumFractionDigits: 0 })
    : dash;
}

function signed(value, digits = 3) {
  if (typeof value !== "number") return dash;
  return (value > 0 ? "+" : "") + value.toFixed(digits);
}

function setChip(el, text, kind) {
  el.textContent = text;
  el.className = "chip" + (kind ? " chip--" + kind : "");
}

function showBanner(title, body) {
  $("banner-title").textContent = title;
  $("banner-body").textContent = body;
  $("banner").hidden = false;
}

function hideBanner() {
  $("banner").hidden = true;
}

/** Désactive un bouton pendant l'appel, pour éviter les requêtes en rafale. */
async function withBusy(button, label, fn) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  try {
    await fn();
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

/* ---------------------------------------------------------------- status */

async function loadStatus() {
  try {
    const data = await api("/api/status");

    // Le bandeau demo reste affiche tant que le mode est actif : ce n'est pas
    // une notification que l'on chasse, c'est un etat.
    $("demo-banner").hidden = data.demo !== true;

    $("v-wallet").textContent = data.wallet || dash;
    $("v-chain").textContent = data.chain_id ?? dash;
    $("v-clob").textContent = data.clob_reachable ? "joignable" : "injoignable";
    $("v-trading").textContent = data.trading_enabled ? "ACTIVÉ" : "désactivé";
    $("v-builder").textContent = data.builder_mode || dash;
    $("v-creds").textContent = data.api_creds_configured ? "fournies" : "à dériver";

    setChip($("chip-clob"), data.clob_reachable ? "CLOB joignable" : "CLOB injoignable",
      data.clob_reachable ? "ok" : "err");
    // Le trading activé est un avertissement, pas un succès : des fonds réels
    // peuvent partir.
    setChip($("chip-trading"), data.trading_enabled ? "Trading ACTIVÉ" : "Lecture seule",
      data.trading_enabled ? "warn" : "ok");
    setChip($("chip-builder"), data.builder_active ? "Builder actif" : "Builder inactif",
      data.builder_active ? "ok" : null);

    if (data.demo) {
      // En demo, le CLOB est simule joignable : pas de bandeau d'erreur.
      hideBanner();
    } else if (!data.clob_reachable) {
      showBanner(
        "Polymarket injoignable depuis ce réseau",
        "Le CLOB ne répond pas. Si la résolution DNS renvoie une IP hors de " +
          "l'infrastructure Polymarket, le domaine est filtré sur ce réseau — " +
          "un blocage réglementaire produit exactement ce symptôme. Les analyses " +
          "hors ligne restent disponibles ; les données de marché, non.",
      );
    } else {
      hideBanner();
    }
  } catch (error) {
    setChip($("chip-clob"), "Erreur", "err");
    showBanner("Impossible de lire l'état du moteur", error.message);
  }
}

/* --------------------------------------------------------------- marchés */

async function loadMarkets() {
  const limit = Math.max(1, Math.min(100, Number($("limit").value) || 10));
  const state = $("markets-state");
  const table = $("markets-table");
  const body = $("markets-body");

  state.className = "state";
  state.textContent = "Interrogation de l'API Gamma…";
  table.hidden = true;

  try {
    const data = await api(`/api/markets?limit=${limit}`);
    body.replaceChildren();

    if (!data.markets || data.markets.length === 0) {
      state.textContent = "Aucun marché actif retourné par Gamma.";
      return;
    }

    for (const market of data.markets) {
      const row = document.createElement("tr");

      const question = document.createElement("td");
      question.textContent = market.question || "(sans intitulé)";
      if (market.event) {
        const event = document.createElement("span");
        event.className = "event";
        event.textContent = market.event;
        question.appendChild(event);
      }

      const volume = document.createElement("td");
      volume.className = "num";
      volume.textContent = money(market.volume_24h);

      const tokens = document.createElement("td");
      for (const side of ["YES", "NO"]) {
        const id = market.tokens ? market.tokens[side] : null;
        if (!id) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "token-btn";
        button.textContent = side;
        button.title = id;
        // Un clic renvoie l'identifiant vers le panneau d'analyse : c'est le
        // chemin normal, personne ne copie un token id à la main.
        button.addEventListener("click", () => {
          $("token").value = id;
          loadBook();
          $("book-state").scrollIntoView({ behavior: "smooth", block: "center" });
        });
        tokens.appendChild(button);
      }
      if (!tokens.childElementCount) tokens.textContent = dash;

      row.append(question, volume, tokens);
      body.appendChild(row);
    }

    state.textContent = `${data.count} marché(s) chargé(s).`;
    table.hidden = false;
  } catch (error) {
    state.className = "state state--err";
    state.textContent = error.message;
  }
}

/* ---------------------------------------------------------------- carnet */

async function loadBook() {
  const token = $("token").value.trim();
  const size = Math.max(0, Number($("size").value) || 0);
  const state = $("book-state");
  const result = $("book-result");

  if (!token) {
    state.className = "state state--err";
    state.textContent = "Renseigne un identifiant de token.";
    result.hidden = true;
    return;
  }

  state.className = "state";
  state.textContent = "Lecture du carnet…";
  result.hidden = true;

  try {
    const query = size > 0 ? `?size=${size}` : "";
    const data = await api(`/api/book/${encodeURIComponent(token)}${query}`);

    $("m-bid").textContent = price(data.best_bid);
    $("m-ask").textContent = price(data.best_ask);
    $("m-mid").textContent = price(data.midpoint);
    $("m-spread").textContent = price(data.spread);
    $("m-bps").textContent =
      typeof data.spread_bps === "number" ? Math.round(data.spread_bps) : dash;
    $("m-liquid").textContent = data.crossed ? "croisé" : data.liquid ? "liquide" : "illiquide";

    $("m-biddepth").textContent = integer(data.bid_depth);
    $("m-askdepth").textContent = integer(data.ask_depth);
    $("m-imb").textContent = signed(data.imbalance);

    // Largeur de la barre proportionnelle à la profondeur de chaque côté.
    const total = (data.bid_depth || 0) + (data.ask_depth || 0);
    const bidPct = total > 0 ? ((data.bid_depth || 0) / total) * 100 : 50;
    $("bar-bid").style.width = bidPct + "%";
    $("bar-ask").style.width = 100 - bidPct + "%";

    const sim = $("sim");
    if (data.simulation) {
      sim.hidden = false;
      $("sim-body").textContent = data.simulation.error
        ? `${integer(data.simulation.size)} parts : ${data.simulation.error}`
        : `${integer(data.simulation.size)} parts → prix moyen ` +
          `${price(data.simulation.avg_price)}, slippage ` +
          `${Math.round(data.simulation.slippage_bps)} bps`;
    } else {
      sim.hidden = true;
    }

    state.textContent = data.crossed
      ? "Carnet croisé : donnée périmée, ou fenêtre d'arbitrage."
      : `${data.levels_bid} niveau(x) bid / ${data.levels_ask} ask.`;
    result.hidden = false;
  } catch (error) {
    state.className = "state state--err";
    state.textContent = error.message;
  }
}

/* --------------------------------------------------------------- builder */

async function loadBuilder() {
  const state = $("builder-state");
  state.className = "state";
  state.textContent = "Vérification…";

  try {
    const data = await api("/api/builder?trades=true");

    if (data.active) {
      state.textContent = `Attribution active — mode : ${data.mode}.`;
      return;
    }

    state.textContent =
      `Mode : ${data.mode}. Aucune attribution active. ` +
      (data.trades_error ||
        "Les credentials builder sont délivrées par Polymarket après candidature.") +
      " Voir docs/BUILDER.md.";
  } catch (error) {
    state.className = "state state--err";
    state.textContent = error.message;
  }
}

/* ----------------------------------------------------------------- liens */

$("btn-refresh").addEventListener("click", (event) =>
  withBusy(event.currentTarget, "…", loadStatus),
);
$("btn-markets").addEventListener("click", (event) =>
  withBusy(event.currentTarget, "…", loadMarkets),
);
$("btn-book").addEventListener("click", (event) => withBusy(event.currentTarget, "…", loadBook));
$("btn-builder").addEventListener("click", (event) =>
  withBusy(event.currentTarget, "…", loadBuilder),
);

$("token").addEventListener("keydown", (event) => {
  if (event.key === "Enter") loadBook();
});

loadStatus();

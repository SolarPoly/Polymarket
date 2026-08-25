"""API HTTP exposant le moteur au front.

Principes :

* **Lecture seule.** Aucune route ne place d'ordre. Le coupe-circuit du
  moteur reste la dernière ligne de défense, mais l'API ne l'atteint jamais :
  passer un ordre demande d'écrire du code, pas de cliquer.
* **Les pannes remontent telles quelles.** Une indisponibilité Polymarket
  renvoie un 503 avec la cause, jamais des données de substitution. Le front
  affiche l'erreur ; il ne fait pas semblant d'avoir des prix.
* **Aucun secret n'est exposé.** Aucune route ne renvoie de clé, de secret ni
  de passphrase. `/api/status` publie l'adresse du wallet — publique par
  nature — et des booléens de configuration.
* **Écoute locale par défaut.** Le serveur donne accès à un wallet capable de
  signer : il ne doit pas être exposé sur un réseau sans authentification.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .analytics import analyze_book, parse_levels, slippage
from .client import PolymarketEngine
from .config import Settings
from .demo import DEMO_WALLET, demo_book, demo_markets
from .errors import ClobError, ConfigError, MarketDataError
from .market import GammaMarketScanner
from .scanner import MarketScan, rank_by_opportunity, scan_markets

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _demo_enabled() -> bool:
    """Mode demonstration : opt-in strict, jamais declenche par une panne."""
    return os.getenv("POLY_DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_engine() -> PolymarketEngine:
    """Moteur unique, construit à la première requête.

    Mis en cache : dériver l'adresse du wallet et instancier le client SDK à
    chaque requête serait du gaspillage pur.
    """
    load_dotenv()
    return PolymarketEngine(Settings.from_env())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    return Settings.from_env()


def create_app() -> FastAPI:
    app = FastAPI(
        title="PolyTrade Engine",
        description="Interface de lecture et d'analyse des marchés Polymarket.",
        version="1.0.0",
    )

    # ------------------------------------------------------------------ status

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        """Configuration, wallet et connectivité réelle du CLOB."""
        if _demo_enabled():
            # Aucune cle lue, aucun reseau touche : la demo doit tourner sans
            # configuration valide.
            return {
                "demo": True,
                "wallet": DEMO_WALLET,
                "chain_id": 137,
                "clob_host": "(demonstration)",
                "clob_reachable": True,
                "trading_enabled": False,
                "builder_mode": "non configure",
                "builder_active": False,
                "api_creds_configured": False,
            }

        try:
            settings = get_settings()
            engine = get_engine()
        except ConfigError as exc:
            raise HTTPException(status_code=500, detail=f"Configuration invalide : {exc}") from exc

        reachable = engine.health_check()
        return {
            "demo": False,
            "wallet": engine.address,
            "chain_id": settings.chain_id,
            "clob_host": settings.clob_host,
            "clob_reachable": reachable,
            "trading_enabled": settings.enable_trading,
            "builder_mode": settings.builder.mode,
            "builder_active": engine.builder_enabled,
            "api_creds_configured": settings.api_creds is not None,
        }

    # ----------------------------------------------------------------- marchés

    @app.get("/api/markets")
    def markets(limit: int = Query(default=10, ge=1, le=100)) -> dict[str, Any]:
        """Marchés actifs via l'API Gamma.

        Renvoie 503 si Gamma est injoignable — jamais de données factices.
        """
        if _demo_enabled():
            raw = demo_markets(limit)
            rows = [
                {
                    "question": m.get("question"),
                    "event": m.get("event_title"),
                    "volume_24h": GammaMarketScanner.volume_24h(m),
                    "tokens": GammaMarketScanner.get_market_tokens(m),
                }
                for m in raw
            ]
            return {"demo": True, "count": len(rows), "markets": rows}

        settings = get_settings()
        try:
            with GammaMarketScanner(settings.gamma_host, settings.request_timeout) as scanner:
                raw = scanner.get_active_markets(limit=limit)
                # Helpers appelés sur l'instance (et non sur la classe) : un
                # seul point de substitution suffit alors pour les tests.
                rows = [
                    {
                        "question": m.get("question"),
                        "event": m.get("event_title"),
                        "volume_24h": scanner.volume_24h(m),
                        "tokens": scanner.get_market_tokens(m),
                    }
                    for m in raw
                ]
        except MarketDataError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {"demo": False, "count": len(rows), "markets": rows}

    # ------------------------------------------------------------------ carnet

    @app.get("/api/book/{token_id}")
    def book(token_id: str, size: float = Query(default=0, ge=0)) -> dict[str, Any]:
        """Analyse du carnet d'un token, avec simulation d'achat optionnelle."""
        if _demo_enabled():
            raw: Any = demo_book(token_id)
        else:
            engine = get_engine()
            try:
                raw = engine.get_order_book(token_id)
            except ClobError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

        analysis = analyze_book(raw)
        payload: dict[str, Any] = {
            "demo": _demo_enabled(),
            "token_id": token_id,
            "best_bid": analysis.best_bid,
            "best_ask": analysis.best_ask,
            "midpoint": analysis.midpoint,
            "spread": analysis.spread,
            "spread_bps": analysis.spread_bps,
            "bid_depth": analysis.bid_depth,
            "ask_depth": analysis.ask_depth,
            "bid_notional": analysis.bid_notional,
            "ask_notional": analysis.ask_notional,
            "levels_bid": analysis.levels_bid,
            "levels_ask": analysis.levels_ask,
            "imbalance": analysis.imbalance,
            "crossed": analysis.is_crossed,
            "liquid": analysis.is_liquid,
        }

        if size > 0:
            asks = sorted(parse_levels(getattr(raw, "asks", None)), key=lambda lvl: lvl.price)
            result = slippage(asks, size)
            payload["simulation"] = (
                {"size": size, "avg_price": result[0], "slippage_bps": result[1]}
                if result is not None
                else {"size": size, "error": "profondeur insuffisante"}
            )

        return payload

    # ----------------------------------------------------------------- builder

    @app.get("/api/builder")
    def builder(trades: bool = False) -> dict[str, Any]:
        """Statut d'attribution builder, et trades associés si demandé."""
        if _demo_enabled():
            return {
                "demo": True,
                "mode": "non configure",
                "configured": False,
                "active": False,
                "trades_error": "Mode demonstration : aucune attribution reelle.",
            }

        settings = get_settings()
        engine = get_engine()
        active = engine.builder_enabled

        payload: dict[str, Any] = {
            "demo": False,
            "mode": settings.builder.mode,
            "configured": settings.builder.is_configured,
            "active": active,
        }

        if trades:
            if not active:
                payload["trades_error"] = (
                    "Credentials builder absentes. Elles sont délivrées par "
                    "Polymarket après candidature : voir docs/BUILDER.md."
                )
            else:
                try:
                    payload["trades"] = engine.get_builder_trades()
                except ClobError as exc:
                    payload["trades_error"] = str(exc)

        return payload

    # ------------------------------------------------------------------ scan

    def _serialize_scan(scan: MarketScan) -> dict[str, Any]:
        best = scan.best_opportunity
        return {
            "question": scan.question,
            "event": scan.event,
            "yes_token": scan.yes_token,
            "no_token": scan.no_token,
            "touch_sum": scan.touch_sum,
            "touch_edge": scan.touch_edge,
            "total_depth": scan.total_depth,
            "tradable": scan.tradable,
            "error": scan.error,
            "yes_spread_bps": scan.yes.spread_bps if scan.yes else None,
            "no_spread_bps": scan.no.spread_bps if scan.no else None,
            "opportunity": (
                {
                    "kind": best.kind,
                    "size": best.size,
                    "yes_price": best.yes_price,
                    "no_price": best.no_price,
                    "profit_per_set": best.profit_per_set,
                    "total_profit": best.total_profit,
                    "edge_bps": best.edge_bps,
                }
                if best
                else None
            ),
        }

    @app.get("/api/scan")
    def scan(
        limit: int = Query(default=10, ge=1, le=50),
        size: float = Query(default=100, gt=0, le=1_000_000),
    ) -> dict[str, Any]:
        """Balaie les marchés actifs et classe les écarts exploitables.

        L'écart est calculé au volume `size`, en traversant réellement les deux
        carnets : un écart visible au meilleur prix mais sans profondeur n'est
        pas retourné.
        """
        if _demo_enabled():
            raw = demo_markets(limit)
            fetch = demo_book
            tokens_of = GammaMarketScanner.get_market_tokens
        else:
            settings = get_settings()
            engine = get_engine()
            try:
                with GammaMarketScanner(settings.gamma_host, settings.request_timeout) as gamma:
                    raw = gamma.get_active_markets(limit=limit)
                    tokens_of = gamma.get_market_tokens
            except MarketDataError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            fetch = engine.get_order_book

        scans = rank_by_opportunity(scan_markets(fetch, raw, tokens_of, size=size))
        rows = [_serialize_scan(item) for item in scans]
        return {
            "demo": _demo_enabled(),
            "size": size,
            "count": len(rows),
            "with_opportunity": sum(1 for r in rows if r["opportunity"]),
            "markets": rows,
        }

    # -------------------------------------------------------------- front

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")
    else:  # pragma: no cover - seulement si le dossier web/ est absent
        logger.warning("Dossier web/ introuvable : l'API tourne sans interface.")

    return app


app = create_app()

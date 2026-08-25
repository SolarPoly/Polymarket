#!/usr/bin/env python3
"""PolyTrade Engine — CLI.

Toutes les sous-commandes sont en lecture seule : aucune ne place d'ordre.
Passer un ordre exige `POLY_ENABLE_TRADING=true` et un appel explicite à
`PolymarketEngine.place_limit_order` depuis ton propre code.

Sous-commandes :
    check     config, wallet, connectivité CLOB, statut builder
    markets   marchés actifs via l'API Gamma
    book      analyse du carnet d'ordres d'un token
    builder   statut d'attribution builder et trades associés
    scan      balaie les marches et classe les ecarts d'arbitrage
    creds     dérive les credentials L2 depuis la clé privée
    serve     lance l'interface web (écoute locale par défaut)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import TypedDict

from dotenv import load_dotenv

from src.analytics import analyze_book, parse_levels, slippage
from src.client import PolymarketEngine
from src.config import Settings
from src.errors import ClobError, ConfigError, MarketDataError, PolyTradeError
from src.market import GammaMarketScanner
from src.scanner import rank_by_opportunity, scan_markets

logger = logging.getLogger("polytrade")

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_NETWORK = 3


class MarketRow(TypedDict):
    """Ligne de marché normalisée pour l'affichage et la sortie JSON."""

    question: str | None
    event: str | None
    volume_24h: float
    tokens: dict[str, str | None]


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="polytrade",
        description="Moteur Polymarket — CLI de lecture et d'analyse.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="logs de debug")
    parser.add_argument("--json", action="store_true", help="sortie JSON")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="config, wallet, connectivité, statut builder")

    p_markets = sub.add_parser("markets", help="marchés actifs (API Gamma)")
    p_markets.add_argument("--limit", type=int, default=5, help="nombre de marchés (défaut : 5)")

    p_book = sub.add_parser("book", help="analyse du carnet d'un token")
    p_book.add_argument("token_id", help="identifiant CLOB du token (YES ou NO)")
    p_book.add_argument(
        "--size", type=float, default=0, help="simule le slippage pour cette taille"
    )

    p_scan = sub.add_parser("scan", help="balaie les marches et classe les ecarts d'arbitrage")
    p_scan.add_argument("--limit", type=int, default=10, help="marches a balayer (defaut : 10)")
    p_scan.add_argument(
        "--size", type=float, default=100, help="volume vise pour le calcul (defaut : 100)"
    )
    p_scan.add_argument(
        "--only-opportunities", action="store_true", help="masque les marches sans ecart"
    )

    p_builder = sub.add_parser("builder", help="statut builder et trades attribués")
    p_builder.add_argument("--trades", action="store_true", help="liste les trades attribués")

    sub.add_parser("creds", help="dérive les credentials L2 (affiche la clé, pas les secrets)")

    p_serve = sub.add_parser("serve", help="lance l'interface web (lecture seule)")
    p_serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="interface d'écoute (défaut : 127.0.0.1, local uniquement)",
    )
    p_serve.add_argument("--port", type=int, default=8000, help="port (défaut : 8000)")
    p_serve.add_argument("--reload", action="store_true", help="rechargement à chaud (dev)")
    p_serve.add_argument(
        "--demo",
        action="store_true",
        help="donnees de demonstration, sans reseau ni wallet (etiquetees partout)",
    )

    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "markets"
        args.limit = 5
    return args


def _load() -> tuple[Settings, PolymarketEngine]:
    settings = Settings.from_env()
    return settings, PolymarketEngine(settings)


# ----------------------------------------------------------------- commandes


def cmd_check(settings: Settings, engine: PolymarketEngine, as_json: bool) -> int:
    reachable = engine.health_check()
    if not reachable:
        logger.error(
            "CLOB %s injoignable. Si la résolution DNS renvoie une IP hors "
            "infrastructure Polymarket, le domaine est filtré sur ce réseau.",
            settings.clob_host,
        )

    payload = {
        "wallet": engine.address,
        "chain_id": settings.chain_id,
        "clob_reachable": reachable,
        "trading_enabled": settings.enable_trading,
        "builder_mode": settings.builder.mode,
        "builder_active": engine.builder_enabled,
        "api_creds_configured": settings.api_creds is not None,
    }

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Wallet            : {payload['wallet']}")
        print(f"Chain             : {payload['chain_id']}")
        print(f"CLOB joignable    : {'oui' if reachable else 'NON'}")
        print(f"Trading           : {'ACTIVÉ' if settings.enable_trading else 'désactivé'}")
        print(f"Builder           : {payload['builder_mode']}")
        print(f"Builder actif     : {'oui' if payload['builder_active'] else 'non'}")
        print(f"Creds L2          : {'fournies' if settings.api_creds else 'à dériver'}")

    return EXIT_OK if reachable else EXIT_NETWORK


def cmd_markets(settings: Settings, engine: PolymarketEngine, limit: int, as_json: bool) -> int:
    with GammaMarketScanner(settings.gamma_host, settings.request_timeout) as scanner:
        markets = scanner.get_active_markets(limit=limit)
        rows: list[MarketRow] = [
            {
                "question": m.get("question"),
                "event": m.get("event_title"),
                "volume_24h": GammaMarketScanner.volume_24h(m),
                "tokens": GammaMarketScanner.get_market_tokens(m),
            }
            for m in markets
        ]

    if as_json:
        print(json.dumps({"wallet": engine.address, "markets": rows}, indent=2, ensure_ascii=False))
        return EXIT_OK

    if not rows:
        print("Aucun marché actif retourné par Gamma.")
        return EXIT_OK

    print(f"\n{len(rows)} marché(s) actif(s) — wallet {engine.address}\n")
    for i, row in enumerate(rows, start=1):
        print(f"[{i}] {row['question']}")
        print(f"    volume 24h : ${row['volume_24h']:,.0f}")
        print(f"    YES : {row['tokens']['YES']}")
        print(f"    NO  : {row['tokens']['NO']}")
    return EXIT_OK


def cmd_book(engine: PolymarketEngine, token_id: str, size: float, as_json: bool) -> int:
    raw = engine.get_order_book(token_id)
    analysis = analyze_book(raw)

    payload: dict[str, object] = {
        "token_id": token_id,
        "best_bid": analysis.best_bid,
        "best_ask": analysis.best_ask,
        "midpoint": analysis.midpoint,
        "spread": analysis.spread,
        "spread_bps": analysis.spread_bps,
        "bid_depth": analysis.bid_depth,
        "ask_depth": analysis.ask_depth,
        "imbalance": analysis.imbalance,
        "crossed": analysis.is_crossed,
        "liquid": analysis.is_liquid,
    }

    if size > 0:
        asks = sorted(parse_levels(getattr(raw, "asks", None)), key=lambda level: level.price)
        result = slippage(asks, size)
        # Branches hétérogènes (float vs str) : le type doit être explicite.
        simulation: dict[str, object] = {"size": size}
        if result is None:
            simulation["error"] = "profondeur insuffisante"
        else:
            simulation["avg_price"], simulation["slippage_bps"] = result
        payload["buy_simulation"] = simulation

    if as_json:
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    def fmt(value: object, suffix: str = "") -> str:
        return f"{value:.4f}{suffix}" if isinstance(value, float) else "—"

    print(f"\nCarnet — token {token_id}\n")
    print(f"  Meilleure offre (bid) : {fmt(analysis.best_bid)}")
    print(f"  Meilleure demande (ask): {fmt(analysis.best_ask)}")
    print(f"  Midpoint              : {fmt(analysis.midpoint)}")
    print(f"  Spread                : {fmt(analysis.spread)}")
    bps = analysis.spread_bps
    print(f"  Spread (bps)          : {f'{bps:.0f}' if bps is not None else '—'}")
    print(f"  Profondeur bid / ask  : {analysis.bid_depth:,.0f} / {analysis.ask_depth:,.0f}")
    imb = analysis.imbalance
    print(f"  Déséquilibre          : {f'{imb:+.3f}' if imb is not None else '—'}")
    print(f"  Liquide               : {'oui' if analysis.is_liquid else 'non'}")
    if analysis.is_crossed:
        print("  ATTENTION : carnet croisé (donnée périmée ou arbitrage).")

    sim = payload.get("buy_simulation")
    if isinstance(sim, dict):
        if "error" in sim:
            print(f"\n  Achat de {size:,.0f} parts : {sim['error']}")
        else:
            print(f"\n  Achat de {size:,.0f} parts :")
            avg = float(sim["avg_price"])  # type: ignore[arg-type]
            slip = float(sim["slippage_bps"])  # type: ignore[arg-type]
            print(f"    prix moyen  : {avg:.4f}")
            print(f"    slippage    : {slip:.0f} bps")
    return EXIT_OK


def cmd_scan(
    settings: Settings,
    engine: PolymarketEngine,
    limit: int,
    size: float,
    only_opportunities: bool,
    as_json: bool,
) -> int:
    """Balaie les marches et classe les ecarts d'arbitrage exploitables."""
    with GammaMarketScanner(settings.gamma_host, settings.request_timeout) as gamma:
        markets = gamma.get_active_markets(limit=limit)
        tokens_of = gamma.get_market_tokens

    scans = rank_by_opportunity(scan_markets(engine.get_order_book, markets, tokens_of, size=size))

    if as_json:
        print(
            json.dumps(
                [
                    {
                        "question": s.question,
                        "touch_sum": s.touch_sum,
                        "tradable": s.tradable,
                        "error": s.error,
                        "opportunity": (
                            {
                                "kind": s.best_opportunity.kind,
                                "profit_per_set": s.best_opportunity.profit_per_set,
                                "total_profit": s.best_opportunity.total_profit,
                            }
                            if s.best_opportunity
                            else None
                        ),
                    }
                    for s in scans
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return EXIT_OK

    found = [s for s in scans if s.best_opportunity]
    print()
    print(f"{len(scans)} marché(s) balayé(s), {len(found)} avec un écart au volume {size:,.0f}")
    print()

    for scan in scans:
        best = scan.best_opportunity
        if only_opportunities and not best:
            continue
        if scan.error:
            print(f"  [!] {scan.question} — {scan.error}")
            continue

        somme = f"{scan.touch_sum:.4f}" if scan.touch_sum is not None else "—"
        marque = "***" if best else "   "
        print(f"{marque} {scan.question}")
        print(f"      somme des midpoints : {somme}   profondeur : {scan.total_depth:,.0f}")
        if best:
            print(
                f"      ECART {best.kind} : {best.profit_per_set:.4f} USDC/ensemble "
                f"({best.edge_bps:.0f} bps) -> {best.total_profit:,.2f} USDC sur {best.size:,.0f}"
            )
            print(f"      prix moyens : YES {best.yes_price:.4f} / NO {best.no_price:.4f}")

    if found:
        print()
        print(
            "Rappel : les frais ne sont pas modélisés. Un écart affiché est un "
            "plafond, pas un gain net."
        )
    return EXIT_OK


def cmd_builder(settings: Settings, engine: PolymarketEngine, trades: bool, as_json: bool) -> int:
    active = engine.builder_enabled
    payload: dict[str, object] = {
        "mode": settings.builder.mode,
        "configured": settings.builder.is_configured,
        "active": active,
    }

    if trades and active:
        payload["trades"] = engine.get_builder_trades()

    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return EXIT_OK

    print(f"\nMode builder   : {payload['mode']}")
    print(f"Configuré      : {'oui' if payload['configured'] else 'non'}")
    print(f"Actif (SDK)    : {'oui' if active else 'non'}")

    if not active:
        print(
            "\nAucune attribution builder n'est active. Les credentials builder sont\n"
            "délivrés par Polymarket à l'issue d'une candidature — ils ne se\n"
            "génèrent pas localement. Voir docs/BUILDER.md."
        )
        return EXIT_OK

    if trades:
        print(f"\nTrades attribués : {payload.get('trades')}")
    return EXIT_OK


def cmd_creds(engine: PolymarketEngine, as_json: bool) -> int:
    creds = engine.ensure_api_creds()
    # Seule la clé publique est affichée : secret et passphrase restent masqués.
    payload = {"api_key": creds.api_key, "secret": "***masqué***", "passphrase": "***masqué***"}
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"api_key    : {creds.api_key}")
        print("secret     : ***masqué*** (récupérable via le SDK, non affiché)")
        print("passphrase : ***masqué***")
        print(
            "\nPour éviter un aller-retour réseau au démarrage, stocke-les dans .env\n"
            "sous CLOB_API_KEY / CLOB_API_SECRET / CLOB_API_PASSPHRASE."
        )
    return EXIT_OK


def cmd_serve(host: str, port: int, reload: bool, demo: bool = False) -> int:
    """Lance le serveur web.

    Écoute sur 127.0.0.1 par défaut : le serveur donne accès à un wallet
    capable de signer, il ne doit pas être exposé sans authentification.
    """
    try:
        import uvicorn
    except ImportError:
        logger.error(
            "uvicorn est absent. Installe les dépendances web : pip install -r requirements.txt"
        )
        return EXIT_CONFIG

    if demo:
        # Transmis par l'environnement : uvicorn --reload reimporte le module
        # dans un sous-processus, qui ne verrait pas un argument de fonction.
        os.environ["POLY_DEMO_MODE"] = "true"
        print("MODE DEMONSTRATION : donnees simulees, etiquetees dans chaque reponse.")

    if host not in {"127.0.0.1", "localhost", "::1"}:
        logger.warning(
            "Écoute sur %s : ce serveur expose un wallet capable de signer et "
            "n'a aucune authentification. Ne l'ouvre pas sur un réseau non fiable.",
            host,
        )

    print(f"Interface disponible sur http://{host}:{port}")
    uvicorn.run("src.api:app", host=host, port=port, reload=reload, log_level="info")
    return EXIT_OK


# --------------------------------------------------------------------- point d'entrée


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.verbose)
    load_dotenv()

    # `serve` est traité avant la construction du moteur : l'API l'instancie
    # elle-même à la première requête, et le mode --reload réimporte le module.
    if args.command == "serve":
        return cmd_serve(args.host, args.port, args.reload, args.demo)

    try:
        settings, engine = _load()
    except ConfigError as exc:
        logger.error("Configuration invalide : %s", exc)
        return EXIT_CONFIG
    except PolyTradeError as exc:
        logger.error("%s", exc)
        return EXIT_CONFIG

    try:
        if args.command == "check":
            return cmd_check(settings, engine, args.json)
        if args.command == "markets":
            return cmd_markets(settings, engine, args.limit, args.json)
        if args.command == "book":
            return cmd_book(engine, args.token_id, args.size, args.json)
        if args.command == "scan":
            return cmd_scan(
                settings, engine, args.limit, args.size, args.only_opportunities, args.json
            )
        if args.command == "builder":
            return cmd_builder(settings, engine, args.trades, args.json)
        if args.command == "creds":
            return cmd_creds(engine, args.json)
    except MarketDataError as exc:
        logger.error("Scan Gamma impossible : %s", exc)
        return EXIT_NETWORK
    except ClobError as exc:
        logger.error("%s", exc)
        return EXIT_NETWORK
    except ValueError as exc:
        logger.error("Argument invalide : %s", exc)
        return EXIT_CONFIG

    logger.error("Commande inconnue : %s", args.command)
    return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())

"""Détection d'arbitrage et classement de marchés.

## Le raisonnement

Sur un marché binaire Polymarket, les jetons YES et NO d'un même marché
forment un « ensemble complet » : à la résolution, exactement l'un des deux
paie 1 USDC et l'autre 0. Un ensemble complet vaut donc toujours 1 USDC,
quelle que soit l'issue. Deux écarts sont exploitables :

* **Achat** — si `ask_YES + ask_NO < 1`, acheter les deux côtés coûte moins
  que le 1 USDC garanti au dénouement. Le gain est acquis, hors frais.
* **Vente** — si `bid_YES + bid_NO > 1`, vendre les deux côtés rapporte plus
  que le coût de création d'un ensemble complet (1 USDC).

## Pourquoi le prix affiché ne suffit pas

Un scanner naïf compare les meilleurs prix (le « touch ») et annonce un écart
qui n'existe pas : le meilleur prix ne porte qu'une taille limitée. Dès qu'on
veut exécuter un volume réel, on consomme les niveaux suivants et l'écart
s'évapore — voire s'inverse.

Ce module calcule donc l'écart **au volume demandé**, en traversant réellement
le carnet des deux côtés. Si la profondeur est insuffisante d'un côté, aucune
opportunité n'est retournée : mieux vaut ne rien annoncer qu'annoncer un gain
qui suppose une liquidité absente.

Les frais ne sont pas modélisés — ils dépendent du compte et du programme
builder. Un écart calculé ici est donc un **plafond**, pas un gain net.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from .analytics import BookAnalysis, Level, analyze_book, arbitrage_edge, parse_levels, slippage

logger = logging.getLogger(__name__)

# Les appels carnet sont bloquants et dominés par la latence réseau : quelques
# threads suffisent à masquer l'attente sans matraquer l'API.
_MAX_WORKERS = 6

BUY = "achat"
SELL = "vente"


@dataclass(frozen=True)
class ArbitrageOpportunity:
    """Écart exploitable sur un marché, calculé à un volume donné."""

    kind: str
    """`BUY` (acheter les deux côtés) ou `SELL` (vendre les deux côtés)."""

    size: float
    """Nombre d'ensembles complets pris en compte dans le calcul."""

    yes_price: float
    """Prix moyen d'exécution côté YES, pas le prix affiché."""

    no_price: float
    profit_per_set: float
    """Gain en USDC par ensemble complet, avant frais."""

    @property
    def total_profit(self) -> float:
        return self.profit_per_set * self.size

    @property
    def edge_bps(self) -> float:
        """Écart en points de base du 1 USDC que vaut un ensemble complet."""
        return self.profit_per_set * 10_000


@dataclass(frozen=True)
class MarketScan:
    """Résultat de l'analyse d'un marché : ses deux carnets et ses écarts."""

    question: str | None
    event: str | None
    yes_token: str | None
    no_token: str | None
    yes: BookAnalysis | None
    no: BookAnalysis | None
    opportunities: tuple[ArbitrageOpportunity, ...] = ()
    error: str | None = None

    @property
    def touch_sum(self) -> float | None:
        """Somme des midpoints YES et NO.

        Doit valoir 1 sur un marché cohérent. L'écart à 1 est un indicateur
        de désalignement, mais **pas** un gain exécutable : voir
        `opportunities` pour ce qui est réellement traitable.
        """
        if self.yes is None or self.no is None:
            return None
        if self.yes.midpoint is None or self.no.midpoint is None:
            return None
        return self.yes.midpoint + self.no.midpoint

    @property
    def touch_edge(self) -> float | None:
        """Écart des midpoints par rapport à 1."""
        if self.yes is None or self.no is None:
            return None
        if self.yes.midpoint is None or self.no.midpoint is None:
            return None
        return arbitrage_edge(self.yes.midpoint, self.no.midpoint)

    @property
    def total_depth(self) -> float:
        """Profondeur cumulée des deux carnets, en parts."""
        total = 0.0
        for analysis in (self.yes, self.no):
            if analysis is not None:
                total += analysis.bid_depth + analysis.ask_depth
        return total

    @property
    def best_opportunity(self) -> ArbitrageOpportunity | None:
        if not self.opportunities:
            return None
        return max(self.opportunities, key=lambda o: o.profit_per_set)

    @property
    def tradable(self) -> bool:
        """Les deux côtés sont-ils cotés avec un spread raisonnable ?"""
        return (
            self.yes is not None
            and self.no is not None
            and self.yes.is_liquid
            and self.no.is_liquid
        )


def find_arbitrage(
    yes_book: Any, no_book: Any, size: float = 100.0
) -> tuple[ArbitrageOpportunity, ...]:
    """Cherche les écarts exploitables entre les carnets YES et NO.

    `size` est le nombre d'ensembles complets visés. Le calcul traverse
    réellement les carnets : un écart n'est retourné que si les deux côtés
    offrent la profondeur nécessaire.
    """
    if size <= 0:
        raise ValueError("size doit être > 0")

    yes_asks = _sorted_levels(yes_book, "asks")
    no_asks = _sorted_levels(no_book, "asks")
    yes_bids = _sorted_levels(yes_book, "bids", descending=True)
    no_bids = _sorted_levels(no_book, "bids", descending=True)

    found: list[ArbitrageOpportunity] = []

    # --- côté achat : payer moins que le 1 USDC garanti ---------------------
    buy_yes = slippage(yes_asks, size)
    buy_no = slippage(no_asks, size)
    if buy_yes is not None and buy_no is not None:
        cost = buy_yes[0] + buy_no[0]
        if cost < 1.0:
            found.append(
                ArbitrageOpportunity(
                    kind=BUY,
                    size=size,
                    yes_price=buy_yes[0],
                    no_price=buy_no[0],
                    profit_per_set=1.0 - cost,
                )
            )

    # --- côté vente : encaisser plus que le coût de création -----------------
    sell_yes = slippage(yes_bids, size)
    sell_no = slippage(no_bids, size)
    if sell_yes is not None and sell_no is not None:
        proceeds = sell_yes[0] + sell_no[0]
        if proceeds > 1.0:
            found.append(
                ArbitrageOpportunity(
                    kind=SELL,
                    size=size,
                    yes_price=sell_yes[0],
                    no_price=sell_no[0],
                    profit_per_set=proceeds - 1.0,
                )
            )

    return tuple(found)


def _sorted_levels(book: Any, side: str, descending: bool = False) -> list[Level]:
    levels = parse_levels(getattr(book, side, None))
    return sorted(levels, key=lambda lvl: -lvl.price if descending else lvl.price)


def scan_markets(
    fetch_book: Callable[[str], Any],
    markets: Sequence[dict[str, Any]],
    tokens_of: Callable[[dict[str, Any]], dict[str, str | None]],
    size: float = 100.0,
    max_workers: int = _MAX_WORKERS,
) -> list[MarketScan]:
    """Analyse une liste de marchés en parallèle.

    `fetch_book` est injecté plutôt qu'appelé sur un client concret : le même
    code sert ainsi au CLOB réel, au mode démonstration et aux tests.

    Un marché dont un carnet est illisible n'interrompt pas le balayage : il
    ressort avec son champ `error` renseigné, ce qui rend la panne visible
    sans perdre les autres résultats.
    """
    if not markets:
        return []

    def _scan_one(market: dict[str, Any]) -> MarketScan:
        tokens = tokens_of(market)
        yes_token, no_token = tokens.get("YES"), tokens.get("NO")

        if not yes_token or not no_token:
            return MarketScan(
                question=market.get("question"),
                event=market.get("event_title"),
                yes_token=yes_token,
                no_token=no_token,
                yes=None,
                no=None,
                error="marché sans paire YES/NO complète",
            )

        try:
            yes_raw = fetch_book(yes_token)
            no_raw = fetch_book(no_token)
        except Exception as exc:
            logger.warning("Carnet indisponible pour %r : %s", market.get("question"), exc)
            return MarketScan(
                question=market.get("question"),
                event=market.get("event_title"),
                yes_token=yes_token,
                no_token=no_token,
                yes=None,
                no=None,
                error=str(exc),
            )

        return MarketScan(
            question=market.get("question"),
            event=market.get("event_title"),
            yes_token=yes_token,
            no_token=no_token,
            yes=analyze_book(yes_raw),
            no=analyze_book(no_raw),
            opportunities=find_arbitrage(yes_raw, no_raw, size),
        )

    workers = max(1, min(max_workers, len(markets)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_scan_one, markets))


def rank_by_opportunity(scans: Sequence[MarketScan]) -> list[MarketScan]:
    """Trie les marchés : écart exploitable d'abord, puis liquidité.

    Un marché en erreur est relégué en fin de liste plutôt que masqué : une
    panne doit rester visible.
    """

    def key(scan: MarketScan) -> tuple[bool, float, float]:
        best = scan.best_opportunity
        return (
            scan.error is not None,  # erreurs en dernier
            -(best.profit_per_set if best else 0.0),  # meilleur écart d'abord
            -scan.total_depth,  # puis la liquidité
        )

    return sorted(scans, key=key)

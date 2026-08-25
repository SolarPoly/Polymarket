"""Analyse de carnet d'ordres.

Fonctions pures, sans I/O : entièrement testables hors ligne, ce qui compte
sur un réseau où les endpoints Polymarket peuvent être filtrés.

Convention Polymarket : un prix est une probabilité dans ]0, 1[. Un marché
binaire coté 0,42 signifie « 42 % de chances ». Les tailles sont exprimées en
parts, dont chacune paie 1 USDC si l'issue se réalise.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Level:
    """Niveau de carnet normalisé en float."""

    price: float
    size: float

    @property
    def notional(self) -> float:
        """Capital immobilisé sur ce niveau, en USDC."""
        return self.price * self.size


@dataclass(frozen=True)
class BookAnalysis:
    """Vue synthétique d'un carnet à un instant donné."""

    best_bid: float | None
    best_ask: float | None
    bid_depth: float
    ask_depth: float
    bid_notional: float
    ask_notional: float
    levels_bid: int
    levels_ask: int

    @property
    def spread(self) -> float | None:
        """Écart absolu entre meilleure offre et meilleure demande."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    @property
    def midpoint(self) -> float | None:
        """Prix milieu — l'estimation de probabilité la plus neutre."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread_bps(self) -> float | None:
        """Spread en points de base du midpoint.

        Comparable entre marchés, contrairement au spread absolu : 1 centime
        d'écart sur un marché à 0,05 est bien plus coûteux qu'à 0,50.
        """
        mid = self.midpoint
        spread = self.spread
        if mid is None or spread is None or mid <= 0:
            return None
        return (spread / mid) * 10_000

    @property
    def imbalance(self) -> float | None:
        """Déséquilibre de liquidité dans [-1, 1].

        +1 = liquidité entièrement à l'achat, -1 = entièrement à la vente,
        0 = équilibré. Indicateur de pression directionnelle.
        """
        total = self.bid_depth + self.ask_depth
        if total <= 0:
            return None
        return (self.bid_depth - self.ask_depth) / total

    @property
    def is_crossed(self) -> bool:
        """Carnet croisé : la meilleure demande dépasse la meilleure offre.

        Anomalie — donnée périmée, ou fenêtre d'arbitrage.
        """
        if self.best_bid is None or self.best_ask is None:
            return False
        return self.best_bid >= self.best_ask

    @property
    def is_liquid(self) -> bool:
        """Heuristique : deux côtés cotés et un spread sous 500 bps."""
        bps = self.spread_bps
        return bps is not None and bps < 500 and not self.is_crossed


def parse_levels(raw: Sequence[Any] | None) -> list[Level]:
    """Convertit les niveaux du SDK en `Level`, en ignorant les entrées illisibles.

    Le SDK renvoie des prix et tailles en chaînes ; un niveau non convertible
    est écarté plutôt que de faire échouer toute l'analyse.
    """
    levels: list[Level] = []
    for item in raw or []:
        price = getattr(item, "price", None)
        size = getattr(item, "size", None)
        if price is None and isinstance(item, dict):
            price, size = item.get("price"), item.get("size")
        try:
            levels.append(Level(price=float(price), size=float(size)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    return levels


def analyze_book(book: Any) -> BookAnalysis:
    """Analyse un `OrderBookSummary` (ou tout objet exposant `bids`/`asks`).

    Les bids sont triés par prix décroissant et les asks par prix croissant :
    l'ordre renvoyé par l'API n'est pas garanti, donc on ne s'y fie pas.
    """
    bids = sorted(parse_levels(getattr(book, "bids", None)), key=lambda level: -level.price)
    asks = sorted(parse_levels(getattr(book, "asks", None)), key=lambda level: level.price)

    return BookAnalysis(
        best_bid=bids[0].price if bids else None,
        best_ask=asks[0].price if asks else None,
        bid_depth=sum(level.size for level in bids),
        ask_depth=sum(level.size for level in asks),
        bid_notional=sum(level.notional for level in bids),
        ask_notional=sum(level.notional for level in asks),
        levels_bid=len(bids),
        levels_ask=len(asks),
    )


def slippage(levels: Sequence[Level], target_size: float) -> tuple[float, float] | None:
    """Prix moyen d'exécution pour `target_size` parts, et slippage en bps.

    Consomme le carnet niveau par niveau. Retourne `None` si la profondeur est
    insuffisante : mieux vaut refuser de répondre que retourner un prix qui
    suppose une liquidité inexistante.
    """
    if target_size <= 0:
        raise ValueError("target_size doit être > 0")
    if not levels:
        return None

    remaining = target_size
    cost = 0.0
    for level in levels:
        take = min(remaining, level.size)
        cost += take * level.price
        remaining -= take
        if remaining <= 0:
            break

    if remaining > 0:
        return None

    avg_price = cost / target_size
    touch = levels[0].price
    slip_bps = abs(avg_price - touch) / touch * 10_000 if touch > 0 else 0.0
    return avg_price, slip_bps


def implied_probability(price: float) -> float:
    """Convertit un prix en pourcentage de probabilité implicite."""
    if not 0 <= price <= 1:
        raise ValueError(f"price doit être dans [0, 1], reçu : {price}")
    return price * 100


def arbitrage_edge(yes_price: float, no_price: float) -> float:
    """Écart par rapport à 1 de la somme YES + NO.

    Sur un marché binaire cohérent, YES + NO vaut 1. Un résultat négatif
    signale un achat des deux côtés sous 1 (gain sans risque avant frais) ;
    positif, une survalorisation.
    """
    return (yes_price + no_price) - 1.0

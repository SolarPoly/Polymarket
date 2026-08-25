"""Tests de l'analyse de carnet d'ordres.

Fonctions pures : aucun réseau, donc ces tests passent même quand les
endpoints Polymarket sont filtrés.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.analytics import (
    Level,
    analyze_book,
    arbitrage_edge,
    implied_probability,
    parse_levels,
    slippage,
)


@dataclass
class FakeLevel:
    """Reproduit un `OrderSummary` du SDK : prix et taille en chaînes."""

    price: str
    size: str


@dataclass
class FakeBook:
    bids: list[FakeLevel]
    asks: list[FakeLevel]


def book(bids: list[tuple[str, str]], asks: list[tuple[str, str]]) -> FakeBook:
    return FakeBook(
        bids=[FakeLevel(p, s) for p, s in bids],
        asks=[FakeLevel(p, s) for p, s in asks],
    )


class TestParseLevels:
    def test_convertit_les_chaines(self):
        levels = parse_levels([FakeLevel("0.42", "100")])
        assert levels == [Level(price=0.42, size=100.0)]

    def test_accepte_les_dicts(self):
        assert parse_levels([{"price": "0.5", "size": "10"}]) == [Level(0.5, 10.0)]

    def test_ignore_les_niveaux_illisibles(self):
        levels = parse_levels(
            [FakeLevel("0.42", "100"), FakeLevel("abc", "5"), FakeLevel("0.1", None)]
        )
        assert len(levels) == 1

    @pytest.mark.parametrize("raw", [None, [], "bruit"])
    def test_entrees_degradees(self, raw):
        assert parse_levels(raw) == []

    def test_notional(self):
        assert Level(price=0.25, size=400).notional == 100.0


class TestAnalyzeBook:
    def test_carnet_nominal(self):
        analysis = analyze_book(book([("0.40", "100"), ("0.39", "50")], [("0.44", "80")]))
        assert analysis.best_bid == 0.40
        assert analysis.best_ask == 0.44
        assert analysis.bid_depth == 150.0
        assert analysis.ask_depth == 80.0
        assert analysis.levels_bid == 2
        assert analysis.spread == pytest.approx(0.04)
        assert analysis.midpoint == pytest.approx(0.42)

    def test_trie_independamment_de_lordre_api(self):
        """L'API ne garantit pas l'ordre des niveaux : on ne s'y fie pas."""
        desordre = analyze_book(
            book([("0.39", "50"), ("0.40", "100")], [("0.50", "5"), ("0.44", "80")])
        )
        assert desordre.best_bid == 0.40
        assert desordre.best_ask == 0.44

    def test_spread_bps_est_comparable_entre_marches(self):
        """1 centime d'écart coûte bien plus cher sur un marché à 0,05."""
        cher = analyze_book(book([("0.04", "10")], [("0.05", "10")]))
        bon_marche = analyze_book(book([("0.49", "10")], [("0.50", "10")]))
        assert cher.spread == pytest.approx(bon_marche.spread)
        assert cher.spread_bps > bon_marche.spread_bps * 5

    def test_carnet_vide(self):
        analysis = analyze_book(book([], []))
        assert analysis.best_bid is None
        assert analysis.spread is None
        assert analysis.midpoint is None
        assert analysis.spread_bps is None
        assert analysis.imbalance is None
        assert analysis.is_crossed is False
        assert analysis.is_liquid is False

    def test_un_seul_cote(self):
        analysis = analyze_book(book([("0.40", "100")], []))
        assert analysis.best_bid == 0.40
        assert analysis.best_ask is None
        assert analysis.spread is None
        assert analysis.imbalance == 1.0

    def test_carnet_croise_est_signale(self):
        analysis = analyze_book(book([("0.60", "10")], [("0.55", "10")]))
        assert analysis.is_crossed is True
        assert analysis.is_liquid is False

    @pytest.mark.parametrize(
        ("bids", "asks", "attendu"),
        [
            ([("0.4", "100")], [("0.5", "100")], 0.0),
            ([("0.4", "100")], [("0.5", "0")], 1.0),
            ([("0.4", "0")], [("0.5", "100")], -1.0),
            ([("0.4", "75")], [("0.5", "25")], 0.5),
        ],
    )
    def test_imbalance(self, bids, asks, attendu):
        assert analyze_book(book(bids, asks)).imbalance == pytest.approx(attendu)

    def test_notional_pondere_par_le_prix(self):
        analysis = analyze_book(book([("0.25", "400")], [("0.75", "100")]))
        assert analysis.bid_notional == pytest.approx(100.0)
        assert analysis.ask_notional == pytest.approx(75.0)

    def test_objet_sans_attributs(self):
        analysis = analyze_book(object())
        assert analysis.best_bid is None
        assert analysis.levels_bid == 0


class TestSlippage:
    def test_consomme_un_seul_niveau(self):
        result = slippage([Level(0.40, 100)], 50)
        assert result is not None
        avg, bps = result
        assert avg == pytest.approx(0.40)
        assert bps == pytest.approx(0.0)

    def test_traverse_plusieurs_niveaux(self):
        levels = [Level(0.40, 50), Level(0.42, 50)]
        result = slippage(levels, 100)
        assert result is not None
        avg, bps = result
        assert avg == pytest.approx(0.41)
        assert bps == pytest.approx(250.0, rel=1e-3)

    def test_profondeur_insuffisante_retourne_none(self):
        """Refuser de répondre plutôt que supposer une liquidité inexistante."""
        assert slippage([Level(0.40, 10)], 1000) is None

    def test_carnet_vide(self):
        assert slippage([], 10) is None

    @pytest.mark.parametrize("size", [0, -5])
    def test_taille_invalide(self, size):
        with pytest.raises(ValueError, match="target_size doit être > 0"):
            slippage([Level(0.4, 10)], size)


class TestHelpers:
    @pytest.mark.parametrize(("price", "attendu"), [(0.42, 42.0), (0.0, 0.0), (1.0, 100.0)])
    def test_implied_probability(self, price, attendu):
        assert implied_probability(price) == pytest.approx(attendu)

    @pytest.mark.parametrize("price", [-0.1, 1.1, 2])
    def test_implied_probability_hors_bornes(self, price):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            implied_probability(price)

    @pytest.mark.parametrize(
        ("yes", "no", "attendu"),
        [
            (0.50, 0.50, 0.0),  # marché coherent
            (0.48, 0.48, -0.04),  # arbitrage : acheter les deux cotes sous 1
            (0.55, 0.55, 0.10),  # survalorisation
        ],
    )
    def test_arbitrage_edge(self, yes, no, attendu):
        assert arbitrage_edge(yes, no) == pytest.approx(attendu)

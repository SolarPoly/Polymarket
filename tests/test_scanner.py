"""Tests du scanner d'arbitrage.

Le point critique : un écart doit être calculé **au volume demandé**, en
traversant réellement les carnets. Un scanner qui compare les meilleurs prix
annonce des gains qui n'existent pas dès qu'on veut exécuter du volume.
Plusieurs tests ci-dessous vérifient précisément qu'un écart visible au touch
disparaît quand la profondeur ne suit pas.
"""

from __future__ import annotations

import pytest

from src.scanner import (
    BUY,
    SELL,
    MarketScan,
    find_arbitrage,
    rank_by_opportunity,
    scan_markets,
)


class Lvl:
    def __init__(self, price: str, size: str) -> None:
        self.price = price
        self.size = size


class Book:
    def __init__(self, bids: list[tuple[str, str]], asks: list[tuple[str, str]]) -> None:
        self.bids = [Lvl(p, s) for p, s in bids]
        self.asks = [Lvl(p, s) for p, s in asks]


def tokens_of(market: dict) -> dict[str, str | None]:
    return {"YES": market.get("yes"), "NO": market.get("no")}


class TestArbitrageAchat:
    """ask_YES + ask_NO < 1 : acheter les deux cotes coute moins que 1 USDC."""

    def test_ecart_detecte(self):
        yes = Book(bids=[("0.44", "500")], asks=[("0.45", "500")])
        no = Book(bids=[("0.49", "500")], asks=[("0.50", "500")])
        # 0.45 + 0.50 = 0.95 -> 0.05 de gain par ensemble
        opportunities = find_arbitrage(yes, no, size=100)
        assert len(opportunities) == 1
        opp = opportunities[0]
        assert opp.kind == BUY
        assert opp.profit_per_set == pytest.approx(0.05)
        assert opp.total_profit == pytest.approx(5.0)
        assert opp.edge_bps == pytest.approx(500.0)

    def test_marche_coherent_ne_donne_rien(self):
        yes = Book(bids=[("0.49", "500")], asks=[("0.51", "500")])
        no = Book(bids=[("0.49", "500")], asks=[("0.51", "500")])
        # 0.51 + 0.51 = 1.02 : acheter les deux coute plus que le payout
        assert find_arbitrage(yes, no, size=100) == ()

    def test_prix_moyen_et_non_prix_affiche(self):
        """Le prix retenu doit etre le prix moyen d'execution."""
        yes = Book(bids=[], asks=[("0.40", "50"), ("0.44", "50")])
        no = Book(bids=[], asks=[("0.50", "100")])
        opp = find_arbitrage(yes, no, size=100)[0]
        assert opp.yes_price == pytest.approx(0.42)  # moyenne de 0.40 et 0.44
        assert opp.no_price == pytest.approx(0.50)
        assert opp.profit_per_set == pytest.approx(0.08)


class TestArbitrageVente:
    """bid_YES + bid_NO > 1 : vendre les deux rapporte plus que la creation."""

    def test_ecart_detecte(self):
        yes = Book(bids=[("0.55", "500")], asks=[("0.56", "500")])
        no = Book(bids=[("0.52", "500")], asks=[("0.53", "500")])
        # 0.55 + 0.52 = 1.07 -> 0.07 de gain par ensemble
        opportunities = find_arbitrage(yes, no, size=100)
        assert len(opportunities) == 1
        assert opportunities[0].kind == SELL
        assert opportunities[0].profit_per_set == pytest.approx(0.07)

    def test_consomme_les_bids_du_plus_haut_au_plus_bas(self):
        """Vendre commence par le meilleur bid, pas par le premier de la liste."""
        yes = Book(bids=[("0.50", "50"), ("0.60", "50")], asks=[])
        no = Book(bids=[("0.55", "100")], asks=[])
        opp = find_arbitrage(yes, no, size=100)[0]
        assert opp.yes_price == pytest.approx(0.55)  # moyenne de 0.60 et 0.50
        assert opp.profit_per_set == pytest.approx(0.10)


class TestProfondeurInsuffisante:
    """Le coeur du sujet : un ecart au touch qui ne tient pas au volume."""

    def test_ecart_au_touch_mais_profondeur_absente(self):
        # 0.45 + 0.50 = 0.95 au touch, mais seulement 10 parts disponibles
        yes = Book(bids=[], asks=[("0.45", "10")])
        no = Book(bids=[], asks=[("0.50", "10")])
        assert find_arbitrage(yes, no, size=1000) == ()

    def test_ecart_tient_au_petit_volume(self):
        yes = Book(bids=[], asks=[("0.45", "10")])
        no = Book(bids=[], asks=[("0.50", "10")])
        assert len(find_arbitrage(yes, no, size=10)) == 1

    def test_ecart_disparait_en_traversant_le_carnet(self):
        """Le touch donne 0.95, mais les niveaux suivants font passer au-dessus de 1."""
        yes = Book(bids=[], asks=[("0.45", "10"), ("0.70", "990")])
        no = Book(bids=[], asks=[("0.50", "10"), ("0.60", "990")])
        assert find_arbitrage(yes, no, size=10) != ()  # tient sur 10
        assert find_arbitrage(yes, no, size=1000) == ()  # disparait sur 1000

    def test_un_seul_cote_liquide_ne_suffit_pas(self):
        yes = Book(bids=[], asks=[("0.45", "1000")])
        no = Book(bids=[], asks=[])
        assert find_arbitrage(yes, no, size=100) == ()

    def test_carnets_vides(self):
        assert find_arbitrage(Book([], []), Book([], []), size=100) == ()

    @pytest.mark.parametrize("size", [0, -10])
    def test_size_invalide(self, size):
        with pytest.raises(ValueError, match="size doit être > 0"):
            find_arbitrage(Book([], []), Book([], []), size=size)


class TestScanMarkets:
    MARKETS = [
        {"question": "M1", "event_title": "E", "yes": "y1", "no": "n1"},
        {"question": "M2", "event_title": "E", "yes": "y2", "no": "n2"},
    ]

    BOOKS = {
        "y1": Book(bids=[("0.44", "500")], asks=[("0.45", "500")]),
        "n1": Book(bids=[("0.49", "500")], asks=[("0.50", "500")]),
        "y2": Book(bids=[("0.49", "500")], asks=[("0.51", "500")]),
        "n2": Book(bids=[("0.49", "500")], asks=[("0.51", "500")]),
    }

    def fetch(self, token: str) -> Book:
        return self.BOOKS[token]

    def test_analyse_chaque_marche(self):
        scans = scan_markets(self.fetch, self.MARKETS, tokens_of, size=100)
        assert len(scans) == 2
        assert scans[0].question == "M1"
        assert scans[0].yes is not None
        assert len(scans[0].opportunities) == 1
        assert scans[1].opportunities == ()

    def test_liste_vide(self):
        assert scan_markets(self.fetch, [], tokens_of) == []

    def test_marche_sans_paire_complete(self):
        markets = [{"question": "orphelin", "yes": "y1", "no": None}]
        scans = scan_markets(self.fetch, markets, tokens_of)
        assert scans[0].error is not None
        assert "paire" in scans[0].error

    def test_une_panne_ninterrompt_pas_le_balayage(self):
        """Un carnet illisible ne doit pas faire perdre les autres resultats."""

        def flaky(token: str) -> Book:
            if token == "y2":
                raise RuntimeError("carnet indisponible")
            return self.BOOKS[token]

        scans = scan_markets(flaky, self.MARKETS, tokens_of, size=100)
        assert len(scans) == 2
        assert scans[0].error is None
        assert scans[1].error is not None
        assert "indisponible" in scans[1].error

    def test_ordre_preserve(self):
        """`scan_markets` ne trie pas : c'est le role de `rank_by_opportunity`."""
        scans = scan_markets(self.fetch, self.MARKETS, tokens_of)
        assert [s.question for s in scans] == ["M1", "M2"]


class TestProprietesDuScan:
    def test_touch_sum_et_edge(self):
        scans = scan_markets(
            TestScanMarkets().fetch, TestScanMarkets.MARKETS[:1], tokens_of, size=100
        )
        scan = scans[0]
        # midpoints : YES 0.445, NO 0.495 -> somme 0.94
        assert scan.touch_sum == pytest.approx(0.94)
        assert scan.touch_edge == pytest.approx(-0.06)

    def test_touch_sum_none_si_carnet_incomplet(self):
        scan = MarketScan(question="q", event=None, yes_token="y", no_token="n", yes=None, no=None)
        assert scan.touch_sum is None
        assert scan.touch_edge is None
        assert scan.total_depth == 0.0
        assert scan.best_opportunity is None
        assert scan.tradable is False

    def test_best_opportunity_choisit_le_meilleur_ecart(self):
        # Carnets ou achat ET vente sont possibles simultanement.
        yes = Book(bids=[("0.60", "500")], asks=[("0.45", "500")])
        no = Book(bids=[("0.55", "500")], asks=[("0.50", "500")])
        opportunities = find_arbitrage(yes, no, size=100)
        assert len(opportunities) == 2
        scan = MarketScan(
            question="q",
            event=None,
            yes_token="y",
            no_token="n",
            yes=None,
            no=None,
            opportunities=opportunities,
        )
        best = scan.best_opportunity
        assert best is not None
        # vente : 0.60+0.55-1 = 0.15 ; achat : 1-(0.45+0.50) = 0.05
        assert best.kind == SELL
        assert best.profit_per_set == pytest.approx(0.15)


class TestRanking:
    def make(self, error=None, profit=0.0, depth=0.0) -> MarketScan:
        from src.scanner import ArbitrageOpportunity

        opportunities = ()
        if profit:
            opportunities = (
                ArbitrageOpportunity(
                    kind=BUY, size=100, yes_price=0.4, no_price=0.5, profit_per_set=profit
                ),
            )

        class Analysis:
            bid_depth = depth / 2
            ask_depth = depth / 2
            is_liquid = True

        return MarketScan(
            question=f"p={profit} d={depth} e={error}",
            event=None,
            yes_token="y",
            no_token="n",
            yes=Analysis(),  # type: ignore[arg-type]
            no=Analysis(),  # type: ignore[arg-type]
            opportunities=opportunities,
            error=error,
        )

    def test_meilleur_ecart_en_premier(self):
        scans = [self.make(profit=0.01), self.make(profit=0.09), self.make(profit=0.05)]
        ranked = rank_by_opportunity(scans)
        profits = [s.best_opportunity.profit_per_set for s in ranked]  # type: ignore[union-attr]
        assert profits == [0.09, 0.05, 0.01]

    def test_liquidite_departage_a_ecart_egal(self):
        """`total_depth` cumule les deux carnets : on verifie l'ordre, pas les
        valeurs absolues du double de test."""
        scans = [self.make(depth=100), self.make(depth=9000), self.make(depth=500)]
        depths = [s.total_depth for s in rank_by_opportunity(scans)]
        assert depths == sorted(depths, reverse=True)
        assert depths[0] > depths[-1]

    def test_erreurs_en_dernier_pas_masquees(self):
        scans = [self.make(error="boum"), self.make(profit=0.01)]
        ranked = rank_by_opportunity(scans)
        assert ranked[0].error is None
        assert ranked[1].error == "boum"
        assert len(ranked) == 2  # rien n'est perdu

    def test_liste_vide(self):
        assert rank_by_opportunity([]) == []

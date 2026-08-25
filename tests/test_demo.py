"""Tests du mode démonstration.

Enjeu : le mode démo ne doit jamais pouvoir être confondu avec des données
réelles. La version initiale du projet servait des marchés factices en cas de
panne réseau, ce qui faisait passer une coupure pour un succès. Le mode démo
est l'inverse — opt-in strict et étiqueté — et ces tests le verrouillent :

* il ne s'active QUE sur la variable d'environnement, jamais sur une panne ;
* toute réponse porte `"demo": true` ;
* hors mode démo, toute réponse porte `"demo": false`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import api as api_module
from src.analytics import analyze_book
from src.demo import DEMO_MARKETS, DEMO_WALLET, demo_book, demo_markets
from src.market import GammaMarketScanner


@pytest.fixture
def demo_client(monkeypatch):
    """Client HTTP en mode démo, sans clé ni configuration valide."""
    monkeypatch.setenv("POLY_DEMO_MODE", "true")
    # Aucun moteur n'est fourni : la démo doit tourner sans wallet.
    monkeypatch.delenv("POLYGON_PRIVATE_KEY", raising=False)
    return TestClient(api_module.create_app())


class TestActivation:
    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
    def test_valeurs_activantes(self, monkeypatch, value):
        monkeypatch.setenv("POLY_DEMO_MODE", value)
        assert api_module._demo_enabled() is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "", "  ", "peut-etre"])
    def test_valeurs_non_activantes(self, monkeypatch, value):
        monkeypatch.setenv("POLY_DEMO_MODE", value)
        assert api_module._demo_enabled() is False

    def test_absent_donne_faux(self, monkeypatch):
        monkeypatch.delenv("POLY_DEMO_MODE", raising=False)
        assert api_module._demo_enabled() is False


class TestEtiquetage:
    """Chaque réponse doit dire si elle est réelle ou simulée."""

    def test_status_etiquete(self, demo_client):
        body = demo_client.get("/api/status").json()
        assert body["demo"] is True
        assert body["wallet"] == DEMO_WALLET

    def test_markets_etiquete(self, demo_client):
        body = demo_client.get("/api/markets?limit=3").json()
        assert body["demo"] is True
        assert body["count"] == 3

    def test_book_etiquete(self, demo_client):
        body = demo_client.get("/api/book/demo-fed-yes").json()
        assert body["demo"] is True

    def test_builder_etiquete(self, demo_client):
        body = demo_client.get("/api/builder").json()
        assert body["demo"] is True
        assert body["active"] is False


class TestFonctionneSansWallet:
    """La démo doit tourner sans clé privée : c'est son intérêt principal."""

    def test_status_sans_cle(self, demo_client):
        assert demo_client.get("/api/status").status_code == 200

    def test_book_sans_cle(self, demo_client):
        assert demo_client.get("/api/book/demo-btc-yes?size=1000").status_code == 200

    def test_aucune_adresse_reelle_exposee(self, demo_client):
        """Le wallet de démo est ostensiblement factice."""
        assert DEMO_WALLET.startswith("0xDEM0")


class TestJeuDeDonnees:
    """Le jeu de données doit couvrir chaque état affichable."""

    def test_token_inconnu_donne_carnet_vide(self):
        """En démo, un token au hasard montre l'état « vide », pas une erreur."""
        analysis = analyze_book(demo_book("token-inexistant"))
        assert analysis.best_bid is None
        assert analysis.levels_bid == 0

    def test_cas_liquide(self):
        analysis = analyze_book(demo_book("demo-fed-yes"))
        assert analysis.is_liquid is True
        assert analysis.spread is not None

    def test_cas_illiquide(self):
        """Spread large : `is_liquid` doit ressortir à faux."""
        analysis = analyze_book(demo_book("demo-thin-yes"))
        assert analysis.is_liquid is False

    def test_cas_desequilibre(self):
        analysis = analyze_book(demo_book("demo-btc-yes"))
        assert analysis.imbalance is not None
        assert analysis.imbalance > 0.5

    def test_cas_carnet_vide(self):
        analysis = analyze_book(demo_book("demo-empty-yes"))
        assert analysis.midpoint is None

    def test_aucun_carnet_croise(self):
        """Un carnet croisé dans le jeu de données serait une incohérence.

        Parcourt tous les tokens référencés par les marchés de démo, plutôt
        qu'une liste écrite à la main qui se désynchroniserait.
        """
        for market in DEMO_MARKETS:
            for token_id in GammaMarketScanner.get_market_tokens(market).values():
                if token_id is None:
                    continue
                assert analyze_book(demo_book(token_id)).is_crossed is False, token_id

    def test_limite_respectee(self):
        assert len(demo_markets(2)) == 2
        assert len(demo_markets(999)) == len(DEMO_MARKETS)


class TestHorsModeDemo:
    def test_reponses_reelles_etiquetees_false(self, monkeypatch):
        """Sans la variable, tout doit être marqué comme non simulé."""
        from tests.test_api import FakeEngine, FakeScanner, make_settings

        monkeypatch.delenv("POLY_DEMO_MODE", raising=False)
        monkeypatch.setattr(api_module, "get_engine", lambda: FakeEngine())
        monkeypatch.setattr(api_module, "get_settings", make_settings)
        monkeypatch.setattr(api_module, "GammaMarketScanner", FakeScanner([]))

        client = TestClient(api_module.create_app())
        assert client.get("/api/status").json()["demo"] is False
        assert client.get("/api/markets").json()["demo"] is False
        assert client.get("/api/builder").json()["demo"] is False

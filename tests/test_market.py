"""Tests du scanner Gamma.

Le test central est `test_aucun_fallback_mock_*` : la version initiale
renvoyait des marchés factices en cas de panne, ce qui faisait passer une
coupure réseau pour un succès.
"""

from __future__ import annotations

import pytest
import requests
import responses

from src.errors import MarketDataError
from src.market import GammaMarketScanner

HOST = "https://gamma-api.test"
URL = f"{HOST}/events"


@pytest.fixture
def scanner() -> GammaMarketScanner:
    return GammaMarketScanner(host=HOST, timeout=2)


class TestNoSilentFallback:
    """Toute panne doit lever, jamais retourner de données inventées."""

    @responses.activate
    def test_aucun_fallback_mock_sur_erreur_reseau(self, scanner):
        responses.add(responses.GET, URL, body=requests.exceptions.ConnectionError())
        with pytest.raises(MarketDataError, match="Connexion impossible"):
            scanner.get_active_markets()

    @responses.activate
    def test_aucun_fallback_mock_sur_500_repete(self, scanner):
        """500 persistant : les retries s'épuisent -> RetryError -> MarketDataError."""
        responses.add(responses.GET, URL, status=500)
        with pytest.raises(MarketDataError, match="retries épuisés"):
            scanner.get_active_markets()

    @responses.activate
    def test_aucun_fallback_mock_sur_404(self, scanner):
        """404 n'est pas retryable : remonte en HTTPError -> MarketDataError."""
        responses.add(responses.GET, URL, status=404)
        with pytest.raises(MarketDataError, match="HTTP 404"):
            scanner.get_active_markets()

    @responses.activate
    def test_recuperation_apres_500_transitoire(self, scanner, gamma_payload):
        """Un 500 isolé doit être absorbé par le retry, pas propagé."""
        responses.add(responses.GET, URL, status=500)
        responses.add(responses.GET, URL, json=gamma_payload, status=200)
        assert len(scanner.get_active_markets(limit=10)) == 3

    @responses.activate
    def test_aucun_fallback_mock_sur_json_invalide(self, scanner):
        responses.add(responses.GET, URL, body="<html>blocked</html>", status=200)
        with pytest.raises(MarketDataError, match="non-JSON"):
            scanner.get_active_markets()

    @responses.activate
    def test_aucun_fallback_mock_sur_format_inattendu(self, scanner):
        responses.add(responses.GET, URL, json={"error": "nope"}, status=200)
        with pytest.raises(MarketDataError, match="Format inattendu"):
            scanner.get_active_markets()

    @responses.activate
    def test_erreur_tls_est_explicite(self, scanner):
        responses.add(responses.GET, URL, body=requests.exceptions.SSLError())
        with pytest.raises(MarketDataError, match="TLS"):
            scanner.get_active_markets()

    @responses.activate
    def test_timeout_est_explicite(self, scanner):
        responses.add(responses.GET, URL, body=requests.exceptions.Timeout())
        with pytest.raises(MarketDataError, match="Délai"):
            scanner.get_active_markets()


class TestParsing:
    @responses.activate
    def test_aplatit_les_evenements(self, scanner, gamma_payload):
        responses.add(responses.GET, URL, json=gamma_payload, status=200)
        markets = scanner.get_active_markets(limit=10)
        assert len(markets) == 3
        assert markets[0]["event_title"] == "Fed decisions"
        assert markets[2]["event_title"] == "Crypto"

    @responses.activate
    def test_respecte_la_limite(self, scanner, gamma_payload):
        responses.add(responses.GET, URL, json=gamma_payload, status=200)
        assert len(scanner.get_active_markets(limit=2)) == 2

    @responses.activate
    def test_liste_vide(self, scanner):
        responses.add(responses.GET, URL, json=[], status=200)
        assert scanner.get_active_markets() == []

    @responses.activate
    def test_ignore_les_entrees_non_dict(self, scanner):
        payload = [None, "bruit", 42, {"title": "ok", "markets": [{"question": "Q?"}]}]
        responses.add(responses.GET, URL, json=payload, status=200)
        markets = scanner.get_active_markets()
        assert len(markets) == 1
        assert markets[0]["question"] == "Q?"

    @responses.activate
    def test_params_passes_en_query(self, scanner):
        responses.add(responses.GET, URL, json=[], status=200)
        scanner.get_active_markets(limit=7)
        query = responses.calls[0].request.url
        assert "limit=7" in query
        assert "closed=false" in query

    def test_limite_invalide(self, scanner):
        with pytest.raises(ValueError, match="limit doit être >= 1"):
            scanner.get_active_markets(limit=0)


class TestTokenExtraction:
    def test_chaine_json(self):
        tokens = GammaMarketScanner.get_market_tokens({"clobTokenIds": '["a", "b"]'})
        assert tokens == {"YES": "a", "NO": "b"}

    def test_liste_native(self):
        tokens = GammaMarketScanner.get_market_tokens({"clobTokenIds": ["a", "b"]})
        assert tokens == {"YES": "a", "NO": "b"}

    @pytest.mark.parametrize(
        "raw",
        ["json-casse", None, [], {}, 42, '["seul"]'],
    )
    def test_entrees_degradees_ne_levent_pas(self, raw):
        tokens = GammaMarketScanner.get_market_tokens({"clobTokenIds": raw})
        assert set(tokens) == {"YES", "NO"}

    def test_un_seul_token(self):
        tokens = GammaMarketScanner.get_market_tokens({"clobTokenIds": ["a"]})
        assert tokens == {"YES": "a", "NO": None}

    def test_champ_absent(self):
        assert GammaMarketScanner.get_market_tokens({}) == {"YES": None, "NO": None}


class TestVolume:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("1254300.5", 1254300.5),
            (1000, 1000.0),
            (None, 0.0),
            ("", 0.0),
            ("not-a-number", 0.0),
            ([], 0.0),
        ],
    )
    def test_conversion_robuste(self, raw, expected):
        assert GammaMarketScanner.volume_24h({"volume24hr": raw}) == expected

    def test_champ_absent(self):
        assert GammaMarketScanner.volume_24h({}) == 0.0

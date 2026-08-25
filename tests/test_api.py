"""Tests de l'API HTTP.

Le moteur et le scanner sont remplacés par des doubles : ces tests ne
touchent jamais le réseau et passent donc même quand Polymarket est filtré.

Le test central est `test_gamma_indisponible_renvoie_503` : l'API doit
propager la panne, jamais servir de données de substitution. C'est le pendant
côté HTTP du fallback mock supprimé dans `market.py`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import api as api_module
from src.config import ApiCredentials, BuilderConfiguration, Secret, Settings
from src.errors import ClobError, MarketDataError
from src.market import GammaMarketScanner

TEST_KEY = "01" * 32


class FakeLevel:
    def __init__(self, price: str, size: str) -> None:
        self.price = price
        self.size = size


class FakeBook:
    def __init__(self, bids: list[FakeLevel], asks: list[FakeLevel]) -> None:
        self.bids = bids
        self.asks = asks


class FakeEngine:
    """Double du moteur : aucun appel réseau, comportement pilotable."""

    def __init__(
        self,
        *,
        reachable: bool = True,
        builder: bool = False,
        book: FakeBook | None = None,
        book_error: str | None = None,
        trades: object = None,
        trades_error: str | None = None,
    ) -> None:
        self.address = "0xAbCd000000000000000000000000000000000001"
        self._reachable = reachable
        self._builder = builder
        self._book = book
        self._book_error = book_error
        self._trades = trades
        self._trades_error = trades_error

    def health_check(self) -> bool:
        return self._reachable

    @property
    def builder_enabled(self) -> bool:
        return self._builder

    def get_order_book(self, token_id: str) -> FakeBook:
        if self._book_error:
            raise ClobError(self._book_error)
        assert self._book is not None
        return self._book

    def get_builder_trades(self) -> object:
        if self._trades_error:
            raise ClobError(self._trades_error)
        return self._trades


class FakeScanner:
    """Double du scanner Gamma, utilisable comme context manager."""

    def __init__(self, markets: list[dict] | None = None, error: str | None = None) -> None:
        self._markets = markets or []
        self._error = error

    def __call__(self, *_args: object, **_kwargs: object) -> FakeScanner:
        return self

    def __enter__(self) -> FakeScanner:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def get_active_markets(self, limit: int = 5) -> list[dict]:
        if self._error:
            raise MarketDataError(self._error)
        return self._markets[:limit]

    # Le double reutilise les vrais helpers : leur logique de parsing est
    # deja couverte par test_market.py, on ne la reimplemente pas ici.
    volume_24h = staticmethod(GammaMarketScanner.volume_24h)
    get_market_tokens = staticmethod(GammaMarketScanner.get_market_tokens)


def make_settings(**kwargs: object) -> Settings:
    base: dict[str, object] = {"private_key": Secret(TEST_KEY)}
    base.update(kwargs)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def client(monkeypatch):
    """Fabrique un client HTTP dont on choisit le moteur et le scanner."""

    def _build(
        engine: FakeEngine | None = None,
        settings: Settings | None = None,
        scanner: FakeScanner | None = None,
    ) -> TestClient:
        monkeypatch.setattr(api_module, "get_engine", lambda: engine or FakeEngine())
        monkeypatch.setattr(api_module, "get_settings", lambda: settings or make_settings())
        if scanner is not None:
            monkeypatch.setattr(api_module, "GammaMarketScanner", scanner)
        return TestClient(api_module.create_app())

    return _build


class TestStatus:
    def test_expose_letat_du_moteur(self, client):
        response = client(FakeEngine(reachable=True)).get("/api/status")
        assert response.status_code == 200
        body = response.json()
        assert body["clob_reachable"] is True
        assert body["trading_enabled"] is False
        assert body["wallet"].startswith("0x")

    def test_signale_le_clob_injoignable(self, client):
        body = client(FakeEngine(reachable=False)).get("/api/status").json()
        assert body["clob_reachable"] is False

    def test_ne_fuit_aucun_secret(self, client):
        """Aucune route ne doit exposer clé, secret ni passphrase."""
        settings = make_settings(
            api_creds=ApiCredentials(
                key="pub-key", secret=Secret("secret-sensible"), passphrase=Secret("pass-sensible")
            ),
            builder=BuilderConfiguration(
                creds=ApiCredentials(
                    key="b-key",
                    secret=Secret("builder-secret"),
                    passphrase=Secret("builder-pass"),
                )
            ),
        )
        raw = client(settings=settings).get("/api/status").text
        for leak in (
            TEST_KEY,
            "secret-sensible",
            "pass-sensible",
            "builder-secret",
            "builder-pass",
        ):
            assert leak not in raw
        # Le booléen de configuration, lui, doit bien être publié.
        assert '"api_creds_configured":true' in raw.replace(" ", "")


class TestMarkets:
    MARKETS = [
        {
            "question": "Fed cuts rates?",
            "event_title": "Fed",
            "volume24hr": "1000",
            "clobTokenIds": '["111", "222"]',
        },
        {"question": "BTC 100k?", "volume24hr": None, "clobTokenIds": ["333", "444"]},
    ]

    def test_liste_les_marches(self, client):
        response = client(scanner=FakeScanner(self.MARKETS)).get("/api/markets?limit=5")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert body["markets"][0]["tokens"]["YES"] == "111"
        assert body["markets"][1]["volume_24h"] == 0.0

    def test_respecte_la_limite(self, client):
        body = client(scanner=FakeScanner(self.MARKETS)).get("/api/markets?limit=1").json()
        assert body["count"] == 1

    def test_gamma_indisponible_renvoie_503(self, client):
        """La panne remonte telle quelle : jamais de données de substitution."""
        response = client(scanner=FakeScanner(error="Échec TLS vers gamma")).get("/api/markets")
        assert response.status_code == 503
        assert "TLS" in response.json()["detail"]

    def test_liste_vide_reste_vide(self, client):
        body = client(scanner=FakeScanner([])).get("/api/markets").json()
        assert body == {"demo": False, "count": 0, "markets": []}

    @pytest.mark.parametrize("limit", [0, -1, 101, 9999])
    def test_limites_hors_bornes_rejetees(self, client, limit):
        response = client(scanner=FakeScanner([])).get(f"/api/markets?limit={limit}")
        assert response.status_code == 422


class TestBook:
    BOOK = FakeBook(
        bids=[FakeLevel("0.40", "100"), FakeLevel("0.39", "50")],
        asks=[FakeLevel("0.44", "80")],
    )

    def test_analyse_le_carnet(self, client):
        response = client(FakeEngine(book=self.BOOK)).get("/api/book/tok-1")
        assert response.status_code == 200
        body = response.json()
        assert body["best_bid"] == 0.40
        assert body["best_ask"] == 0.44
        assert body["midpoint"] == pytest.approx(0.42)
        assert body["levels_bid"] == 2
        assert "simulation" not in body

    def test_simulation_dachat(self, client):
        body = client(FakeEngine(book=self.BOOK)).get("/api/book/tok-1?size=50").json()
        assert body["simulation"]["avg_price"] == pytest.approx(0.44)

    def test_profondeur_insuffisante_est_dite(self, client):
        body = client(FakeEngine(book=self.BOOK)).get("/api/book/tok-1?size=100000").json()
        assert body["simulation"]["error"] == "profondeur insuffisante"

    def test_carnet_indisponible_renvoie_503(self, client):
        response = client(FakeEngine(book_error="CLOB injoignable")).get("/api/book/tok-1")
        assert response.status_code == 503
        assert "injoignable" in response.json()["detail"]

    def test_taille_negative_rejetee(self, client):
        response = client(FakeEngine(book=self.BOOK)).get("/api/book/tok-1?size=-5")
        assert response.status_code == 422


class TestBuilder:
    def test_inactif_par_defaut(self, client):
        body = client(FakeEngine(builder=False)).get("/api/builder").json()
        assert body["active"] is False
        assert body["configured"] is False

    def test_inactif_avec_trades_explique_pourquoi(self, client):
        body = client(FakeEngine(builder=False)).get("/api/builder?trades=true").json()
        assert "candidature" in body["trades_error"]
        assert "trades" not in body

    def test_actif_retourne_les_trades(self, client):
        engine = FakeEngine(builder=True, trades=[{"id": "t1"}])
        body = client(engine).get("/api/builder?trades=true").json()
        assert body["active"] is True
        assert body["trades"] == [{"id": "t1"}]

    def test_erreur_de_trades_est_rapportee(self, client):
        engine = FakeEngine(builder=True, trades_error="403 interdit")
        body = client(engine).get("/api/builder?trades=true").json()
        assert "403" in body["trades_error"]


class TestFront:
    def test_page_servie(self, client):
        response = client().get("/")
        assert response.status_code == 200
        assert "PolyTrade" in response.text

    def test_actifs_statiques_servis(self, client):
        instance = client()
        assert instance.get("/static/app.js").status_code == 200
        assert instance.get("/static/styles.css").status_code == 200

    def test_aucune_route_decriture(self, client):
        """L'API est en lecture seule : aucun POST/PUT/DELETE ne doit exister."""
        routes = api_module.create_app().routes
        for route in routes:
            methods = getattr(route, "methods", set()) or set()
            assert not ({"POST", "PUT", "PATCH", "DELETE"} & methods), (
                f"route en écriture inattendue : {getattr(route, 'path', route)}"
            )

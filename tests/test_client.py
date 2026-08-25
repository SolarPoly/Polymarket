"""Tests des méthodes de lecture du moteur.

Ces méthodes sont de fines enveloppes autour du SDK, mais l'enveloppe est
justement ce qui doit être testé : elle garantit qu'une défaillance du SDK
ressort en `ClobError` (et non en exception brute du SDK remontant jusqu'à
l'appelant), et que les arguments vides sont rejetés avant l'appel réseau.

Ces cinq méthodes n'avaient aucune couverture avant ce fichier.
"""

from __future__ import annotations

import pytest

from src.client import PolymarketEngine
from src.config import Secret, Settings
from src.errors import ClobError

TEST_KEY = "01" * 32


class BoomClient:
    """Client SDK dont chaque appel échoue, comme le ferait un réseau coupé."""

    def __init__(self, message: str = "reseau injoignable") -> None:
        self.message = message

    def __getattr__(self, name: str):
        def _raise(*_args: object, **_kwargs: object):
            raise RuntimeError(self.message)

        return _raise


class StubClient:
    """Client SDK qui répond, pour vérifier le passage des arguments."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def _record(self, name: str):
        def _call(*args: object, **kwargs: object):
            self.calls.append((name, args, kwargs))
            return {"ok": name}

        return _call

    def __getattr__(self, name: str):
        return self._record(name)


@pytest.fixture
def engine() -> PolymarketEngine:
    return PolymarketEngine(Settings(private_key=Secret(TEST_KEY)))


class TestArgumentsVides:
    """Un token_id vide doit être rejeté avant tout appel réseau."""

    @pytest.mark.parametrize("method", ["get_order_book", "get_midpoint", "get_spread"])
    def test_token_id_vide_rejete(self, engine, method):
        with pytest.raises(ValueError, match="token_id est requis"):
            getattr(engine, method)("")


class TestEnveloppeDErreur:
    """Toute défaillance du SDK doit ressortir en ClobError."""

    @pytest.mark.parametrize(
        ("method", "args"),
        [
            ("get_sampling_markets", ()),
            ("get_order_book", ("tok-1",)),
            ("get_midpoint", ("tok-1",)),
            ("get_spread", ("tok-1",)),
            ("ensure_api_creds", ()),
        ],
    )
    def test_echec_sdk_devient_cloberror(self, engine, method, args):
        engine.client = BoomClient("boum")
        with pytest.raises(ClobError) as excinfo:
            getattr(engine, method)(*args)
        # Le message d'origine doit rester visible pour le diagnostic.
        assert "boum" in str(excinfo.value)

    def test_analyze_token_propage_cloberror(self, engine):
        engine.client = BoomClient()
        with pytest.raises(ClobError):
            engine.analyze_token("tok-1")


class TestPassageDesArguments:
    def test_get_order_book(self, engine):
        stub = StubClient()
        engine.client = stub
        engine.get_order_book("tok-42")
        assert stub.calls == [("get_order_book", ("tok-42",), {})]

    def test_get_midpoint(self, engine):
        stub = StubClient()
        engine.client = stub
        engine.get_midpoint("tok-42")
        assert stub.calls[0][1] == ("tok-42",)

    def test_get_spread(self, engine):
        stub = StubClient()
        engine.client = stub
        engine.get_spread("tok-42")
        assert stub.calls[0][1] == ("tok-42",)


class TestHealthCheck:
    def test_vrai_quand_le_clob_repond(self, engine):
        engine.client = StubClient()
        assert engine.health_check() is True

    def test_faux_quand_le_clob_echoue(self, engine):
        """Un health check ne doit jamais lever : il répond oui ou non."""
        engine.client = BoomClient()
        assert engine.health_check() is False


class TestAnalyzeToken:
    def test_retourne_une_analyse(self, engine):
        class Level:
            def __init__(self, price: str, size: str) -> None:
                self.price = price
                self.size = size

        class Book:
            bids = [Level("0.40", "100")]
            asks = [Level("0.44", "80")]

        class BookClient:
            def get_order_book(self, token_id: str) -> Book:
                return Book()

        engine.client = BookClient()
        analysis = engine.analyze_token("tok-1")
        assert analysis.best_bid == 0.40
        assert analysis.midpoint == pytest.approx(0.42)


class TestBuilderDesactive:
    def test_builder_enabled_faux_sans_creds(self, engine):
        assert engine.builder_enabled is False

    def test_builder_enabled_ne_leve_jamais(self, engine):
        """Même si le SDK explose, la propriété répond un booléen."""
        engine.client = BoomClient()
        assert engine.builder_enabled is False

    def test_get_builder_trades_refuse_sans_creds(self, engine):
        with pytest.raises(ClobError, match="BUILDER_API_KEY"):
            engine.get_builder_trades()


class TestPlaceLimitOrder:
    """Le chemin nominal de l'envoi d'ordre : c'est le code qui engage des
    fonds, donc celui qui mérite le plus d'être verrouillé."""

    class OrderClient:
        def __init__(self) -> None:
            self.created: object = None
            self.posted: tuple[object, object] | None = None

        def create_order(self, order_args):
            self.created = order_args
            return {"signed": True, "args": order_args}

        def post_order(self, signed, order_type):
            self.posted = (signed, order_type)
            return {"orderID": "abc-123"}

    @pytest.fixture
    def trading_engine(self) -> PolymarketEngine:
        return PolymarketEngine(Settings(private_key=Secret(TEST_KEY), enable_trading=True))

    def test_envoie_et_retourne_la_reponse(self, trading_engine):
        client = self.OrderClient()
        trading_engine.client = client
        result = trading_engine.place_limit_order("tok-1", price=0.42, size=10, side="BUY")
        assert result == {"orderID": "abc-123"}
        assert client.posted is not None

    def test_transmet_les_bons_parametres(self, trading_engine):
        client = self.OrderClient()
        trading_engine.client = client
        trading_engine.place_limit_order("tok-9", price=0.33, size=7, side="SELL")
        order = client.created
        assert order.token_id == "tok-9"
        assert order.price == 0.33
        assert order.size == 7

    @pytest.mark.parametrize("side", ["buy", "BUY", " buy ", "Buy"])
    def test_side_normalise(self, trading_engine, side):
        """La casse et les espaces ne doivent pas changer le sens de l'ordre."""
        client = self.OrderClient()
        trading_engine.client = client
        trading_engine.place_limit_order("tok-1", price=0.5, size=1, side=side)
        assert client.created is not None

    def test_echec_denvoi_devient_cloberror(self, trading_engine):
        trading_engine.client = BoomClient("rejet du carnet")
        with pytest.raises(ClobError, match="rejet du carnet"):
            trading_engine.place_limit_order("tok-1", price=0.5, size=1)

    def test_validation_precede_lenvoi(self, trading_engine):
        """Un ordre invalide ne doit jamais atteindre le client SDK."""
        client = self.OrderClient()
        trading_engine.client = client
        with pytest.raises(ValueError):
            trading_engine.place_limit_order("tok-1", price=1.5, size=10)
        assert client.created is None


class TestBuilderTrades:
    def test_retourne_les_trades_quand_actif(self, engine, monkeypatch):
        class TradesClient:
            def can_builder_auth(self) -> bool:
                return True

            def get_builder_trades(self, next_cursor: str = "MA=="):
                return [{"id": "t1", "cursor": next_cursor}]

        engine.client = TradesClient()
        assert engine.get_builder_trades() == [{"id": "t1", "cursor": "MA=="}]

    def test_propage_le_curseur(self, engine):
        class TradesClient:
            def can_builder_auth(self) -> bool:
                return True

            def get_builder_trades(self, next_cursor: str = "MA=="):
                return next_cursor

        engine.client = TradesClient()
        assert engine.get_builder_trades("PAGE2") == "PAGE2"


class TestEnsureApiCreds:
    def test_pose_les_creds_sur_le_client(self, engine):
        class CredsClient:
            def __init__(self) -> None:
                self.posed = None

            def create_or_derive_api_creds(self):
                class Creds:
                    api_key = "derived-key-123456"

                return Creds()

            def set_api_creds(self, creds) -> None:
                self.posed = creds

        client = CredsClient()
        engine.client = client
        creds = engine.ensure_api_creds()
        assert creds.api_key == "derived-key-123456"
        assert client.posed is creds

"""Tests de non-régression sécurité.

Chacun de ces tests correspond à une faiblesse réelle de la version
initiale du projet. S'ils passent au rouge, la régression est de nature
sécuritaire, pas fonctionnelle.
"""

from __future__ import annotations

import logging

import pytest

from src.client import PolymarketEngine
from src.config import Secret, Settings
from src.errors import ConfigError, TradingDisabledError
from tests.conftest import TEST_KEY


class TestSecretMasking:
    """La clé privée ne doit apparaître dans AUCUNE sortie textuelle."""

    def test_repr_masque_la_valeur(self):
        # Valeur ostensiblement factice : ne jamais utiliser un fragment d'un
        # secret reel comme donnee de test, meme tronque — il finirait dans
        # l'historique git et declencherait les scanners.
        secret = Secret("valeur-de-test-non-sensible")
        assert "valeur-de-test" not in repr(secret)
        assert "valeur-de-test" not in str(secret)
        assert "***" in repr(secret)

    def test_repr_des_settings_ne_fuit_pas(self, settings):
        rendered = repr(settings)
        assert TEST_KEY not in rendered

    def test_reveal_est_le_seul_acces(self):
        secret = Secret("valeur-sensible")
        assert secret.reveal() == "valeur-sensible"

    def test_repr_du_moteur_ne_fuit_pas(self, settings):
        engine = PolymarketEngine(settings)
        assert TEST_KEY not in repr(engine)
        # L'adresse publique, elle, doit bien être exposée : c'est son rôle.
        assert engine.address.startswith("0x")

    def test_les_logs_ne_contiennent_pas_la_cle(self, settings, caplog):
        with caplog.at_level(logging.DEBUG):
            PolymarketEngine(settings)
        assert TEST_KEY not in caplog.text


class TestKeyValidation:
    def test_cle_absente_est_rejetee(self, monkeypatch):
        monkeypatch.delenv("POLYGON_PRIVATE_KEY", raising=False)
        with pytest.raises(ConfigError, match="absent"):
            Settings.from_env()

    def test_cle_vide_est_rejetee(self, monkeypatch):
        monkeypatch.setenv("POLYGON_PRIVATE_KEY", "   ")
        with pytest.raises(ConfigError, match="absent"):
            Settings.from_env()

    @pytest.mark.parametrize(
        "bad",
        [
            "trop-court",
            "ff" * 10,  # 20 hex
            "ff" * 40,  # 80 hex
            "zz" * 32,  # non hexadécimal
            "remplace_par_ta_cle_privee_64_hex",  # placeholder du .env.example
        ],
    )
    def test_cle_malformee_est_rejetee(self, monkeypatch, bad):
        monkeypatch.setenv("POLYGON_PRIVATE_KEY", bad)
        with pytest.raises(ConfigError, match="malformée"):
            Settings.from_env()

    @pytest.mark.parametrize("good", ["ab" * 32, "0x" + "ab" * 32, "AB" * 32])
    def test_cle_valide_est_acceptee(self, monkeypatch, good):
        monkeypatch.setenv("POLYGON_PRIVATE_KEY", good)
        assert Settings.from_env().private_key.reveal() == good


class TestTradingKillSwitch:
    """Aucun ordre ne doit pouvoir partir sans opt-in explicite."""

    def test_desactive_par_defaut(self, settings):
        assert settings.enable_trading is False

    def test_ordre_refuse_quand_desactive(self, settings):
        engine = PolymarketEngine(settings)
        with pytest.raises(TradingDisabledError, match="POLY_ENABLE_TRADING"):
            engine.place_limit_order("token-1", price=0.5, size=10)

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
    def test_valeurs_activantes(self, monkeypatch, value):
        monkeypatch.setenv("POLYGON_PRIVATE_KEY", TEST_KEY)
        monkeypatch.setenv("POLY_ENABLE_TRADING", value)
        assert Settings.from_env().enable_trading is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "", "peut-etre"])
    def test_valeurs_non_activantes(self, monkeypatch, value):
        monkeypatch.setenv("POLYGON_PRIVATE_KEY", TEST_KEY)
        monkeypatch.setenv("POLY_ENABLE_TRADING", value)
        assert Settings.from_env().enable_trading is False


class TestOrderValidation:
    """La validation précède le coupe-circuit : un ordre absurde est rejeté
    même en mode trading, avant toute signature."""

    @pytest.mark.parametrize("price", [0, 1, -0.5, 1.5, 100])
    def test_prix_hors_intervalle(self, trading_settings, price):
        engine = PolymarketEngine(trading_settings)
        with pytest.raises(ValueError, match=r"\]0, 1\["):
            engine.place_limit_order("token-1", price=price, size=10)

    @pytest.mark.parametrize("size", [0, -1, -0.001])
    def test_taille_non_positive(self, trading_settings, size):
        engine = PolymarketEngine(trading_settings)
        with pytest.raises(ValueError, match="size doit être > 0"):
            engine.place_limit_order("token-1", price=0.5, size=size)

    def test_token_id_vide(self, trading_settings):
        engine = PolymarketEngine(trading_settings)
        with pytest.raises(ValueError, match="token_id est requis"):
            engine.place_limit_order("", price=0.5, size=10)

    def test_side_invalide(self, trading_settings):
        engine = PolymarketEngine(trading_settings)
        with pytest.raises(ValueError, match="BUY ou SELL"):
            engine.place_limit_order("token-1", price=0.5, size=10, side="LONG")

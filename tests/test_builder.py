"""Tests de la configuration builder.

Point clé : `BUILDER_CODE` (une chaîne hex) n'a jamais été un mécanisme
d'attribution reconnu par le SDK Polymarket, qui exige un triplet
key/secret/passphrase. La version initiale du projet lisait cette variable
sans jamais la transmettre — on pouvait donc croire l'attribution active
alors qu'elle ne l'était pas. Ces tests verrouillent le comportement correct.
"""

from __future__ import annotations

import logging

import pytest

from src.client import _to_builder_config
from src.config import ApiCredentials, BuilderConfiguration, Secret
from src.errors import ConfigError

BUILDER_VARS = (
    "BUILDER_API_KEY",
    "BUILDER_API_SECRET",
    "BUILDER_API_PASSPHRASE",
    "BUILDER_REMOTE_URL",
    "BUILDER_REMOTE_TOKEN",
    "BUILDER_CODE",
)


@pytest.fixture(autouse=True)
def _clean_builder_env(monkeypatch):
    """Isole chaque test du .env du développeur."""
    for var in BUILDER_VARS:
        monkeypatch.delenv(var, raising=False)


class TestBuilderCredsLocales:
    def test_triplet_complet(self, monkeypatch):
        monkeypatch.setenv("BUILDER_API_KEY", "bk-123")
        monkeypatch.setenv("BUILDER_API_SECRET", "bs-456")
        monkeypatch.setenv("BUILDER_API_PASSPHRASE", "bp-789")

        builder = BuilderConfiguration.from_env()
        assert builder.is_configured is True
        assert builder.mode == "creds locales"
        assert builder.creds is not None
        assert builder.creds.key == "bk-123"

    @pytest.mark.parametrize(
        "present",
        [
            {"BUILDER_API_KEY": "k"},
            {"BUILDER_API_KEY": "k", "BUILDER_API_SECRET": "s"},
            {"BUILDER_API_SECRET": "s"},
            {"BUILDER_API_PASSPHRASE": "p"},
        ],
    )
    def test_triplet_incomplet_est_rejete(self, monkeypatch, present):
        """Mieux vaut échouer que signer avec des creds partielles."""
        for key, value in present.items():
            monkeypatch.setenv(key, value)
        with pytest.raises(ConfigError, match="incomplètes"):
            BuilderConfiguration.from_env()

    def test_aucune_var_donne_non_configure(self):
        builder = BuilderConfiguration.from_env()
        assert builder.is_configured is False
        assert builder.mode == "non configuré"
        assert builder.creds is None


class TestSigneurDistant:
    def test_url_seule_suffit(self, monkeypatch):
        monkeypatch.setenv("BUILDER_REMOTE_URL", "https://signer.example")
        builder = BuilderConfiguration.from_env()
        assert builder.is_configured is True
        assert "signeur distant" in builder.mode

    def test_avec_token(self, monkeypatch):
        monkeypatch.setenv("BUILDER_REMOTE_URL", "https://signer.example")
        monkeypatch.setenv("BUILDER_REMOTE_TOKEN", "tok-secret")
        builder = BuilderConfiguration.from_env()
        assert builder.remote_token is not None
        assert builder.remote_token.reveal() == "tok-secret"

    def test_modes_mutuellement_exclusifs(self, monkeypatch):
        monkeypatch.setenv("BUILDER_API_KEY", "k")
        monkeypatch.setenv("BUILDER_API_SECRET", "s")
        monkeypatch.setenv("BUILDER_API_PASSPHRASE", "p")
        monkeypatch.setenv("BUILDER_REMOTE_URL", "https://signer.example")
        with pytest.raises(ConfigError, match="mutuellement exclusives"):
            BuilderConfiguration.from_env()


class TestLegacyBuilderCode:
    def test_builder_code_seul_avertit_et_ne_configure_rien(self, monkeypatch, caplog):
        monkeypatch.setenv("BUILDER_CODE", "0x" + "82" * 32)
        with caplog.at_level(logging.WARNING):
            builder = BuilderConfiguration.from_env()

        assert builder.is_configured is False
        assert "n'est pas un mécanisme d'attribution reconnu" in caplog.text
        assert "docs/BUILDER.md" in caplog.text

    def test_pas_davertissement_si_vraies_creds_presentes(self, monkeypatch, caplog):
        monkeypatch.setenv("BUILDER_CODE", "0x" + "82" * 32)
        monkeypatch.setenv("BUILDER_API_KEY", "k")
        monkeypatch.setenv("BUILDER_API_SECRET", "s")
        monkeypatch.setenv("BUILDER_API_PASSPHRASE", "p")
        with caplog.at_level(logging.WARNING):
            builder = BuilderConfiguration.from_env()

        assert builder.is_configured is True
        assert "n'est pas un mécanisme" not in caplog.text


class TestTraductionVersLeSdk:
    def test_creds_locales_produisent_un_builder_config(self):
        builder = BuilderConfiguration(
            creds=ApiCredentials(key="k", secret=Secret("s"), passphrase=Secret("p"))
        )
        config = _to_builder_config(builder)
        assert config is not None
        assert config.is_valid() is True

    def test_signeur_distant_produit_un_builder_config(self):
        config = _to_builder_config(BuilderConfiguration(remote_url="https://signer.example"))
        assert config is not None

    def test_non_configure_donne_none(self):
        assert _to_builder_config(BuilderConfiguration()) is None


class TestApiCredsL2:
    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        for var in ("CLOB_API_KEY", "CLOB_API_SECRET", "CLOB_API_PASSPHRASE"):
            monkeypatch.delenv(var, raising=False)

    def test_absentes_donnent_none(self):
        assert ApiCredentials.from_env("CLOB") is None

    def test_triplet_complet(self, monkeypatch):
        monkeypatch.setenv("CLOB_API_KEY", "k")
        monkeypatch.setenv("CLOB_API_SECRET", "s")
        monkeypatch.setenv("CLOB_API_PASSPHRASE", "p")
        creds = ApiCredentials.from_env("CLOB")
        assert creds is not None
        assert creds.key == "k"

    def test_incompletes_rejetees(self, monkeypatch):
        monkeypatch.setenv("CLOB_API_KEY", "k")
        with pytest.raises(ConfigError, match="incomplètes"):
            ApiCredentials.from_env("CLOB")

    def test_secrets_masques_dans_repr(self, monkeypatch):
        monkeypatch.setenv("CLOB_API_KEY", "k")
        monkeypatch.setenv("CLOB_API_SECRET", "secret-sensible")
        monkeypatch.setenv("CLOB_API_PASSPHRASE", "pass-sensible")
        creds = ApiCredentials.from_env("CLOB")
        rendered = repr(creds)
        assert "secret-sensible" not in rendered
        assert "pass-sensible" not in rendered

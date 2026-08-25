"""Fixtures partagées.

La clé utilisée ici est une valeur de test déterministe et publique
(0x01 répété). Elle ne contrôle aucun fonds.
"""

from __future__ import annotations

import pytest

from src.config import Secret, Settings

# Clé de test valide sur le plan du format, sans valeur économique.
TEST_KEY = "01" * 32


@pytest.fixture
def settings() -> Settings:
    return Settings(private_key=Secret(TEST_KEY))


@pytest.fixture
def trading_settings() -> Settings:
    return Settings(private_key=Secret(TEST_KEY), enable_trading=True)


@pytest.fixture
def gamma_payload() -> list[dict]:
    """Charge utile Gamma réaliste : deux événements, trois marchés."""
    return [
        {
            "title": "Fed decisions",
            "markets": [
                {
                    "question": "Fed cuts rates in 2026?",
                    "volume24hr": "1254300.5",
                    "clobTokenIds": '["111", "222"]',
                },
                {
                    "question": "Fed hikes in 2026?",
                    "volume24hr": None,
                    "clobTokenIds": ["333", "444"],
                },
            ],
        },
        {
            "title": "Crypto",
            "markets": [
                {
                    "question": "BTC above 100k?",
                    "volume24hr": "not-a-number",
                    "clobTokenIds": "malformed-json",
                }
            ],
        },
    ]

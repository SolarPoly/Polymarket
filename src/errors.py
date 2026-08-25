"""Exceptions du moteur PolyTrade.

Chaque erreur est explicite : aucune ne doit jamais être avalée
silencieusement au profit de données factices (cf. incident du mock
fallback qui faisait passer une panne réseau pour un succès).
"""


class PolyTradeError(Exception):
    """Erreur de base du moteur."""


class ConfigError(PolyTradeError):
    """Configuration absente, malformée ou invalide."""


class MarketDataError(PolyTradeError):
    """L'API Gamma est injoignable ou renvoie une charge utile invalide."""


class ClobError(PolyTradeError):
    """Le CLOB Polymarket a rejeté l'appel ou est injoignable."""


class TradingDisabledError(PolyTradeError):
    """Une écriture a été tentée alors que le mode trading est désactivé."""

"""Jeu de données de démonstration, pour montrer l'interface hors ligne.

## Pourquoi ce module existe, et pourquoi il n'est pas un retour du mock

La version initiale du projet renvoyait des marchés factices dès qu'un appel
réseau échouait. C'était nuisible : une coupure devenait un succès apparent,
et rien ne distinguait un prix réel d'un prix inventé. Ce fallback a été
supprimé.

Ce module est l'inverse exact, sur trois points :

1. **Opt-in explicite.** Il ne s'active que sur `--demo` (ou
   `POLY_DEMO_MODE=true`). Jamais en réaction à une panne.
2. **Étiqueté partout.** Chaque réponse d'API porte `"demo": true`, et
   l'interface affiche un bandeau permanent. On ne peut pas confondre.
3. **Aucun accès réseau ni wallet.** Rien n'est signé, aucune clé n'est lue.

Utilité réelle : montrer l'interface quand Polymarket est filtré sur le
réseau — une démonstration à un partenaire, une capture d'écran, ou le
développement du front sans dépendre de la disponibilité de l'API.

Les valeurs sont figées et cohérentes entre elles (spreads plausibles,
profondeurs asymétriques, un carnet volontairement illiquide et un cas
d'arbitrage) pour que chaque état de l'interface soit visible.
"""

from __future__ import annotations

from typing import Any

DEMO_WALLET = "0xDEM0000000000000000000000000000000000001"

# Marchés couvrant volontairement plusieurs cas d'affichage : gros volume,
# volume nul, intitulé long, et un marché sans token NO.
DEMO_MARKETS: list[dict[str, Any]] = [
    {
        "question": "La Fed baissera-t-elle ses taux avant fin 2026 ?",
        "event_title": "Politique monétaire",
        "volume24hr": "1254300",
        "clobTokenIds": '["demo-fed-yes", "demo-fed-no"]',
    },
    {
        "question": "Bitcoin au-dessus de 100 000 $ au 31 décembre ?",
        "event_title": "Crypto",
        "volume24hr": "845200",
        "clobTokenIds": '["demo-btc-yes", "demo-btc-no"]',
    },
    {
        "question": "Un candidat obtiendra-t-il plus de 50 % au premier tour ?",
        "event_title": "Élections",
        "volume24hr": "312850",
        "clobTokenIds": '["demo-elec-yes", "demo-elec-no"]',
    },
    {
        "question": "Marché peu liquide, pour illustrer un spread large",
        "event_title": "Divers",
        "volume24hr": "1200",
        "clobTokenIds": '["demo-thin-yes", "demo-thin-no"]',
    },
    {
        "question": "Marché sans cotation, pour illustrer un carnet vide",
        "event_title": "Divers",
        "volume24hr": "0",
        "clobTokenIds": '["demo-empty-yes"]',
    },
]


class DemoLevel:
    """Reproduit un `OrderSummary` du SDK : prix et tailles en chaînes."""

    __slots__ = ("price", "size")

    def __init__(self, price: str, size: str) -> None:
        self.price = price
        self.size = size


class DemoBook:
    """Reproduit un `OrderBookSummary` : seuls `bids` et `asks` sont lus."""

    __slots__ = ("asset_id", "bids", "asks")

    def __init__(
        self, asset_id: str, bids: list[tuple[str, str]], asks: list[tuple[str, str]]
    ) -> None:
        self.asset_id = asset_id
        self.bids = [DemoLevel(p, s) for p, s in bids]
        self.asks = [DemoLevel(p, s) for p, s in asks]


# Carnets couvrant chaque état que l'interface sait afficher : liquide,
# déséquilibré, illiquide, croisé, et vide.
_BOOKS: dict[str, DemoBook] = {
    "demo-fed-yes": DemoBook(
        "demo-fed-yes",
        bids=[("0.62", "4200"), ("0.61", "8800"), ("0.60", "15000"), ("0.58", "22000")],
        asks=[("0.64", "3900"), ("0.65", "7400"), ("0.67", "11000"), ("0.70", "18500")],
    ),
    "demo-fed-no": DemoBook(
        "demo-fed-no",
        bids=[("0.35", "5100"), ("0.34", "9200"), ("0.32", "14000")],
        asks=[("0.38", "4600"), ("0.39", "8100"), ("0.41", "12500")],
    ),
    # Déséquilibre marqué côté achat : la barre du front penche visiblement.
    "demo-btc-yes": DemoBook(
        "demo-btc-yes",
        bids=[("0.44", "26000"), ("0.43", "31000"), ("0.41", "48000")],
        asks=[("0.46", "3200"), ("0.48", "5100")],
    ),
    "demo-btc-no": DemoBook(
        "demo-btc-no",
        bids=[("0.53", "3000"), ("0.51", "4200")],
        asks=[("0.55", "24000"), ("0.57", "38000")],
    ),
    "demo-elec-yes": DemoBook(
        "demo-elec-yes",
        bids=[("0.28", "12000"), ("0.27", "19000")],
        asks=[("0.30", "9500"), ("0.32", "16000")],
    ),
    # Somme YES + NO nettement sous 1 : cas d'arbitrage visible.
    "demo-elec-no": DemoBook(
        "demo-elec-no",
        bids=[("0.66", "8000")],
        asks=[("0.68", "7200"), ("0.71", "13000")],
    ),
    # Spread très large : `is_liquid` doit ressortir à faux.
    "demo-thin-yes": DemoBook("demo-thin-yes", bids=[("0.10", "300")], asks=[("0.34", "250")]),
    "demo-thin-no": DemoBook("demo-thin-no", bids=[("0.62", "180")], asks=[("0.90", "220")]),
    # Aucun niveau : l'interface doit afficher des tirets, pas des zéros.
    "demo-empty-yes": DemoBook("demo-empty-yes", bids=[], asks=[]),
}


def demo_book(token_id: str) -> DemoBook:
    """Carnet de démonstration pour un token.

    Un identifiant inconnu retourne un carnet vide plutôt que de lever : en
    démonstration, saisir un token au hasard doit montrer l'état « vide », pas
    une erreur.
    """
    return _BOOKS.get(token_id, DemoBook(token_id, bids=[], asks=[]))


def demo_markets(limit: int) -> list[dict[str, Any]]:
    return DEMO_MARKETS[:limit]

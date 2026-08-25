"""Lecture des marchés via l'API Gamma de Polymarket.

Changements par rapport à la version initiale :

* `subprocess.run(["curl", ...])` remplacé par `requests` + `urllib3.Retry`.
  L'appel à un binaire externe imposait la présence de curl, empêchait toute
  gestion fine des erreurs HTTP et masquait le code de statut.
* Le fallback vers des données factices est **supprimé**. Il transformait
  n'importe quelle panne (réseau, DNS, JSON invalide) en faux succès. Les
  échecs remontent désormais en `MarketDataError`.
* Les paramètres de requête passent par `params=` : plus de construction
  d'URL par f-string.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import DEFAULT_GAMMA_HOST
from .errors import MarketDataError

logger = logging.getLogger(__name__)

_RETRY = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
)


def _build_session() -> requests.Session:
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=_RETRY))
    session.headers.update(
        {
            "Accept": "application/json",
            "User-Agent": "polytrade-engine/1.0 (+https://github.com/SolarPoly/Polymarket)",
        }
    )
    return session


class GammaMarketScanner:
    """Client lecture seule de l'API Gamma."""

    def __init__(
        self,
        host: str = DEFAULT_GAMMA_HOST,
        timeout: int = 15,
        session: requests.Session | None = None,
    ) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout
        self._session = session or _build_session()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> GammaMarketScanner:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get_active_markets(self, limit: int = 5) -> list[dict[str, Any]]:
        """Retourne jusqu'à `limit` marchés actifs.

        Lève `MarketDataError` si l'API est injoignable ou répond hors format.
        Ne retourne jamais de données de substitution.
        """
        if limit < 1:
            raise ValueError("limit doit être >= 1")

        url = f"{self.host}/events"
        params: dict[str, str | int] = {"limit": limit, "active": "true", "closed": "false"}

        try:
            response = self._session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
        except requests.exceptions.SSLError as exc:
            raise MarketDataError(
                f"Échec TLS vers {self.host}. Un blocage DNS/FAI redirigeant le "
                "domaine vers un sinkhole produit ce symptôme."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise MarketDataError(
                f"Connexion impossible à {self.host}. Vérifie la résolution DNS : "
                "le domaine peut être redirigé par le FAI."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise MarketDataError(f"Délai de {self.timeout}s dépassé sur {url}.") from exc
        except requests.exceptions.RetryError as exc:
            # Retries épuisés sur des 429/5xx. `RetryError` est une soeur de
            # ConnectionError, pas une sous-classe : sans ce handler explicite
            # elle s'échapperait de la fonction.
            raise MarketDataError(
                f"L'API Gamma a échoué de façon répétée sur {url} (retries épuisés sur 429/5xx)."
            ) from exc
        except requests.exceptions.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            raise MarketDataError(f"L'API Gamma a répondu HTTP {code}.") from exc
        except requests.exceptions.RequestException as exc:
            # Filet de sécurité : toute autre défaillance requests devient une
            # MarketDataError, jamais une exception nue remontant à l'appelant.
            raise MarketDataError(f"Requête vers {url} échouée : {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise MarketDataError(
                f"Réponse non-JSON de l'API Gamma ({len(response.content)} octets)."
            ) from exc

        if not isinstance(payload, list):
            raise MarketDataError(
                f"Format inattendu : liste d'événements attendue, reçu {type(payload).__name__}."
            )

        markets = self._flatten_events(payload)
        logger.info(
            "Gamma a renvoyé %d marché(s) depuis %d événement(s).", len(markets), len(payload)
        )
        return markets[:limit]

    @staticmethod
    def _flatten_events(events: list[Any]) -> list[dict[str, Any]]:
        """Aplatit les marchés imbriqués dans les événements, en ignorant le bruit."""
        markets: list[dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            for market in event.get("markets") or []:
                if not isinstance(market, dict):
                    continue
                enriched = dict(market)
                enriched["event_title"] = event.get("title")
                markets.append(enriched)
        return markets

    @staticmethod
    def get_market_tokens(market: dict[str, Any]) -> dict[str, str | None]:
        """Extrait les identifiants de tokens YES/NO d'un marché.

        Gamma renvoie `clobTokenIds` soit en liste, soit en chaîne JSON.
        """
        raw = market.get("clobTokenIds") or []

        if isinstance(raw, str):
            try:
                tokens = json.loads(raw)
            except ValueError:
                logger.warning("clobTokenIds illisible pour %r", market.get("question"))
                tokens = []
        else:
            tokens = raw

        if not isinstance(tokens, list):
            tokens = []

        return {
            "YES": tokens[0] if len(tokens) > 0 else None,
            "NO": tokens[1] if len(tokens) > 1 else None,
        }

    @staticmethod
    def volume_24h(market: dict[str, Any]) -> float:
        """Volume 24h en float, robuste aux `None` / chaînes vides / non-numériques."""
        try:
            return float(market.get("volume24hr") or 0)
        except (TypeError, ValueError):
            return 0.0

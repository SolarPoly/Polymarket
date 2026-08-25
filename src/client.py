"""Enveloppe autour du client CLOB Polymarket.

Garde-fous :

* **Coupe-circuit** : `place_limit_order` refuse d'agir si
  `POLY_ENABLE_TRADING` n'est pas explicitement à `true`. Un lancement
  accidentel du script ne peut donc pas engager de fonds.
* **Validation des ordres** avant signature : un prix Polymarket est une
  probabilité, il doit être strictement dans ]0, 1[. Une taille doit être
  strictement positive.
* **Aucune fuite de secret** : les clés ne sont lues qu'au moment de
  construire le client, via `Secret.reveal()`, et ne sont jamais stockées en
  attribut d'instance — donc invisibles dans un `repr()` ou un traceback.
"""

from __future__ import annotations

import logging
from typing import Any

from eth_account import Account
from py_builder_signing_sdk.config import BuilderConfig
from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds, RemoteBuilderConfig
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from .analytics import BookAnalysis, analyze_book
from .config import BuilderConfiguration, Settings
from .errors import ClobError, TradingDisabledError

logger = logging.getLogger(__name__)


def _to_builder_config(builder: BuilderConfiguration) -> BuilderConfig | None:
    """Traduit notre configuration en `BuilderConfig` du SDK.

    Le SDK n'accepte pas de « code » builder : soit un triplet de credentials
    signant en local, soit l'URL d'un signeur distant.
    """
    if builder.creds is not None:
        return BuilderConfig(
            local_builder_creds=BuilderApiKeyCreds(
                key=builder.creds.key,
                secret=builder.creds.secret.reveal(),
                passphrase=builder.creds.passphrase.reveal(),
            )
        )
    if builder.remote_url:
        return BuilderConfig(
            remote_builder_config=RemoteBuilderConfig(
                url=builder.remote_url,
                token=builder.remote_token.reveal() if builder.remote_token else None,
            )
        )
    return None


class PolymarketEngine:
    """Accès au CLOB Polymarket, en lecture par défaut."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # Dérivée localement, sans appel réseau : utile pour tracer QUEL wallet
        # signe, sans jamais exposer la clé elle-même.
        self.address: str = Account.from_key(settings.private_key.reveal()).address

        creds = None
        if settings.api_creds is not None:
            creds = ApiCreds(
                api_key=settings.api_creds.key,
                api_secret=settings.api_creds.secret.reveal(),
                api_passphrase=settings.api_creds.passphrase.reveal(),
            )

        try:
            self.client = ClobClient(
                host=settings.clob_host,
                key=settings.private_key.reveal(),
                chain_id=settings.chain_id,
                creds=creds,
                builder_config=_to_builder_config(settings.builder),
            )
        except Exception as exc:  # le SDK ne définit pas d'exception d'init dédiée
            raise ClobError(f"Initialisation du client CLOB impossible : {exc}") from exc

        logger.info(
            "Moteur CLOB prêt — wallet %s, chain %d, trading %s, builder %s.",
            self.address,
            settings.chain_id,
            "ACTIVÉ" if settings.enable_trading else "désactivé (lecture seule)",
            settings.builder.mode,
        )

    def __repr__(self) -> str:
        return (
            f"PolymarketEngine(address={self.address}, "
            f"chain_id={self.settings.chain_id}, "
            f"trading_enabled={self.settings.enable_trading}, "
            f"builder={self.builder_enabled})"
        )

    # ------------------------------------------------------------------ santé

    def health_check(self) -> bool:
        """Vérifie que le CLOB répond réellement.

        Le constructeur de `ClobClient` ne fait aucun appel réseau : une
        instanciation réussie ne prouve donc rien. Cette méthode le prouve.
        """
        try:
            self.client.get_ok()
        except Exception as exc:
            logger.warning("Health check CLOB échoué : %s", exc)
            return False
        return True

    # ---------------------------------------------------------------- builder

    @property
    def builder_enabled(self) -> bool:
        """Le SDK reconnaît-il l'authentification builder comme utilisable ?

        Distinct de `settings.builder.is_configured` : ici c'est le SDK qui
        valide, donc un triplet mal formé ressort à `False`.
        """
        try:
            return bool(self.client.can_builder_auth())
        except Exception:
            return False

    def get_builder_trades(self, next_cursor: str = "MA==") -> Any:
        """Trades attribués à ton compte builder (`GET /builder/trades`).

        Nécessite des credentials builder délivrés par Polymarket. Voir
        `docs/BUILDER.md` pour la procédure de candidature.
        """
        if not self.builder_enabled:
            raise ClobError(
                "Authentification builder indisponible. Renseigne BUILDER_API_KEY / "
                "BUILDER_API_SECRET / BUILDER_API_PASSPHRASE (ou BUILDER_REMOTE_URL) "
                "avec des credentials délivrés par Polymarket. Voir docs/BUILDER.md."
            )
        try:
            return self.client.get_builder_trades(next_cursor=next_cursor)
        except Exception as exc:
            raise ClobError(f"get_builder_trades a échoué : {exc}") from exc

    # --------------------------------------------------------------- auth L2

    def ensure_api_creds(self) -> ApiCreds:
        """Dérive (ou crée) les credentials L2 depuis la clé privée.

        Les endpoints authentifiés — ordres, positions, trades — en ont besoin.
        Elles sont déterministes pour une clé et un nonce donnés : les stocker
        dans `.env` évite un aller-retour réseau au démarrage.
        """
        try:
            creds = self.client.create_or_derive_api_creds()
        except Exception as exc:
            raise ClobError(f"Dérivation des credentials API échouée : {exc}") from exc
        self.client.set_api_creds(creds)
        logger.info("Credentials L2 en place (api_key %s...).", creds.api_key[:8])
        return creds

    # ---------------------------------------------------------------- lecture

    def get_sampling_markets(self) -> Any:
        try:
            return self.client.get_sampling_markets()
        except Exception as exc:
            raise ClobError(f"get_sampling_markets a échoué : {exc}") from exc

    def get_order_book(self, token_id: str) -> Any:
        if not token_id:
            raise ValueError("token_id est requis")
        try:
            return self.client.get_order_book(token_id)
        except Exception as exc:
            raise ClobError(f"Carnet d'ordres indisponible pour {token_id} : {exc}") from exc

    def analyze_token(self, token_id: str) -> BookAnalysis:
        """Récupère le carnet d'un token et en retourne l'analyse."""
        return analyze_book(self.get_order_book(token_id))

    def get_midpoint(self, token_id: str) -> Any:
        if not token_id:
            raise ValueError("token_id est requis")
        try:
            return self.client.get_midpoint(token_id)
        except Exception as exc:
            raise ClobError(f"Midpoint indisponible pour {token_id} : {exc}") from exc

    def get_spread(self, token_id: str) -> Any:
        if not token_id:
            raise ValueError("token_id est requis")
        try:
            return self.client.get_spread(token_id)
        except Exception as exc:
            raise ClobError(f"Spread indisponible pour {token_id} : {exc}") from exc

    # --------------------------------------------------------------- écriture

    @staticmethod
    def _validate_order(token_id: str, price: float, size: float, side: str) -> str:
        if not token_id:
            raise ValueError("token_id est requis")
        if not 0 < price < 1:
            raise ValueError(
                f"price doit être dans ]0, 1[ (probabilité Polymarket), reçu : {price}"
            )
        if size <= 0:
            raise ValueError(f"size doit être > 0, reçu : {size}")

        normalized = side.strip().upper()
        if normalized not in {"BUY", "SELL"}:
            raise ValueError(f"side doit être BUY ou SELL, reçu : {side!r}")
        return normalized

    def place_limit_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str = "BUY",
        order_type: OrderType = OrderType.GTC,
    ) -> Any:
        """Place un ordre limite. Engage des fonds réels.

        Exige `POLY_ENABLE_TRADING=true`, sinon lève `TradingDisabledError`.
        """
        normalized = self._validate_order(token_id, price, size, side)

        if not self.settings.enable_trading:
            raise TradingDisabledError(
                "Trading désactivé : aucun ordre envoyé. Pour autoriser les "
                "ordres réels, définis POLY_ENABLE_TRADING=true dans .env. "
                f"(Ordre refusé : {normalized} {size} @ {price} sur {token_id})"
            )

        logger.warning(
            "ENVOI D'UN ORDRE RÉEL : %s %s @ %s sur %s", normalized, size, price, token_id
        )

        order_args = OrderArgs(
            price=price,
            size=size,
            side=BUY if normalized == "BUY" else SELL,
            token_id=token_id,
        )
        try:
            signed_order = self.client.create_order(order_args)
            return self.client.post_order(signed_order, order_type)
        except Exception as exc:
            raise ClobError(f"Envoi de l'ordre échoué : {exc}") from exc

"""Chargement et validation de la configuration.

Règles de sécurité appliquées ici :

1. Toute valeur sensible est enveloppée dans `Secret`, dont `__repr__` /
   `__str__` sont masqués. Un `print(settings)`, un traceback ou un log ne
   peuvent donc pas divulguer une clé.
2. La clé privée est validée (64 caractères hexadécimaux) avant tout usage,
   ce qui évite d'envoyer une valeur tronquée au signeur.
3. Le trading est **désactivé par défaut**. Placer un ordre réel exige
   `POLY_ENABLE_TRADING=true` explicitement : un script lancé par erreur ne
   peut pas engager de fonds.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field

from .errors import ConfigError

logger = logging.getLogger(__name__)

_HEX64 = re.compile(r"\A(?:0x)?[0-9a-fA-F]{64}\Z")

DEFAULT_CLOB_HOST = "https://clob.polymarket.com"
DEFAULT_GAMMA_HOST = "https://gamma-api.polymarket.com"
POLYGON_CHAIN_ID = 137


class Secret:
    """Enveloppe une valeur sensible pour la rendre non-imprimable.

    La valeur n'est accessible que par `reveal()`, ce qui rend tout accès
    volontaire et grep-able en revue de code.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***masqué***)"

    __str__ = __repr__

    def __bool__(self) -> bool:
        return bool(self._value)


def _require_env(name: str) -> str:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise ConfigError(
            f"{name} est absent. Copie .env.example vers .env et renseigne-le. "
            "Ne committe jamais .env."
        )
    return raw


def _opt_env(name: str) -> str:
    return os.getenv(name, "").strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} doit être un entier, reçu : {raw!r}") from exc


@dataclass(frozen=True)
class ApiCredentials:
    """Credentials L2 du CLOB (accès aux endpoints authentifiés).

    Dérivables de la clé privée via `create_or_derive_api_creds()`. Les
    renseigner explicitement évite un aller-retour réseau à chaque démarrage.
    """

    key: str
    secret: Secret = field(repr=False)
    passphrase: Secret = field(repr=False)

    @classmethod
    def from_env(cls, prefix: str = "CLOB") -> ApiCredentials | None:
        key = _opt_env(f"{prefix}_API_KEY")
        secret = _opt_env(f"{prefix}_API_SECRET")
        passphrase = _opt_env(f"{prefix}_API_PASSPHRASE")

        provided = [bool(key), bool(secret), bool(passphrase)]
        if not any(provided):
            return None
        if not all(provided):
            raise ConfigError(
                f"Credentials {prefix} incomplètes : {prefix}_API_KEY, "
                f"{prefix}_API_SECRET et {prefix}_API_PASSPHRASE sont requis "
                "ensemble, ou aucun des trois."
            )
        return cls(key=key, secret=Secret(secret), passphrase=Secret(passphrase))


@dataclass(frozen=True)
class BuilderConfiguration:
    """Configuration du programme builder Polymarket.

    Deux modes exclusifs, tels que définis par `py_builder_signing_sdk` :

    * **creds locales** — un triplet key/secret/passphrase délivré par
      Polymarket, signant les en-têtes builder en local ;
    * **signeur distant** — une URL de service qui signe à ta place, utile
      pour ne pas exposer les creds builder aux machines d'exécution.

    Ces credentials ne se génèrent pas : ils sont attribués par Polymarket à
    l'issue d'une candidature. Voir `docs/BUILDER.md`.
    """

    creds: ApiCredentials | None = None
    remote_url: str = ""
    remote_token: Secret | None = field(default=None, repr=False)

    @property
    def is_configured(self) -> bool:
        return self.creds is not None or bool(self.remote_url)

    @property
    def mode(self) -> str:
        if self.creds is not None:
            return "creds locales"
        if self.remote_url:
            return f"signeur distant ({self.remote_url})"
        return "non configuré"

    @classmethod
    def from_env(cls) -> BuilderConfiguration:
        creds = ApiCredentials.from_env("BUILDER")
        remote_url = _opt_env("BUILDER_REMOTE_URL")
        remote_token = _opt_env("BUILDER_REMOTE_TOKEN")

        if creds is not None and remote_url:
            raise ConfigError(
                "Les creds builder locales et BUILDER_REMOTE_URL sont mutuellement "
                "exclusives : le SDK n'accepte qu'un seul mode de signature."
            )

        # `BUILDER_CODE` n'a jamais correspondu à l'API du SDK, qui attend un
        # triplet de credentials. Une valeur hex y est donc inopérante : on le
        # dit clairement plutôt que de l'ignorer en silence.
        legacy = _opt_env("BUILDER_CODE")
        if legacy and not (creds or remote_url):
            logger.warning(
                "BUILDER_CODE est défini mais n'est pas un mécanisme d'attribution "
                "reconnu par le SDK Polymarket, qui exige BUILDER_API_KEY / "
                "BUILDER_API_SECRET / BUILDER_API_PASSPHRASE (ou BUILDER_REMOTE_URL). "
                "Aucune attribution builder n'est active. Voir docs/BUILDER.md."
            )

        return cls(
            creds=creds,
            remote_url=remote_url,
            remote_token=Secret(remote_token) if remote_token else None,
        )


@dataclass(frozen=True)
class Settings:
    """Configuration immuable, validée à la construction."""

    private_key: Secret = field(repr=False)
    clob_host: str = DEFAULT_CLOB_HOST
    gamma_host: str = DEFAULT_GAMMA_HOST
    chain_id: int = POLYGON_CHAIN_ID
    enable_trading: bool = False
    request_timeout: int = 15
    api_creds: ApiCredentials | None = field(default=None, repr=False)
    builder: BuilderConfiguration = field(default_factory=BuilderConfiguration)

    @classmethod
    def from_env(cls) -> Settings:
        """Construit la configuration depuis l'environnement déjà chargé.

        `load_dotenv()` doit avoir été appelé au préalable (cf. `main.py`).
        """
        raw_key = _require_env("POLYGON_PRIVATE_KEY")

        if not _HEX64.match(raw_key):
            raise ConfigError(
                "POLYGON_PRIVATE_KEY est malformée : 64 caractères hexadécimaux "
                f"attendus (préfixe 0x optionnel), longueur reçue : {len(raw_key)}."
            )

        return cls(
            private_key=Secret(raw_key),
            clob_host=os.getenv("CLOB_HOST", DEFAULT_CLOB_HOST).rstrip("/"),
            gamma_host=os.getenv("GAMMA_HOST", DEFAULT_GAMMA_HOST).rstrip("/"),
            chain_id=_env_int("POLYGON_CHAIN_ID", POLYGON_CHAIN_ID),
            enable_trading=_env_bool("POLY_ENABLE_TRADING", False),
            request_timeout=_env_int("POLY_REQUEST_TIMEOUT", 15),
            api_creds=ApiCredentials.from_env("CLOB"),
            builder=BuilderConfiguration.from_env(),
        )

# PolyTrade Engine

Moteur Python de lecture et de trading sur [Polymarket](https://polymarket.com) :
API Gamma pour la découverte des marchés, CLOB pour le carnet d'ordres et
l'exécution.

> **Le trading est désactivé par défaut.** Aucun ordre ne peut partir sans
> `POLY_ENABLE_TRADING=true` explicite. Voir [Coupe-circuit](#coupe-circuit).

---

## Installation

Python 3.12 ou 3.13 requis.

```bash
git clone https://github.com/SolarPoly/Polymarket.git
cd Polymarket
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Un environnement virtuel est spécifique à un OS : ne le committe jamais, et
n'en réutilise pas un créé sur une autre plateforme.

## Configuration

```bash
cp .env.example .env
```

Renseigne `POLYGON_PRIVATE_KEY` dans `.env`. Ce fichier est ignoré par git.

| Variable | Requis | Défaut | Rôle |
|---|---|---|---|
| `POLYGON_PRIVATE_KEY` | oui | — | clé du wallet, 64 hex |
| `POLY_ENABLE_TRADING` | non | `false` | autorise les ordres réels |
| `CLOB_HOST` | non | `https://clob.polymarket.com` | endpoint CLOB |
| `GAMMA_HOST` | non | `https://gamma-api.polymarket.com` | endpoint Gamma |
| `POLYGON_CHAIN_ID` | non | `137` | Polygon mainnet |
| `POLY_REQUEST_TIMEOUT` | non | `15` | timeout HTTP (s) |
| `CLOB_API_*` | non | dérivées | credentials L2 (clé/secret/passphrase) |
| `BUILDER_API_*` | non | — | attribution builder, voir [docs/BUILDER.md](docs/BUILDER.md) |
| `BUILDER_CODE` | non | — | **obsolète, ne fait rien** |

Utilise un **wallet dédié**, alimenté au strict nécessaire. Le solde qui s'y
trouve est le plafond de ta perte en cas de fuite de clé.

## Utilisation

```bash
python main.py check                    # config, wallet, connectivité, builder
python main.py markets --limit 20       # marchés actifs via Gamma
python main.py book <token_id>          # analyse du carnet
python main.py book <token_id> --size 500   # + simulation de slippage
python main.py builder                  # statut d'attribution builder
python main.py builder --trades         # trades attribués
python main.py creds                    # dérive les credentials L2
python main.py serve                    # interface web sur 127.0.0.1:8000
```

Options globales : `--json` (sortie machine), `-v` (logs de debug).
Sans sous-commande, `markets` est exécuté.

Codes de sortie : `0` succès, `2` configuration invalide, `3` réseau injoignable.

### En bibliothèque

```python
from dotenv import load_dotenv
from src.client import PolymarketEngine
from src.config import Settings
from src.market import GammaMarketScanner

load_dotenv()
settings = Settings.from_env()
engine = PolymarketEngine(settings)

print(engine.address)  # wallet signataire
print(engine.health_check())  # le CLOB répond-il vraiment ?

with GammaMarketScanner(settings.gamma_host) as scanner:
    for market in scanner.get_active_markets(limit=5):
        tokens = scanner.get_market_tokens(market)
        print(market["question"], tokens["YES"])
```

## Coupe-circuit

`place_limit_order` engage des fonds réels. Il lève `TradingDisabledError`
tant que `POLY_ENABLE_TRADING` n'est pas à `true` :

```python
engine.place_limit_order(token_id, price=0.42, size=10, side="BUY")
# TradingDisabledError: Trading désactivé : aucun ordre envoyé.
```

La validation des paramètres est appliquée **avant** le coupe-circuit : un
prix hors de `]0, 1[` ou une taille négative est rejeté dans tous les cas,
avant toute signature.

## Interface web

```bash
python main.py serve --demo    # http://127.0.0.1:8000 — donnees simulees
python main.py serve           # donnees reelles (necessite un acces Polymarket)
```

### Voir l'interface sans acces a Polymarket

Sur un reseau ou Polymarket est filtre, l'interface reelle s'affiche vide avec
un bandeau d'erreur : elle fonctionne, mais elle n'a rien a montrer. Le mode
`--demo` sert un jeu de donnees fige couvrant chaque etat affichable — carnet
liquide, carnet desequilibre, spread large, carnet vide, profondeur
insuffisante. Il ne lit aucune cle et ne touche pas le reseau, donc il tourne
sans configuration.

**Ce n'est pas un retour du fallback supprime.** La difference est entiere :
le mode demo ne s'active que sur `--demo` (ou `POLY_DEMO_MODE=true`), jamais
en reaction a une panne ; chaque reponse d'API porte `"demo": true` ; et un
bandeau permanent s'affiche dans l'interface. L'ancien fallback, lui, se
declenchait silencieusement sur erreur reseau et etait indistinguable de vraies
donnees. Trois tests verrouillent cette distinction dans
[tests/test_demo.py](tests/test_demo.py).

Un front sans dependance ni etape de build : etat du moteur, marches actifs,
analyse de carnet avec barre de desequilibre et simulation de slippage,
statut builder. Un clic sur un token YES/NO d'un marche l'envoie directement
au panneau d'analyse.

L'ecoute est sur `127.0.0.1` par defaut, et c'est deliberé : le serveur donne
acces a un wallet capable de signer et n'a aucune authentification. Ouvrir
`--host 0.0.0.0` declenche un avertissement explicite.

L'interface ne fabrique jamais de donnee. Quand l'API renvoie une erreur, elle
affiche la cause exacte plutot qu'un tableau vide qui ressemblerait a « pas de
liquidite ». C'est le pendant cote front du choix fait dans `market.py`.

## Programme builder

L'attribution builder est entièrement implémentée côté code. Vérifie ton
statut :

```bash
python main.py builder
```

Les credentials sont délivrés par Polymarket après candidature — ils ne se
génèrent pas localement. La procédure, les points de contact et le piège de
`BUILDER_CODE` sont détaillés dans [docs/BUILDER.md](docs/BUILDER.md) ; une
trame de candidature est dans [docs/CANDIDATURE.md](docs/CANDIDATURE.md).

## Développement

```bash
pip install -r requirements-dev.txt
pre-commit install     # installe les hooks — indispensable, voir SECURITY.md

pytest                 # 199 tests, couverture 96 %
ruff check .
ruff format .
mypy src main.py
```

`tests/test_security.py` contient des tests de non-régression : masquage des
secrets, validation de clé, coupe-circuit, validation d'ordres. Une
régression y est de nature sécuritaire.

## Architecture

```
main.py            CLI a sous-commandes (lecture seule)
src/config.py      chargement + validation, enveloppe Secret, config builder
src/client.py      client CLOB, coupe-circuit, builder, auth L2
src/market.py      client Gamma (lecture seule)
src/analytics.py   analyse de carnet : spread, profondeur, slippage (pur)
src/errors.py      hierarchie d'exceptions
src/api.py         API HTTP FastAPI (lecture seule)
src/demo.py        jeu de donnees de demonstration (opt-in, etiquete)
web/               front sans dependance ni etape de build
tests/             pytest, reseau simule via responses
docs/BUILDER.md    programme builder Polymarket
docs/CANDIDATURE.md  trame de candidature au programme builder
```

### Choix de conception

**Aucun repli silencieux.** Une panne réseau, un JSON invalide ou un format
inattendu lève `MarketDataError`. La version initiale renvoyait des marchés
factices codés en dur, ce qui faisait passer une coupure réseau pour un
succès — un bot de trading construit dessus aurait pris des décisions sur des
prix inventés.

**Les secrets ne sont pas imprimables.** `Secret.__repr__` est masqué, donc
ni un `print`, ni un traceback, ni un log ne peuvent divulguer la clé. Seul
`reveal()` y donne accès, ce qui rend chaque accès grep-able en revue.

**Le health check est distinct de l'instanciation.** Le constructeur de
`ClobClient` ne fait aucun appel réseau : une instanciation réussie ne prouve
rien. `health_check()` interroge réellement le CLOB.

## Limites connues

**Blocage régional.** Polymarket est inaccessible depuis certains réseaux :
la résolution DNS renvoie une IP hors de son infrastructure et la connexion
TLS se ferme aussitôt. Le symptôme est un `MarketDataError` mentionnant TLS
ou la connexion. Vérifie avec `python main.py --check`.

**Credentials builder non générables.** Le support technique de
l'attribution builder est complet (`BuilderConfig`, en-têtes signés,
`GET /builder/trades`), mais les credentials sont délivrés par Polymarket
après candidature — aucun code ne peut les fabriquer. Procédure complète
dans [docs/BUILDER.md](docs/BUILDER.md).

**`BUILDER_CODE` est obsolète.** Cette variable du `.env` d'origine ne faisait
rien : le SDK n'accepte pas de « code » builder, il exige un triplet
key/secret/passphrase. Le moteur avertit désormais explicitement quand elle
est définie sans credentials réelles.

## Sécurité

Voir [SECURITY.md](SECURITY.md) — signalement, incident du 24/08/2026, et
procédure de purge d'un secret de l'historique git.

## Avertissement

Logiciel fourni tel quel, à des fins éducatives. Le trading de marchés
prédictifs comporte un risque de perte totale du capital engagé. Vérifie la
légalité de Polymarket dans ta juridiction avant usage.

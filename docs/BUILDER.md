# Programme Builder Polymarket

## Ce que le code fait, et ce qu'il ne peut pas faire

Ce dépôt implémente **entièrement** le côté technique de l'attribution
builder : la construction du `BuilderConfig`, la signature des en-têtes
builder sur chaque requête authentifiée, et la lecture de l'endpoint
`GET /builder/trades` qui liste les trades attribués à ton compte.

Ce que le code ne peut pas faire, c'est **te délivrer des credentials
builder**. Ils sont émis par Polymarket, pas générés localement. Aucune
bibliothèque, ce projet compris, ne peut les fabriquer : ce sont des
identifiants côté serveur qui n'existent qu'après acceptation d'une
candidature. Il faut donc passer par eux.

## Comment vérifier ton statut actuel

```bash
python main.py builder
```

Sortie sans credentials :

```
Mode builder   : non configuré
Configuré      : non
Actif (SDK)    : non
```

`Actif (SDK)` est le champ qui compte : c'est le SDK lui-même qui valide la
configuration via `can_builder_auth()`. Un triplet mal formé ressort à `non`,
ce qui évite de croire l'attribution active alors qu'elle ne l'est pas.

## Le piège de `BUILDER_CODE`

Le `.env` d'origine de ce projet contenait :

```
BUILDER_CODE=0x8200166e...(tronque)
```

Cette variable **n'a jamais rien fait**. Elle était lue par le code puis
jamais transmise au SDK — et de toute façon, `py_builder_signing_sdk`
n'accepte pas de « code » : son `BuilderConfig` attend soit un triplet
key/secret/passphrase, soit l'URL d'un signeur distant. Une chaîne hex n'a
aucun point d'entrée dans cette API.

Conséquence : si tu croyais toucher des revenus builder via cette variable,
ce n'était pas le cas. Le moteur émet désormais un avertissement explicite
quand `BUILDER_CODE` est défini sans credentials réelles, plutôt que de rester
muet.

## Candidater au programme

Le programme builder rémunère ceux qui apportent du volume à Polymarket via
leurs propres interfaces, bots ou intégrations. Les modalités, les taux et
les critères d'accès évoluent — vérifie les conditions à jour avant de t'y
fier.

**Points d'entrée officiels :**

- Documentation développeur : <https://docs.polymarket.com>
- Discord Polymarket, canal développeurs — c'est là que les intégrateurs
  obtiennent le plus vite une réponse humaine
- Contact direct : `developers@polymarket.com` (à recouper avec la doc, les
  adresses changent)

**Ce qu'une candidature demande en général.** Ne pars pas d'une page blanche :
avoir déjà quelque chose qui tourne pèse beaucoup plus qu'une intention.

1. **Une intégration fonctionnelle.** Ce dépôt te donne la base — client
   CLOB, lecture des marchés, analyse de carnet. Construis dessus quelque
   chose de démontrable.
2. **Du volume, ou une audience crédible.** Le programme rémunère l'apport
   de flux. Sans trafic ni volume à montrer, la candidature a peu d'arguments.
3. **Une description claire de l'intégration** : ce que tu construis, pour
   qui, et quel volume tu anticipes.
4. **Une adresse de wallet** pour recevoir l'attribution.

**Une remarque de fond.** Tu es sur un réseau où Polymarket est filtré au
niveau DNS — le blocage réglementaire français. Ça a deux conséquences
concrètes : tu ne peux pas tester ton intégration en conditions réelles
depuis cette machine, et une candidature depuis une juridiction où la
plateforme est bloquée soulèvera probablement une question côté Polymarket.
Autant l'anticiper que le découvrir en cours de route.

## Configurer les credentials, une fois obtenus

Dans `.env` (jamais committé, cf. [SECURITY.md](../SECURITY.md)) :

```bash
BUILDER_API_KEY=...
BUILDER_API_SECRET=...
BUILDER_API_PASSPHRASE=...
```

Vérification :

```bash
python main.py builder            # doit afficher « Actif (SDK) : oui »
python main.py builder --trades   # trades attribués
```

### Variante : signeur distant

Pour ne pas exposer les credentials builder aux machines d'exécution — un bot
sur un VPS, par exemple — le SDK accepte un service de signature distant :

```bash
BUILDER_REMOTE_URL=https://ton-signeur.example
BUILDER_REMOTE_TOKEN=...
```

Les deux modes sont **mutuellement exclusifs** : renseigner les deux lève une
`ConfigError` au démarrage plutôt que de laisser le SDK choisir en silence.

## Sécurité des credentials builder

Ces credentials donnent accès à ton attribution, donc à des revenus. Les
mêmes règles que pour la clé privée s'appliquent :

- jamais dans un fichier suivi par git — `.gitignore` couvre `.env`
- jamais dans un log : `ApiCredentials` enveloppe secret et passphrase dans
  `Secret`, dont le `repr` est masqué, et un test le verrouille
  (`test_secrets_masques_dans_repr`)
- en production, préfère le signeur distant ou un gestionnaire de secrets
  (Vault, AWS Secrets Manager) à un `.env` sur disque

Le hook pre-commit gitleaks bloque un push contenant ces valeurs. Installe-le :

```bash
pre-commit install
```

## Référence technique

| Élément | Emplacement |
|---|---|
| Traduction vers `BuilderConfig` du SDK | [`src/client.py`](../src/client.py) — `_to_builder_config` |
| Validation de la configuration | [`src/config.py`](../src/config.py) — `BuilderConfiguration` |
| Statut d'activation | `PolymarketEngine.builder_enabled` |
| Trades attribués | `PolymarketEngine.get_builder_trades()` |
| Tests | [`tests/test_builder.py`](../tests/test_builder.py) |

Endpoint sous-jacent : `GET /builder/trades`, avec les en-têtes builder
ajoutés aux en-têtes L2 par `enrich_l2_headers_with_builder_headers`.

# Sécurité

## Signaler une vulnérabilité

N'ouvre pas d'issue publique. Utilise l'onglet **Security → Report a vulnerability**
(GitHub Private Vulnerability Reporting) du dépôt.

---

## Incident : clé privée exposée (24 août 2026)

### Ce qui s'est passé

Le commit initial `452ecaf` a été poussé sur un dépôt **public** avec un
`.gitignore` vide. Le fichier `.env`, contenant `POLYGON_PRIVATE_KEY` en clair,
a donc été committé puis publié. Il était servi par
`raw.githubusercontent.com` en HTTP 200 pendant environ 24 heures.

Wallet concerné : `***PURGED***`

L'ensemble du répertoire `.venv/` (~2 500 fichiers, dont des binaires `.so`
compilés pour macOS) était également suivi par git.

### Ce qu'il faut retenir

Un dépôt public est scanné en continu par des bots qui cherchent
précisément ce motif. Le délai entre un push et la première exploitation se
mesure en secondes ou minutes, pas en heures. **Une clé poussée sur un dépôt
public doit être considérée comme perdue au moment du push**, indépendamment
de ce qui est fait ensuite.

### Corrections appliquées

| Correction | Fichier |
|---|---|
| `.gitignore` couvrant secrets, venvs, caches | `.gitignore` |
| `.env` et `.venv/` retirés du suivi git | — |
| Secrets enveloppés dans `Secret` non-imprimable | `src/config.py` |
| Validation du format de la clé avant usage | `src/config.py` |
| Coupe-circuit trading, désactivé par défaut | `src/client.py` |
| Scan de secrets bloquant en CI (gitleaks) | `.github/workflows/ci.yml` |
| Règle gitleaks sur mesure pour clés EVM 64-hex | `.gitleaks.toml` |
| Hooks pre-commit (gitleaks + detect-private-key) | `.pre-commit-config.yaml` |
| Tests de non-régression sécurité | `tests/test_security.py` |

---

## Purger un secret de l'historique git

### La question la plus fréquente : est-ce que supprimer le fichier suffit ?

**Non.** `git rm .env && git commit` crée un *nouveau* commit où le fichier
est absent. Le contenu reste intégralement présent dans tous les commits
antérieurs, et `git log -p -- .env` le ressort en une commande. Sur GitHub,
le blob reste par ailleurs accessible :

* par son SHA, via `https://github.com/<org>/<repo>/blob/<sha>/.env` ;
* dans les commits « dangling » conservés après un force-push ;
* dans les forks — un fork n'est **jamais** modifié par ton force-push ;
* dans les caches et les vues de pull requests ;
* dans les archives tierces qui ont déjà cloné le dépôt.

### Ordre des opérations

**1. Faire tourner le secret. En premier, et sans attendre.**

C'est la seule étape qui protège réellement quelque chose. Tout le reste est
du nettoyage cosmétique. Pour un wallet : transférer les fonds vers un
nouveau wallet dont la clé n'a jamais touché un fichier suivi par git, puis
révoquer les approbations de contrats de l'ancienne adresse (`revoke.cash`).

**2. Réécrire l'historique.**

Si le secret est dans le dernier commit et qu'il n'y en a qu'un :

```bash
git rm --cached .env
git commit --amend --no-edit
```

Sur un historique plus profond, avec [git-filter-repo](https://github.com/newren/git-filter-repo) :

```bash
git bundle create ../backup.bundle --all      # toujours sauvegarder d'abord
git filter-repo --invert-paths --path .env --force
```

**3. Force-push, en incluant les tags.**

```bash
git push --force-with-lease origin main
git push --force origin --tags
```

`--force-with-lease` refuse d'écraser un travail distant que tu n'as pas vu,
contrairement à `--force` sec.

**4. Demander la purge à GitHub.**

Les commits orphelins restent atteignables par leur SHA jusqu'au garbage
collector de GitHub, qui n'est pas déclenchable par l'utilisateur. Ouvrir un
ticket sur https://support.github.com/ en demandant explicitement le GC des
références non atteignables.

**5. Traiter les forks un par un.**

Un force-push ne les touche pas. Chaque fork conserve une copie complète du
secret et doit être supprimé par son propriétaire.

---

## Bonnes pratiques du projet

**Wallet dédié.** N'utilise jamais un wallet principal pour du trading
automatisé. Alimente un wallet dédié au strict nécessaire : le montant qui
s'y trouve est le plafond de ce que tu peux perdre sur une fuite de clé.

**Le coupe-circuit.** `POLY_ENABLE_TRADING=false` est le défaut. Aucun ordre
ne peut partir sans passage explicite à `true`. Ne le laisse pas à `true` en
permanence.

**Installer les hooks.** Le scan CI attrape un secret *après* le push, quand
il est déjà trop tard. Seul le hook local l'attrape avant :

```bash
pre-commit install
```

**Vérifier avant de pousser.** `git diff --cached` avant chaque commit :
c'est le contenu exact qui partira.

## Réglages GitHub recommandés

Dans **Settings → Code security** :

* Secret scanning + **Push protection** (bloque le push d'un secret détecté)
* Dependabot alerts + security updates
* Private vulnerability reporting

Dans **Settings → Branches**, une règle de protection sur `main` :

* exiger une pull request et le passage des checks (`secrets`, `lint`, `test`)
* interdire les force-push, sauf pendant une purge d'historique planifiée

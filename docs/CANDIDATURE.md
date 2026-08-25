# Candidature au programme builder — trame de travail

## À lire avant d'envoyer quoi que ce soit

Personne ne peut te garantir une acceptation, et ce document non plus. Le
programme builder rémunère l'apport de volume : la décision se prend sur ce
que tu apportes, pas sur la qualité de ta candidature. Un beau dossier sans
trafic derrière ne compense pas l'absence de trafic.

Deux règles qui font la différence entre une candidature crédible et une
candidature écartée :

**N'invente aucun chiffre.** Un volume, un nombre d'utilisateurs ou un
historique inventé se vérifie en une requête on-chain — ton adresse de wallet
est dans le dossier. Se faire prendre sur un chiffre gonflé ferme la porte
définitivement, alors qu'un « je démarre, voici ce que j'ai construit » reste
recevable.

**Ne cache pas la juridiction.** Polymarket est bloqué en France depuis la
décision de l'ANJ. Ils le savent, et ils verront d'où tu écris. Le mentionner
toi-même te fait passer pour quelqu'un qui connaît le terrain ; le taire et
te faire poser la question te met en position défensive. C'est le point le
plus délicat de ta candidature — traite-le de front.

## Ce qui te manque aujourd'hui, honnêtement

| Critère | État | Ce qu'il faut faire |
|---|---|---|
| Intégration technique | **fait** — CLOB, Gamma, analyse de carnet, front, 143 tests | rien |
| Volume apporté | **zéro** | c'est le point bloquant |
| Utilisateurs | **aucun** | trouve une audience, même petite |
| Historique on-chain | **nonce 0**, wallet jamais utilisé | fais tourner quelques trades réels |
| Juridiction | **bloquée** | à traiter explicitement |

Le tableau dit l'essentiel : côté technique tu es prêt, côté volume tu partais
de zéro. Candidater maintenant, c'est demander une part de revenus sur un flux
qui n'existe pas encore. Deux stratégies possibles.

**Option A — candidater maintenant, en assumant le stade.** Tu présentes
l'outil, tu dis que tu démarres, tu demandes les credentials pour instrumenter
ton intégration. Ça peut marcher : certains programmes acceptent tôt pour
capter les intégrateurs prometteurs. Risque : un refus poli, et une seconde
candidature est toujours plus dure à faire passer que la première.

**Option B — construire d'abord, candidater ensuite.** Tu fais tourner
l'outil, tu accumules quelques semaines de volume réel, même modeste, et tu
candidates avec des chiffres vérifiables. Plus lent, nettement plus solide.

Je recommande B si tu peux attendre. Le seul argument pour A, c'est que les
credentials te donnent accès à `/builder/trades`, donc à l'instrumentation de
ton propre flux — utile, mais pas indispensable pour démarrer.

## Trame de message

À adapter — un message manifestement recopié se repère. Les `[...]` sont à
remplir avec des faits, pas des estimations optimistes.

> Objet : Demande d'accès au programme builder — [nom de ton projet]
>
> Bonjour,
>
> Je développe [nom], un outil d'analyse et d'exécution sur Polymarket écrit
> en Python au-dessus de `py-clob-client`. Le dépôt est public :
> https://github.com/SolarPoly/Polymarket
>
> Ce qui est en place aujourd'hui :
> - lecture des marchés via Gamma et du carnet via le CLOB ;
> - analyse de carnet : spread normalisé en points de base, profondeur,
>   déséquilibre de liquidité, simulation de slippage, détection d'écarts
>   YES + NO ≠ 1 ;
> - interface web de consultation ;
> - [143] tests automatisés, CI avec scan de secrets et audit de dépendances.
>
> Ce que je cherche à faire : [décris l'usage réel — bot d'arbitrage,
> interface pour une communauté, outil d'analyse pour X personnes. Sois
> précis, c'est ce qui distingue un projet d'une intention].
>
> État actuel en toute transparence : [volume réel, utilisateurs réels, ou
> « je démarre, aucun volume à ce jour »]. Je travaille depuis la France, où
> la plateforme est bloquée par l'ANJ — [explique comment tu comptes opérer :
> audience hors France, structure ailleurs, ou usage strictement technique].
> Je préfère le dire d'emblée plutôt que vous laisser le découvrir.
>
> Adresse pour l'attribution : [ta NOUVELLE adresse, pas celle du wallet
> compromis].
>
> Je suis disponible pour une démonstration ou toute question technique.
>
> [Ton nom] — [contact]

## Où l'envoyer

- **Discord Polymarket, canal développeurs** — le plus efficace : réponse
  humaine, et tu peux montrer l'outil en direct
- **Documentation développeur** : <https://docs.polymarket.com> — vérifie s'il
  existe un formulaire dédié, plus fiable qu'un email générique
- **Email** : recoupe l'adresse actuelle depuis la doc, elles changent

Commence par le Discord. Un dossier envoyé par email tombe dans une file ;
une conversation dans le canal développeurs te donne un interlocuteur.

## Avant d'envoyer — vérifications

- [ ] La clé compromise est retirée du service et une nouvelle est en place
- [ ] L'adresse fournie est la **nouvelle**, jamais `0x571b…`
- [ ] `python main.py check` tourne sans erreur de configuration
- [ ] Le dépôt est propre : pas de secret, README à jour, CI verte
- [ ] Tous les chiffres du message sont vérifiables
- [ ] La question de la juridiction est traitée explicitement

## Après acceptation

Les credentials arrivent sous forme de triplet key/secret/passphrase. La
configuration et les règles de sécurité qui s'y appliquent sont dans
[BUILDER.md](BUILDER.md). Vérification immédiate :

```bash
python main.py builder     # doit afficher « Actif (SDK) : oui »
```

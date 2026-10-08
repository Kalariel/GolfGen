# Calibration des tailles de terrain (routeur Muirfield)

> Rounds R3 et R3b (2026-10-08). Données : `tools/muirfield/output/calib_phase1/`,
> `calib_phase2/` (`summary.md`, `summary.json`) et `r3b_etape0/`. Commandes :
> `.venv/bin/python -m tools.muirfield.run_muirfield --round calib|calib2`
> (`--calib-summary-only` pour reconstruire une synthèse sans relancer).

## 1. Objectif

Proposer des bornes de taille (largeur × hauteur, en blocs) que l'utilisateur
pourra paramétrer. Critère de lecture (il ne filtre rien) : toutes les seeds
réussies pour chaque patron et chaque orientation, 0 violation, temps de routage
HORS relief sous un seuil.

## 2. Phase 1 : grille large

6 seeds (1–6), petit côté {240, 260, 280, 300, 325, 350} × grand côté
{400, 450, 500}, 2 orientations (portrait, paysage), 2 patrons (`muirfield`,
`muirfield_inverse`), soit 72 combinaisons et 432 runs. Seuil initial :
p90 ≤ 10 s, max ≤ 30 s.

Verdict par taille (portrait / paysage, patrons poolés, réussites sur 12) :

| petit \ grand | 400 | 450 | 500 |
|---|---|---|---|
| 240 | KO 0/12 / KO 0/12 | KO 4/12 / KO 5/12 | KO 8/12 / KO 6/12 |
| 260 | KO 3/12 / KO 3/12 | KO 10/12 / KO 9/12 | KO temps / OK |
| 280 | KO 10/12 / KO 11/12 | KO temps / OK | OK / OK |
| 300 | KO temps / OK | OK / OK | OK / OK |
| 325 | OK / OK | OK / OK | OK / OK |
| 350 | OK / OK | OK / OK | OK / OK |

« KO temps » : 12/12 réussites, mais le p90 dépasse 10 s (300×400 portrait :
p90 de 11,6 s pour `muirfield_inverse`). La zone OK forme un **escalier**, pas
un rectangle : un grand côté plus long compense un petit côté plus court.

## 3. Décisions de l'utilisateur (2026-10-08)

- Bornes proposées : petit côté **[300, 350]** × grand côté **[400, 500]**, dans
  les deux orientations.
- Seuil de temps révisé EXPLICITEMENT par l'utilisateur : **p90 ≤ 15 s et
  max ≤ 30 s** hors relief. Le seuil de 10 s excluait 300×400, déjà validé.
- Maximum 350×500 pour des raisons esthétiques : un parcours doit rester compact.
- Les mesures ont été faites sur le PC perso de l'utilisateur, sous charge de
  bureau (load de 1 à 4,5). La marge sur les temps est acceptée en conséquence.

## 4. Phase 2 : coins et centre des bornes

30 seeds (1–30) aux 4 coins (300×400, 300×500, 350×400, 350×500) et au centre
(325×450), 2 orientations, 2 patrons, soit 600 runs.

- **597/600 réussites, 0 violation**, temps OK partout. Pire p90 : 12,0 s
  (300×400 portrait, `muirfield_inverse`) ; pire max : 29,0 s (400×300).
- Les 3 échecs :

| taille | patron | seed | tentatives |
|---|---|---|---|
| 500×300 | `muirfield_inverse` | 9 | 27 `echec_ancrages` sur 3 clubhouses |
| 350×400 | `muirfield_inverse` | 29 | 27 `echec_ancrages` sur 3 clubhouses |
| 450×325 | `muirfield` | 28 | 26 `echec_ancrages` sur 3 clubhouses ; un 4e clubhouse sort en `infaisable_ancrage` |

  Cause commune : toutes les tentatives `echec_ancrages` sont tronquées par k=3.
  Le dernier ancrage du nine intérieur ne trouve pas de place.

## 5. R3b « placement du clubhouse », étape 0 : NÉGATIF

L'idée testée : choisir le clubhouse selon un score de place libre autour de
lui. Le mécanisme a été abandonné avant toute ligne de code dans le routeur.

- Le score ne sépare pas assez les clubhouses qui réussissent de ceux qui
  échouent (164 contre 123) : AUC de 0,63 pour min(T, G), 0,72 pour la somme
  T + G et 0,57 pour la variante nine intérieur.
- Sur les 114 seeds rattrapées (le 1er clubhouse échoue, un suivant réussit),
  prendre l'argmax du score (somme) au premier essai donne 78 réussites. L'ordre
  actuel réussit dès le 2e clubhouse dans 103 cas.
- Cause de fond : dans 37 des 300 couples (seed, taille), le MÊME clubhouse
  réussit avec un patron et échoue avec l'autre. La limite vient donc de la
  recherche des ancrages (k=3), pas du placement.
- La règle « grands côtés seulement » n'est pas justifiée : 49 % des clubhouses
  en échec sont sur un petit côté (61/124), contre 56 % des clubhouses qui
  réussissent (92/164).
- Données : `tools/muirfield/output/r3b_etape0/` (`etape0_summary.json` pour
  les statistiques, `etape0_argmax.json` pour le choix par seed,
  `etape0_rows.json` pour une ligne par clubhouse).

## 6. Pistes ouvertes

- **(a)** Accepter environ 0,5 % de refus aux bornes. Le refus est propre, avec
  le message « essayez une autre seed ».
- **(b) Recommandée pour le round R5.** Avec le patron `random` (valeur par
  défaut), si un patron échoue, essayer automatiquement l'autre. Pour les
  3 échecs, l'autre patron réussit : on obtiendrait 600/600 sans relever de
  budget. **À valider par l'utilisateur.**
- **(c)** Un jour, une recherche des ancrages plus robuste. Toucher k aux
  positions d'ancrage revient à relever un budget : c'est une décision de
  l'utilisateur.
- **(d)** Des bornes « en escalier », pour jouer sur les deux dimensions en
  même temps (souhait de l'utilisateur).

## 7. Statut

Les bornes ne sont PAS figées dans le code. La décision entre (a) et (b) revient
à l'utilisateur ; leur intégration est prévue au round R5.

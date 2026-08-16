# Revue de la carte OpenFC et du guide d'assemblage

Ce document répond à une question simple : **le guide décrit-il la carte qui est
réellement dans le dépôt ?** Tout ce qui suit est tiré du modèle KiCad exporté,
pas d'une supposition sur ce qu'une carte de vol contient d'habitude.

## D'où viennent les chiffres

Le visualiseur charge deux fichiers glTF (`fc-board.glb`, `fc-parts.glb`) dont la
conversion depuis STEP a **effacé tous les repères** : les 288 solides s'appellent
`empty_2` … `empty_289`. C'est la cause directe du problème d'origine — sans
repères, l'ancien code découpait la liste des maillages en sept tranches
arbitraires et « installait » donc des pièces au hasard à chaque étape.

Les repères existent toujours dans l'export STEP d'origine, supprimé du dépôt
mais présent dans l'historique git :

```sh
git cat-file -p d2745990bb7a16241ded8e6f10334ca7f610735f > OpenFC-composants.step
git cat-file -p 8e2cb7b62ae23709e0e3d8af9c7b7d7048556ab7 > OpenFC-board.step
python3 tools/build-parts-map.py OpenFC-composants.step OpenFC-board.step
```

`tools/build-parts-map.py` en extrait les 111 composants placés (repère,
empreinte, position, face) et les réassocie aux 288 solides du glTF. Le résultat
est `assets/openfc-visualizer/parts-map.json`, que le guide consomme.

## Ce qu'est réellement cette carte

| | |
|---|---|
| Contour | 37,94 × 37,94 mm |
| Épaisseur | 0,938 mm |
| Fixation | 4 trous **Ø4,0 mm**, entraxe **30,5 × 30,5 mm** |
| Composants placés | **111** — 39 face avant, 72 face arrière |

Le format de fixation 30,5 × 30,5 avec des trous de Ø4 est le standard des
drones 5 pouces et plus, avec silentblocs M3. C'est l'information la plus
identifiante de la carte, et elle est vérifiée géométriquement.

### Les composants qui portent une fonction

| Repère | Empreinte | Face | Rôle |
|---|---|---|---|
| U2 | QFN-80 10,0 × 10,0 mm, pas 0,40, pavé 3,4 mm | avant | Microcontrôleur. Le boîtier correspond exactement au RP2350B / **RP2354B** |
| U9 | LGA-14 3,0 × 2,5 mm pas 0,50 | avant | Centrale inertielle. Boîtier du **BMI270** |
| X1 | Quartz 4 plots 2,5 × 2,0 mm | arrière | Référence de temps, montée **sous** U2 |
| L1 | Bobine 2,0 × 1,6 mm (3,3 µH) | avant | Alimentation du cœur — le RP2350 a un convertisseur interne qui exige cette bobine |
| U6, U16 | SOT-23-6 2,9 × 1,6 mm | arrière | Deux abaisseurs à découpage |
| L2, L3 | Bobines blindées 3,0 × 3,0 × 2,0 mm | arrière | Les bobines des deux abaisseurs |
| U7, U15 | WSON-6 2 × 2 mm | arr. / av. | Régulateurs linéaires. U15 est collé à U9 |
| U1 | Contact SMD 4 broches | avant | Bouton BOOT |
| U5, D2, D3 | SOT-583-8, SOD-882 ×2 | arrière | Protection des lignes d'E/S |
| U10, U11, U12, D8 | X2SON-6, SOT-23-5, X2SON-4, DFN0603 | arrière | Étage analogique de service |
| Q1, Q2 | DFN-3L 1,0 × 0,6 mm | av. / arr. | Transistors |
| D1, D4, D5, D7, D9 | LED 0402 | avant | Témoins, chacune avec sa résistance série |
| Card1 | TF-SMD push-push, 15,2 × 16,2 mm | arrière | Lecteur microSD |
| USB1 | USB-C 16 contacts | arrière | Programmation et alimentation |
| P1 / U14, U8 / CN1 / U13 | JST-SH 1,00 mm — 8P / 6P ×2 / 4P / 3P | arrière | Connectique |

Les 84 résistances et condensateurs restants (0201, 0402, 0603, 0805) sont
rattachés, dans le guide, au composant contre lequel ils sont posés — ce qui est
aussi la règle qu'a suivie le routage.

## Corrections apportées au guide

### 1. Deux étapes décrivaient des composants absents

L'ancien guide comportait une étape **« Video/OSD — OSD Chip »** et une étape
**« Radio — ExpressLRS »**. Ni l'une ni l'autre ne correspond à quoi que ce soit
sur la carte : la nomenclature ne contient aucun circuit d'incrustation vidéo
(type AT7456E / MAX7456) et aucun émetteur-récepteur radio. Les seuls circuits de
plus de 3 mm sont U2 et U9.

Sur une carte à base de RP2350, l'OSD se fait **en logiciel** dans le
microcontrôleur, et le récepteur ExpressLRS est un **module externe** qui se
branche sur un des ports JST-SH. Ces deux étapes ont été remplacées par ce que la
carte contient vraiment.

### 2. Manquent aussi, et le guide le dit maintenant

Ni baromètre, ni capteur de courant : aucune empreinte de la nomenclature ne
correspond. C'est une information utile pour qui va câbler la carte.

### 3. L'ordre des étapes

Le nouvel ordre suit la mise en route d'une carte plutôt que le hasard :
alimentations → microcontrôleur et son support → horloge → capteur → interface
humaine → connectique. L'étape finale précise explicitement que ce découpage est
**pédagogique** : en production, une carte se fabrique par face (pochoir, pose,
refusion), pas fonction par fonction.

## Corrections apportées au visualiseur

| Problème signalé | Cause | Correction |
|---|---|---|
| On ne sait pas quelle pièce est installée | Les maillages étaient découpés en 7 tranches arbitraires, sans rapport avec les composants | Chaque étape allume les maillages des composants réellement concernés, via `parts-map.json` |
| Surlignage illisible | Toutes les pièces étaient affichées en permanence (`o.visible = true` forcé) | Trois états : posé, en cours de pose (surligné + contour + étiquette), pas encore posé (masqué) |
| La carte ne tourne pas quand les composants sont sur l'autre face | Aucune logique de face | Chaque étape calcule la répartition avant/arrière et retourne la carte automatiquement ; l'indicateur de face l'affiche |
| « Retourner » fait disparaître la carte | La rotation s'appliquait à un groupe dont l'origine avait été décalée par `ROOT.position.sub(centre)` : la carte décrivait un arc autour d'un point situé hors d'elle-même | Séparation en deux groupes — un pivot placé au centre géométrique du PCB, et un enfant qui porte le recentrage et l'échelle. La carte tourne sur elle-même |
| Pièces peu réalistes | Les matériaux sortis de KiCad sont plats (`metalness 0`, `roughness 1`) | Blindages, cages et contacts passent en métal ; les boîtiers en résine sortent du noir pur ; le stratifié passe en rendu à facettes, ses normales lissées faisant onduler une surface plane |

Un mode **Rayons X** rend le PCB translucide, et s'active de lui-même quand une
étape concerne réellement les deux faces.

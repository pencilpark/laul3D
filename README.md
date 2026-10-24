# Photos vers impression 3D

App locale : on glisse des photos dans le navigateur et on récupère un STL étanche, dimensionné pour la Creality Ender-3 V3 (plateau 220 × 220 × 250 mm), en LowPoly ou en version détaillée. Tout le calcul tourne sur le Mac. Seul le premier lancement de la voie IA télécharge des poids de modèle depuis Hugging Face.

## Lancer

Double-cliquer sur `start.command`. Le navigateur s'ouvre sur http://127.0.0.1:8642.

En terminal : `./start.command`. Ctrl+C arrête le serveur.

Le port 8765 est déjà pris sur ce Mac par un `python -m http.server`, d'où le 8642. Les ports 9876 et 9877 restent réservés à MCP for Blender et à l'extension MCP de Blender Lab.

## Deux moteurs gratuits

La photogrammétrie Apple Object Capture (`~/.local/bin/HelloPhotogrammetry`) prend la main dès 20 photos. C'est la voie fidèle : la forme vient des photos, rien n'est inventé. Pour un buste, il faut 50 photos ou plus.

L'IA TripoSR (Stability AI et Tripo, licence MIT) sert de 1 à 19 photos. Elle n'utilise que la photo principale, détourée automatiquement par rembg. L'arrière de l'objet est deviné, donc la ressemblance reste approximative. Elle tourne en local sur le GPU du Mac (MPS), avec repli CPU.

Le mode Auto choisit selon le nombre de photos. On peut forcer l'un ou l'autre dans l'interface.

Moteurs écartés :
- Hunyuan3D. La licence Tencent Hunyuan 3D n'accorde aucun droit dans l'UE, au Royaume-Uni ni en Corée du Sud (section 1.l, "Territory"), même pour un usage privé.
- TRELLIS. Le portage Mac recommande 24 Go de mémoire unifiée ou plus, ce Mac en a 16.
- Tripo, Rodin, Meshy et Hunyuan via MCP for Blender. Ils sont payants ou réservés au Premium.

## Pipeline LowPoly vers détaillé

Chaque projet s'affine en trois niveaux. Les reconstructions déjà faites restent en cache.

| Niveau | Object Capture | Triangles visés | Voxel d'étanchéité | Usage |
|---|---|---|---|---|
| LowPoly | `-d preview` | 200 à 5 000 (1 000 par défaut) | taille / 300 | valider forme et orientation en quelques secondes, rendu facetté |
| Moyen | `-d medium` | environ 20 000 | taille / 400 | impression courante |
| Détaillé | `-d full` | jusqu'à 300 000 | taille / 650 | qualité maximale, plus long |

Le voxel est toujours borné entre 0,2 et 0,5 mm. Méthode conseillée : lancer en LowPoly, corriger l'orientation avec les boutons X, Y et Z, puis cliquer sur Générer pour Moyen ou Détaillé.

## Ce que fait la préparation (Blender headless)

`engine/blender_lowpoly.py` est lancé avec `--factory-startup`, donc sans les add-ons de l'utilisateur. Ainsi aucun second serveur MCP ne démarre sur le port 9876.

1. Import USDZ, OBJ, GLB, PLY ou STL, fusion en un objet, rotation demandée, mise à l'échelle en mm.
2. Étanchéité : trous bouchés, puis remaillage voxel. Si le scan fuit trop, l'app bascule sur une fermeture morphologique (dilatation en Geometry Nodes, coque extérieure, rétraction).
3. Une seule coque gardée par défaut, pour retirer les débris. L'option "Garder les pièces détachées" conserve les morceaux de plus de 2 %.
4. Décimation au nombre de triangles du niveau. Si des auto-intersections apparaissent, la cible remonte de 40 % et l'app relance, jusqu'à 3 fois.
5. Socle plat : coupe du bas (3 % par défaut) et fermeture de la section.
6. Contrôles : arêtes non-manifold, auto-intersections, coques, parois plus fines que 2 × la buse, surplombs à plus de 45°, volume.
7. Export STL en mm, vérifié en relisant le nombre de triangles écrit. Le pipeline produit aussi un `.blend` en mm et 4 aperçus PNG.

## Bien photographier

Sujet immobile, lumière égale sans flash, tour complet avec environ 70 % de recouvrement entre deux photos voisines, deux ou trois hauteurs, sujet entier dans chaque cadre. HEIC d'iPhone ou JPG. Les photos floues sont écartées automatiquement (netteté sous 35 % de la médiane).

Les photos d'iPhone donnent un modèle debout (Z en haut). D'autres appareils peuvent donner un modèle couché : les boutons d'orientation corrigent cela en quelques secondes.

## Imprimer

Bouton "Ouvrir dans OrcaSlicer", puis :
- profil Creality Ender-3 V3 ;
- supports arborescents si le rapport signale plus de 5 % de surplombs (menton, nez, oreilles) ;
- socle à plat sur le plateau.

## Dossiers

- `projects/<date>-<nom>/photos` : photos reçues.
- `projects/<date>-<nom>/work` : reconstructions en cache (`scan_preview.usdz`, `scan_full.usdz`, `triposr.obj`).
- `projects/<date>-<nom>/export/<niveau>` : STL, `.blend`, rapport JSON, aperçus.
- `engine/` : préparation Blender, orchestrateur, inférence TripoSR.
- `vendor/TripoSR` : code TripoSR (MIT). `torchmcubes` est remplacé par le marching cubes de scikit-image, ce qui évite une compilation.

## Ligne de commande

```sh
B=/Applications/Blender.app/Contents/MacOS/Blender
$B -b --factory-startup --python-exit-code 1 -P engine/blender_lowpoly.py -- \
  --input scan.usdz --outdir sortie --name buste --level lowpoly --height-mm 80 --previews
.venv/bin/python engine/triposr_infer.py photo.jpg sortie/brut.obj
```

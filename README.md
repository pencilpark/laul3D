# Berria Craft

Application de bureau pour Mac et Windows : on glisse des photos et on récupère un STL étanche, dimensionné pour la Creality Ender-3 V3 (plateau 220 × 220 × 250 mm), en LowPoly ou en version détaillée. Elle s'ouvre dans sa propre fenêtre, sans navigateur. Tout le calcul tourne sur l'ordinateur ; seuls les outils et le module IA se téléchargent, une fois, depuis leurs sites officiels.

## Installer

Les installeurs sont dans la release GitHub de chaque version (onglet Releases du dépôt), où GitHub remplace l'espace du nom par un point (`Berria.Craft_…`).

Mac (puce Apple, macOS 14 Sonoma ou plus récent) : ouvrir `Berria Craft_0.4.0_aarch64.dmg`, glisser Berria Craft dans Applications. L'app n'est pas notarisée : construite sur ce Mac, elle s'ouvre directement ; copiée sur un autre Mac, il faut l'autoriser une fois dans Réglages Système > Confidentialité et sécurité > « Ouvrir quand même ».

Windows 10 ou 11, 64 bits : lancer `Berria Craft_0.4.0_x64-setup.exe`. L'installeur n'est pas signé : SmartScreen demande une fois « Informations complémentaires » puis « Exécuter quand même ». L'installation se fait pour l'utilisateur courant, sans droits d'administrateur.

Au premier lancement, l'app prépare son environnement de calcul (une minute au plus), puis propose dans une fenêtre les outils qui manquent : Blender (obligatoire), OrcaSlicer, et sous Windows la photogrammétrie COLMAP + OpenMVS. Le module « Une photo (IA) » s'installe à part, depuis l'en-tête. Sous Windows, COLMAP, OpenMVS et l'IA demandent les composants Microsoft Visual C++ : Windows demande alors une autorisation.

## Moteurs gratuits

Plusieurs photos (20 et plus, 50 pour un buste fidèle) : la forme vient des photos, rien n'est inventé.
- Mac : Apple Object Capture, via l'outil `HelloPhotogrammetry` fourni avec l'app.
- Windows : COLMAP 4.2.1 place les photos, OpenMVS 2.4.0 construit le maillage et sa texture, sur le processeur. Le nivellement des coutures de TextureMesh est désactivé : en 2.4.0, il noircit les textures (issue OpenMVS #1257). COLMAP extrait les points d'autant de photos à la fois que la mémoire libre le permet (environ 0,8, 1,2 et 3,1 Go par photo en LowPoly, Moyen et Détaillé), au lieu d'une par cœur, pour que le Détaillé ne fasse pas paginer Windows sur 8 Go ; les points trouvés restent les mêmes. COLMAP et OpenMVS tournent en priorité basse. COLMAP travaillant dans un repère arbitraire, l'app redresse le modèle d'après les photos : leur « haut » moyen donne la verticale, la première photo donne la face.

Une photo : l'IA TripoSR (Stability AI et Tripo, licence MIT) estime la forme et les couleurs à partir de la photo principale, détourée par rembg. L'arrière est deviné. Module facultatif d'environ 2,2 Go (4 à 4,7 Go sur un PC avec carte NVIDIA, où torch est pris en version CUDA).

Moteurs écartés :
- Hunyuan3D. La licence Tencent Hunyuan 3D n'accorde aucun droit dans l'UE, au Royaume-Uni ni en Corée du Sud (section 1.l, « Territory »), même pour un usage privé.
- TRELLIS. Le portage Mac recommande 24 Go de mémoire unifiée ou plus, ce Mac en a 16.
- Tripo, Rodin, Meshy et Hunyuan via MCP for Blender : payants ou réservés au Premium.

## Pipeline LowPoly vers détaillé

Chaque projet s'affine en trois niveaux. Les reconstructions déjà faites restent en cache.

| Niveau | Object Capture | Triangles visés | Voxel d'étanchéité | Usage |
|---|---|---|---|---|
| LowPoly | `-d preview` | 200 à 5 000 (1 000 par défaut) | taille / 300 | valider forme et orientation vite, rendu facetté |
| Moyen | `-d medium` | environ 20 000 | taille / 400 | impression courante |
| Détaillé | `-d full` | jusqu'à 300 000 | taille / 650 | qualité maximale, plus long |

Le voxel est borné entre 0,2 et 0,5 mm. Méthode conseillée : lancer en LowPoly, redresser si besoin avec les quarts de tour, puis générer Moyen ou Détaillé.

Lissage (aucun, léger, moyen, fort) : flou du volume du modèle sur 2 à 4 voxels (environ 0,4 à 0,8 mm pour un buste de 80 mm). Il efface le grain et les petites bosses ; au réglage fort, les détails fins du visage s'adoucissent aussi.

Rendu : la visionneuse s'ouvre en mode Rendu quand le modèle a des couleurs, celles des photos (une couleur par facette en LowPoly) ; le bouton « Solide / Rendu » bascule entre les deux. C'est un aperçu : le STL imprimé reste d'une couleur. Des couleurs inexploitables (noires, texture illisible, faces sans photo) sont écartées et le Journal technique en donne la raison.

## Ce que fait la préparation (Blender headless)

`engine/blender_lowpoly.py` est lancé avec `--factory-startup`, donc sans les add-ons de l'utilisateur : aucun second serveur MCP ne démarre sur le port 9876.

1. Import USDZ, OBJ, GLB, PLY ou STL, fusion en un objet, rotation demandée, mise à l'échelle en mm.
2. Étanchéité : trous bouchés, puis remaillage voxel. Si le scan fuit trop, fermeture morphologique (dilatation en Geometry Nodes, coque extérieure, rétraction).
3. Une seule coque gardée par défaut. L'option « Garder les pièces détachées » conserve les morceaux de plus de 2 %.
4. Lissage éventuel (nœuds SDF d'OpenVDB), puis décimation au nombre de triangles du niveau. Si des auto-intersections apparaissent, la cible remonte de 40 % et l'app relance, jusqu'à 3 fois.
5. Socle plat : coupe du bas (3 % par défaut) et fermeture de la section.
6. Contrôles : arêtes non-manifold, auto-intersections, coques, parois plus fines que 2 × la buse, surplombs à plus de 45°, volume.
7. Couleurs du scan projetées par Cycles sur le maillage final, exportées en GLB d'aperçu, et, selon les cases cochées, en 3MF peint, OBJ en couleurs et OBJ texturé (voir « Imprimer en couleur »).
8. Export STL en mm, vérifié en relisant le nombre de triangles écrit, plus un `.blend` et 4 aperçus PNG.

## Bien photographier

Sujet immobile, lumière égale sans flash, première photo de face, tour complet avec environ 70 % de recouvrement entre deux photos voisines, deux ou trois hauteurs, sujet entier dans chaque cadre. HEIC d'iPhone ou JPG. Les photos floues sont écartées automatiquement (netteté sous 35 % de la médiane).

## Imprimer

Bouton « Préparer l'impression dans OrcaSlicer », puis :
- profil Creality Ender-3 V3 ;
- supports arborescents si le rapport signale des surplombs (menton, nez, oreilles) ;
- socle à plat sur le plateau.

## Imprimer en couleur

Dans Réglages avancés, et dans « Recalculer avec ces réglages » pour un modèle déjà calculé, trois cases choisissent les fichiers couleur calculés en plus du STL. Elles sont cochées par défaut ; décochées, le calcul et les fichiers restent ceux d'avant (STL, `.blend`, aperçu en couleur). Les fichiers n'existent que si les photos donnent des couleurs exploitables.

- 3MF peint, pour une imprimante à plusieurs bobines (l'Ender-3 V3 seule n'en a qu'une). Chaque face porte un numéro de filament (attribut `paint_color` d'OrcaSlicer et Bambu Studio), pas une couleur : dans OrcaSlicer, régler d'abord autant de filaments que la palette, dans le même ordre et aux mêmes couleurs, puis ouvrir le fichier. Ouvert avec moins de filaments, les faces des numéros manquants s'affichent au filament 1 et leur peinture se perd quand on ajoute des filaments ensuite. Fichier > Importer ajoute lui-même les filaments manquants, avec des couleurs à corriger.
- OBJ en couleurs (OBJ et MTL côte à côte, en mm, Z en haut comme le STL), pour la même imprimante. À l'ouverture, OrcaSlicer 2.1 ou plus récent affiche une fenêtre qui ajoute les couleurs de la palette comme nouveaux filaments, après ceux déjà réglés. Les faces gardent exactement leur filament, mais OrcaSlicer recalcule les couleurs : elles peuvent s'écarter de quelques unités des codes affichés, et l'ordre des filaments ajoutés peut différer de celui de la palette. Le `.mtl` doit rester à côté du `.obj` : depuis un zip, OrcaSlicer ne lit que l'OBJ et l'ouvre sans couleur. « Enregistrer l'OBJ en couleurs » copie donc les deux fichiers dans Téléchargements.
- OBJ texturé zippé (OBJ, MTL et PNG, en mm, Z en haut), pour un service d'impression en couleurs réelles (Sculpteo, i.materialise…). La texture fait 2 048 px en LowPoly et 4 096 px en Moyen et Détaillé ; elle ajoute de quelques secondes à une minute au calcul.

Pour les deux premiers, les couleurs des photos sont regroupées en 4 teintes par défaut, de 2 à 8 avec le réglage « Filaments pour l'impression en couleur ». Un îlot de couleur plus petit que (4 × buse)², environ 2,6 mm² avec une buse de 0,4, prend la couleur voisine la plus proche ; deux teintes trop proches (écart Lab inférieur à 12) ne prennent pas deux bobines. La palette s'affiche avec le numéro et le code de chaque couleur.

Les couleurs viennent des photos, ombres et reflets compris.

## Dossiers de l'app installée

Données dans `~/Library/Application Support/com.pencilpark.berriacraft` (Mac) ou `%LOCALAPPDATA%\com.pencilpark.berriacraft` (Windows) :
- `runtime`, `venv` : Python privé de l'app et ses bibliothèques ;
- `data/tools` : Blender, COLMAP, OpenMVS, OrcaSlicer (Windows) installés par l'app ; `data/models` : modèles du module IA ;
- `Projets/<date>-<nom>` : photos reçues, reconstructions en cache, exports par niveau ;
- `logs/serveur.log` : journal du moteur.

Les STL enregistrés vont dans Téléchargements. Un projet se supprime depuis la liste des projets (corbeille, avec confirmation) : son dossier est effacé, sauf pendant un calcul ; les fichiers déjà enregistrés dans Téléchargements restent.

## Construire les installeurs

Mac : `desktop/build_mac.sh` (Rust, Node et uv requis). Il rassemble Python 3.11.14, uv 0.13.5 (SHA-256 vérifié), les roues du socle pour macOS 14 arm64, `HelloPhotogrammetry` et le moteur, puis Tauri produit l'app et le DMG dans `desktop/src-tauri/target/release/bundle/`.

Windows : la CI `windows-installer` construit l'installeur à chaque envoi sur GitHub, l'installe en silence, vérifie le démarrage et l'arrêt du moteur et la fenêtre, puis le publie comme artefact `berria-craft-windows`. Sur une machine Windows : `desktop\build_windows.ps1`.

Publier une version : monter la version dans `desktop/src-tauri/tauri.conf.json` et `Cargo.toml`, écrire `desktop/release-notes.md`, puis lancer à la main la CI `windows-installer` sur `dev` (Actions, windows-installer, Run workflow, case « release » cochée) ou envoyer une étiquette `vX.Y.Z`. La CI crée la release GitHub `vX.Y.Z` avec l'installeur testé, et l'étiquette si elle manque. Le DMG, construit sur un Mac avec `desktop/build_mac.sh`, s'ajoute ensuite à cette release (`gh release upload vX.Y.Z "desktop/src-tauri/target/release/bundle/dmg/Berria Craft_X.Y.Z_aarch64.dmg"`).

Mode développeur, dans un navigateur : `start.command`, puis http://127.0.0.1:8642.

## Ligne de commande

```sh
B=/Applications/Blender.app/Contents/MacOS/Blender
$B -b --factory-startup --python-exit-code 1 -P engine/blender_lowpoly.py -- \
  --input scan.usdz --outdir sortie --name buste --level lowpoly --height-mm 80 --previews --colors --smooth 1
.venv/bin/python engine/triposr_infer.py photo.jpg sortie/brut.obj
```

Tests : `tests/setup_ai_test.py`, `tests/setup_tools_test.py`, `tests/orientation_test.py`, `tests/photogrammetry_win_test.py`, `tests/boot_test.py`, `tests/save_race_test.py`, `tests/delete_project_test.py`, `tests/couleurs_test.py`, `tests/preview_fallback_test.py`, `tests/smoke_test.py`.

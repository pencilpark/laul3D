# Berria Craft

Application de bureau pour Mac et Windows : on glisse des photos et on récupère un STL étanche, dimensionné pour la Creality Ender-3 V3 (plateau 220 × 220 × 250 mm), en LowPoly ou en version détaillée. Elle s'ouvre dans sa propre fenêtre, sans navigateur. Tout le calcul tourne sur l'ordinateur ; seuls les outils et le module IA se téléchargent, une fois, depuis leurs sites officiels.

## Installer

Les installeurs sont dans la release GitHub de chaque version (onglet Releases du dépôt), où GitHub remplace l'espace du nom par un point (`Berria.Craft_…`).

Mac (puce Apple, macOS 14 Sonoma ou plus récent) : ouvrir `Berria Craft_0.5.1_aarch64.dmg`, glisser Berria Craft dans Applications. L'app n'est pas notarisée : construite sur ce Mac, elle s'ouvre directement ; copiée sur un autre Mac, il faut l'autoriser une fois dans Réglages Système > Confidentialité et sécurité > « Ouvrir quand même ».

Windows 10 ou 11, 64 bits : lancer `Berria Craft_0.5.1_x64-setup.exe`. L'installeur n'est pas signé : SmartScreen demande une fois « Informations complémentaires » puis « Exécuter quand même ». L'installation se fait pour l'utilisateur courant, sans droits d'administrateur.

Au premier lancement, l'app prépare son environnement de calcul (une minute au plus), puis propose dans une fenêtre les outils qui manquent : Blender (obligatoire), OrcaSlicer, et sous Windows la photogrammétrie COLMAP + OpenMVS. Le module « Une photo (IA) » s'installe à part, depuis l'en-tête. Sous Windows, COLMAP, OpenMVS et l'IA demandent les composants Microsoft Visual C++ : Windows demande alors une autorisation.

## Moteurs gratuits

Plusieurs photos (20 et plus, 50 pour un buste fidèle) : la forme vient des photos, rien n'est inventé.
- Mac : Apple Object Capture, via l'outil `HelloPhotogrammetry` fourni avec l'app.
- Windows : COLMAP 4.2.1 place les photos, OpenMVS 2.4.0 construit le maillage et sa texture, sur le processeur. Le nivellement des coutures de TextureMesh est désactivé : en 2.4.0, il noircit les textures (issue OpenMVS #1257). COLMAP extrait les points d'autant de photos à la fois que la mémoire libre le permet (environ 0,8, 1,2 et 3,1 Go par photo en résolution Basse, Moyenne et Haute), au lieu d'une par cœur, pour que la résolution Haute ne fasse pas paginer Windows sur 8 Go ; les points trouvés restent les mêmes. COLMAP et OpenMVS tournent en priorité basse. COLMAP travaillant dans un repère arbitraire, l'app redresse le modèle d'après les photos : leur « haut » moyen donne la verticale, la première photo donne la face.

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

### Résolution des photos

Le réglage « Résolution des photos », sous le niveau de détail et dans « Ajuster ce modèle », choisit la taille des photos que la photogrammétrie utilise, indépendamment du niveau. Auto, par défaut, garde le comportement d'avant : Basse pour LowPoly, Moyenne pour Moyen, Haute pour Détaillé. Basse, Moyenne, Haute ou Max s'appliquent à tous les niveaux, qui partagent alors le même scan. Sans effet sur « Une photo (IA) ».

| Résolution | Mac : Object Capture | Windows : COLMAP, puis OpenMVS | Texture du scan (Windows) |
|---|---|---|---|
| Basse | `-d preview` | photos réduites à 1600 px, cartes de profondeur à 800 px | 4096 |
| Moyenne | `-d medium` | 2000 px, puis 1000 px | 4096 |
| Haute | `-d full` | 3200 px, puis 1600 px | 4096 |
| Max | `-d raw` | pleine taille des photos, ajustée à la mémoire libre | 8192 |

Max :
- Mac : le détail `raw` d'Object Capture, que la documentation d'Apple décrit comme produit « at the highest resolution possible from the source images » (jusqu'à 30 millions de triangles et 16 textures 8192). macOS ne dit pas à l'avance si la mémoire suffit : si `raw` échoue, l'app refait le scan en `full` (Haute) et le journal le dit ; le projet ne retente plus `raw` ensuite (fichier `scan_raw.failed` dans son dossier de travail).
- Windows : COLMAP et OpenMVS travaillent sur les photos entières (niveau de résolution 0 d'OpenMVS), texture du scan jusqu'à 8192. Avant le calcul, l'app estime la mémoire de chaque étape pour la taille et le nombre des photos (voir `MEMORY_MODEL` dans `engine/photogrammetry_win.py`) et réduit la taille par pas de 10 % jusqu'à tenir dans la mémoire libre, moins 1,5 Go laissés à Windows. Si la taille retenue ne dépasse pas celle de Haute, le scan se fait en Haute. Le journal donne la taille retenue et la mémoire libre ; les détails techniques du modèle aussi.
- Blender : la texture de l'OBJ texturé et celles du profil Logiciels 3D passent de 4096 à 8192, ou à 6144 si la mémoire libre ne suffit pas à cuire 8192 (environ 150 octets par pixel d'après le code de cuisson de Blender 5, soit 10 Go pour 8192) ; LowPoly garde 2048.
- Le STL imprimable reste plafonné par le niveau (300 000 triangles et voxel d'au moins 0,2 mm en Détaillé) : Max affine d'abord le scan, les couleurs et les textures. Le calcul est nettement plus long.

« Enregistrer le scan brut », dans Autres enregistrements, copie dans Téléchargements le maillage de la photogrammétrie tel qu'il est sorti, avant nettoyage, pour Blender : le `.usdz` d'Object Capture sur Mac, l'OBJ texturé d'OpenMVS zippé avec son MTL et ses textures sous Windows, redressé comme le modèle imprimable et Y vers le haut.

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
9. Si des exports 3D hors impression sont cochés, un second Blender refait l'import, l'étanchéité, le tri des coques et le lissage, sans la décimation ni le socle, et produit les profils (voir « Exports 3D hors impression ») : un profil qui échoue ne touche pas aux fichiers d'impression.

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

## Exports 3D hors impression

Trois cases dans Réglages avancés, et dans « Recalculer avec ces réglages », produisent le modèle nettoyé pour d'autres usages que l'impression. Elles sont décochées par défaut : sans elles, le calcul reste celui d'avant. Chaque profil donne un zip, à la taille réelle en mètres (tirée de la hauteur saisie), base centrée sur l'origine, Y vers le haut dans les GLB et FBX.

- Logiciels 3D (Blender, sculpture, animation) : 20 000 quads environ par QuadriFlow, le remailleur de Blender, textures 4096, fichiers `.blend` (textures à côté, chemins relatifs), FBX et OBJ. Si QuadriFlow refuse le modèle, le profil sort en triangles et le journal le dit. Pour animer un personnage, une retopologie à la main reste utile : QuadriFlow aligne les quads sur la forme, sans tenir compte des articulations.
- Jeux (Unity, Unreal, Godot) : 50 000 triangles et deux niveaux de détail à 50 et 25 %, en GLB et en FBX, couleur en JPEG et normal map en PNG, 2048 px.
- Web (three.js, model-viewer) : un GLB de 50 000 triangles, textures JPEG 2048, environ 1,7 Mo sur le scan de test. Une version compressée Draco s'y ajoute quand le Blender installé contient la bibliothèque Draco, ce qui est le cas du Blender 5.2.3 officiel (vérifié dans la CI Windows) ; le fichier est contrôlé, car l'export de Blender réussit sans elle mais n'écrit alors rien de compressé.

Pour chaque profil : morceaux détachés retirés, surface fermée et lissée comme pour l'impression, puis réduction, dépliage UV (Smart UV Project), couleurs des photos cuites dans une texture et relief du modèle lissé dans une normal map. Sans couleurs exploitables, seule la normal map est livrée. Durées mesurées sur un petit scan de test, processeur à 4 cœurs : 15 s environ pour Web ou Jeux, une minute environ pour Logiciels 3D ; davantage sur un scan détaillé. Ces fichiers portent des noms en anglais (`_software`, `_game`, `_web`).

## Langues

L'app existe en anglais (langue par défaut), français, espagnol, allemand, portugais du Brésil, chinois simplifié et japonais. Au premier lancement, elle prend la langue de l'interface du système, lue par le moteur Python (sous Windows, le navigateur intégré ne la donne pas de façon fiable) ; une langue absente de la liste donne l'anglais, le chinois traditionnel aussi. Le menu en haut à droite change de langue ; le choix est gardé dans `data/prefs.json`. L'installeur Windows s'affiche dans la langue du système parmi les sept.

Les textes sont dans `app/static/i18n/<langue>.json`, partagés par l'interface (`tr()`) et par le moteur (`engine/i18n.py`, clés `srv.`). La page de démarrage en garde une copie : après une modification des clés `splash.`, lancer `python desktop/splash_strings.py`. `tests/i18n_test.py` vérifie que les sept fichiers ont les mêmes clés et les mêmes variables, et que le code n'utilise que des clés existantes. Les messages déjà enregistrés dans un projet (étapes, erreurs, journal) restent dans la langue où ils ont été écrits.

Les fichiers produits ont des noms anglais pour tout le monde depuis la 0.5.0 (`_colors.glb`, `_colors_orca.obj`, `_colors_texture.zip`, vues `_front`, `_right`, `_back`, `_three_quarter`) ; ceux des projets déjà calculés gardent leur nom.

## Dossiers de l'app installée

Données dans `~/Library/Application Support/com.pencilpark.berriacraft` (Mac) ou `%LOCALAPPDATA%\com.pencilpark.berriacraft` (Windows) :
- `runtime`, `venv` : Python privé de l'app et ses bibliothèques ;
- `data/tools` : Blender, COLMAP, OpenMVS, OrcaSlicer (Windows) installés par l'app ; `data/models` : modèles du module IA ;
- `Projects/<date>-<nom>` : photos reçues, reconstructions en cache, exports par niveau (le dossier `Projets` des versions précédentes est renommé au premier lancement de la 0.5.0) ;
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
# mêmes options et --profiles-only software,game,web : les profils d'export seuls
.venv/bin/python engine/cli.py photos/ --niveau medium --resolution max --exports game,web
.venv/bin/python engine/triposr_infer.py photo.jpg sortie/brut.obj
```

Tests : `tests/setup_ai_test.py`, `tests/setup_tools_test.py`, `tests/orientation_test.py`, `tests/photogrammetry_win_test.py`, `tests/boot_test.py`, `tests/save_race_test.py`, `tests/delete_project_test.py`, `tests/couleurs_test.py`, `tests/photo_res_test.py`, `tests/preview_fallback_test.py`, `tests/smoke_test.py` (`--max` : un calcul complet en résolution Max).

# Berria Craft

Application de bureau pour Mac et Windows : on glisse des photos et on récupère un STL étanche, dimensionné pour la Creality Ender-3 V3 (plateau 220 × 220 × 250 mm), en LowPoly ou en version détaillée. Elle s'ouvre dans sa propre fenêtre, sans navigateur. Tout le calcul tourne sur l'ordinateur ; seuls les outils et le module IA se téléchargent, une fois, depuis leurs sites officiels.

## Installer

Mac (puce Apple, macOS 14 Sonoma ou plus récent) : ouvrir `Berria Craft_0.1.0_aarch64.dmg`, glisser Berria Craft dans Applications. L'app n'est pas notarisée : construite sur ce Mac, elle s'ouvre directement ; copiée sur un autre Mac, il faut l'autoriser une fois dans Réglages Système > Confidentialité et sécurité > « Ouvrir quand même ».

Windows 10 ou 11, 64 bits : lancer `Berria Craft_0.1.0_x64-setup.exe`. L'installeur n'est pas signé : SmartScreen demande une fois « Informations complémentaires » puis « Exécuter quand même ». L'installation se fait pour l'utilisateur courant, sans droits d'administrateur.

Au premier lancement, l'app prépare son environnement de calcul (une minute au plus), puis propose dans une fenêtre les outils qui manquent : Blender (obligatoire), OrcaSlicer, et sous Windows la photogrammétrie COLMAP + OpenMVS. Le module « Une photo (IA) » s'installe à part, depuis l'en-tête. Sous Windows, COLMAP, OpenMVS et l'IA demandent les composants Microsoft Visual C++ : Windows demande alors une autorisation.

## Moteurs gratuits

Plusieurs photos (20 et plus, 50 pour un buste fidèle) : la forme vient des photos, rien n'est inventé.
- Mac : Apple Object Capture, via l'outil `HelloPhotogrammetry` fourni avec l'app.
- Windows : COLMAP 4.2.1 place les photos, OpenMVS 2.4.0 construit le maillage et sa texture, sur le processeur. COLMAP travaillant dans un repère arbitraire, l'app redresse le modèle d'après les photos : leur « haut » moyen donne la verticale, la première photo donne la face.

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

Rendu : le bouton « Solide / Rendu » de la visionneuse montre le modèle avec les couleurs des photos (une couleur par facette en LowPoly). C'est un aperçu : le STL imprimé reste d'une couleur.

## Ce que fait la préparation (Blender headless)

`engine/blender_lowpoly.py` est lancé avec `--factory-startup`, donc sans les add-ons de l'utilisateur : aucun second serveur MCP ne démarre sur le port 9876.

1. Import USDZ, OBJ, GLB, PLY ou STL, fusion en un objet, rotation demandée, mise à l'échelle en mm.
2. Étanchéité : trous bouchés, puis remaillage voxel. Si le scan fuit trop, fermeture morphologique (dilatation en Geometry Nodes, coque extérieure, rétraction).
3. Une seule coque gardée par défaut. L'option « Garder les pièces détachées » conserve les morceaux de plus de 2 %.
4. Lissage éventuel (nœuds SDF d'OpenVDB), puis décimation au nombre de triangles du niveau. Si des auto-intersections apparaissent, la cible remonte de 40 % et l'app relance, jusqu'à 3 fois.
5. Socle plat : coupe du bas (3 % par défaut) et fermeture de la section.
6. Contrôles : arêtes non-manifold, auto-intersections, coques, parois plus fines que 2 × la buse, surplombs à plus de 45°, volume.
7. Couleurs du scan projetées par Cycles sur le maillage final, exportées en GLB d'aperçu.
8. Export STL en mm, vérifié en relisant le nombre de triangles écrit, plus un `.blend` et 4 aperçus PNG.

## Bien photographier

Sujet immobile, lumière égale sans flash, première photo de face, tour complet avec environ 70 % de recouvrement entre deux photos voisines, deux ou trois hauteurs, sujet entier dans chaque cadre. HEIC d'iPhone ou JPG. Les photos floues sont écartées automatiquement (netteté sous 35 % de la médiane).

## Imprimer

Bouton « Préparer l'impression dans OrcaSlicer », puis :
- profil Creality Ender-3 V3 ;
- supports arborescents si le rapport signale des surplombs (menton, nez, oreilles) ;
- socle à plat sur le plateau.

## Dossiers de l'app installée

Données dans `~/Library/Application Support/com.pencilpark.berriacraft` (Mac) ou `%LOCALAPPDATA%\com.pencilpark.berriacraft` (Windows) :
- `runtime`, `venv` : Python privé de l'app et ses bibliothèques ;
- `data/tools` : Blender, COLMAP, OpenMVS, OrcaSlicer (Windows) installés par l'app ; `data/models` : modèles du module IA ;
- `Projets/<date>-<nom>` : photos reçues, reconstructions en cache, exports par niveau ;
- `logs/serveur.log` : journal du moteur.

Les STL enregistrés vont dans Téléchargements.

## Construire les installeurs

Mac : `desktop/build_mac.sh` (Rust, Node et uv requis). Il rassemble Python 3.11.14, uv 0.13.5 (SHA-256 vérifié), les roues du socle pour macOS 14 arm64, `HelloPhotogrammetry` et le moteur, puis Tauri produit l'app et le DMG dans `desktop/src-tauri/target/release/bundle/`.

Windows : la CI `windows-installer` construit l'installeur à chaque envoi sur GitHub, l'installe en silence, vérifie le démarrage et l'arrêt du moteur et la fenêtre, puis le publie comme artefact `berria-craft-windows`. Sur une machine Windows : `desktop\build_windows.ps1`.

Mode développeur, dans un navigateur : `start.command`, puis http://127.0.0.1:8642.

## Ligne de commande

```sh
B=/Applications/Blender.app/Contents/MacOS/Blender
$B -b --factory-startup --python-exit-code 1 -P engine/blender_lowpoly.py -- \
  --input scan.usdz --outdir sortie --name buste --level lowpoly --height-mm 80 --previews --colors --smooth 1
.venv/bin/python engine/triposr_infer.py photo.jpg sortie/brut.obj
```

Tests : `tests/setup_ai_test.py`, `tests/setup_tools_test.py`, `tests/orientation_test.py`, `tests/photogrammetry_win_test.py`, `tests/boot_test.py`, `tests/save_race_test.py`, `tests/preview_fallback_test.py`, `tests/smoke_test.py`.

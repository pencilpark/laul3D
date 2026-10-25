## Nouveautés

- Exports 3D hors impression : trois profils au choix, en plus des fichiers d'impression, par des cases dans Réglages avancés et dans « Recalculer avec ces réglages ». Elles sont décochées par défaut : sans elles, rien ne change.
  - Logiciels 3D (Blender, sculpture, animation) : environ 20 000 quads, textures 4096, fichiers .blend, FBX et OBJ.
  - Jeux (Unity, Unreal, Godot) : 50 000 triangles et deux niveaux de détail (50 et 25 %), GLB et FBX, textures 2048.
  - Web (three.js, model-viewer) : un GLB léger de 50 000 triangles, textures JPEG, plus une version compressée Draco quand Blender la produit.
- Chaque profil donne un zip : taille réelle en mètres, Y vers le haut, couleurs des photos et normal map pour le relief fin. Un profil allonge le calcul d'environ 15 s (Web, Jeux) à plus d'une minute (Logiciels 3D) sur un modèle simple.

- Sept langues : anglais (par défaut), français, espagnol, allemand, portugais du Brésil, chinois simplifié et japonais. L'app prend la langue du système au premier lancement ; le menu en haut à droite la change. L'installeur Windows suit la langue du système.
- Les fichiers produits ont désormais des noms anglais (`_colors`, `_front`…) et le dossier des projets s'appelle `Projects` : l'ancien dossier `Projets` est renommé au premier lancement, sans perte.

Rappel de la 0.4.0 : impression en couleur au choix, 3MF peint, OBJ en couleurs pour OrcaSlicer et OBJ texturé pour les services d'impression couleur.

## Installer

- Windows 10 ou 11, 64 bits : `Berria.Craft_0.5.0_x64-setup.exe`. L'installeur n'est pas signé : SmartScreen demande une fois « Informations complémentaires » puis « Exécuter quand même ». La mise à jour garde les projets ; un modèle déjà calculé obtient ses exports en cochant les profils puis « Recalculer avec ces réglages ».
- Mac (puce Apple, macOS 14 ou plus récent) : `Berria.Craft_0.5.0_aarch64.dmg`, ajouté à cette release une fois construit sur un Mac. L'app n'est pas notarisée : au premier lancement, l'autoriser dans Réglages Système > Confidentialité et sécurité > « Ouvrir quand même ».

## Nouveautés

- Résolution des photos, au choix : un réglage sous le niveau de détail, et dans « Ajuster ce modèle », choisit la taille des photos que la photogrammétrie utilise, indépendamment du niveau. Auto, par défaut, garde le comportement d'avant (Basse pour LowPoly, Moyenne pour Moyen, Haute pour Détaillé) ; Basse, Moyenne, Haute et Max s'imposent à tous les niveaux.
- Max garde la pleine résolution des photos autant que la mémoire libre le permet : Object Capture en détail raw sur Mac, photos entières pour COLMAP et OpenMVS sous Windows, textures 8192 pour l'OBJ texturé et le profil Logiciels 3D. Le scan et les textures gagnent en finesse ; le calcul est nettement plus long. Quand la mémoire ne suffit pas, l'app descend d'elle-même et le journal technique dit à quelle résolution. Le STL imprimable reste limité par le niveau de détail (300 000 triangles en Détaillé).
- Nouveau bouton « Enregistrer le scan brut » : le maillage complet de la photogrammétrie, avant nettoyage, à ouvrir dans Blender (.usdz sur Mac, OBJ texturé zippé sous Windows).

Rappel de la 0.5.0 : exports 3D hors impression (Logiciels 3D, Jeux, Web) et sept langues.

## Installer

- Windows 10 ou 11, 64 bits : `Berria.Craft_0.5.1_x64-setup.exe`. L'installeur n'est pas signé : SmartScreen demande une fois « Informations complémentaires » puis « Exécuter quand même ». La mise à jour garde les projets et leurs scans ; un modèle déjà calculé passe en Max en choisissant Max dans « Ajuster ce modèle », puis « Recalculer avec ces réglages ».
- Mac (puce Apple, macOS 14 ou plus récent) : `Berria.Craft_0.5.1_aarch64.dmg`, ajouté à cette release une fois construit sur un Mac. L'app n'est pas notarisée : au premier lancement, l'autoriser dans Réglages Système > Confidentialité et sécurité > « Ouvrir quand même ».

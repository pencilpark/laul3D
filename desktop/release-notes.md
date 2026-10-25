## Nouveautés

- Impression en couleur : trois fichiers au choix, en plus du STL, quand le modèle a des couleurs. Trois cases dans Réglages avancés et dans « Recalculer avec ces réglages », cochées par défaut ; seuls les fichiers cochés sont calculés, et tout décocher garde le calcul d'avant.
  - 3MF peint, pour une imprimante à plusieurs bobines : les couleurs des photos regroupées en 4 teintes par défaut (de 2 à 8, réglage « Filaments pour l'impression en couleur »), une par face. OrcaSlicer reçoit les numéros de filament, pas les couleurs : régler avant d'ouvrir autant de filaments que la palette, dans le même ordre et aux mêmes couleurs.
  - OBJ en couleurs, pour la même imprimante : à l'ouverture, OrcaSlicer 2.1 ou plus récent propose les couleurs de la palette comme nouveaux filaments, à quelques unités près. L'OBJ et son MTL sont enregistrés côte à côte.
  - OBJ texturé zippé (OBJ, MTL, PNG, en mm), pour un service d'impression en couleurs réelles comme Sculpteo ou i.materialise.
- Les îlots trop petits pour être imprimés en couleur prennent la couleur voisine la plus proche, et deux teintes presque identiques ne prennent pas deux bobines. La palette s'affiche avec le numéro et le code de chaque couleur.
- L'Ender-3 V3 seule reste une imprimante à une couleur : le 3MF peint et l'OBJ en couleurs demandent une imprimante à plusieurs bobines.

Rappel de la 0.3.0 : sous Windows, la photogrammétrie limite l'extraction des points à la mémoire libre et tourne en priorité basse.

## Installer

- Windows 10 ou 11, 64 bits : `Berria.Craft_0.4.0_x64-setup.exe`. L'installeur n'est pas signé : SmartScreen demande une fois « Informations complémentaires » puis « Exécuter quand même ». La mise à jour garde les projets ; un modèle déjà calculé obtient ses fichiers couleur avec « Recalculer avec ces réglages ».
- Mac (puce Apple, macOS 14 ou plus récent) : `Berria.Craft_0.4.0_aarch64.dmg`, ajouté à cette release une fois construit sur un Mac. L'app n'est pas notarisée : au premier lancement, l'autoriser dans Réglages Système > Confidentialité et sécurité > « Ouvrir quand même ».

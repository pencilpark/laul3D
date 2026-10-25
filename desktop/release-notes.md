## Nouveautés

- Windows : la photogrammétrie ne bloque plus un PC de 8 Go en niveau Détaillé. COLMAP extrayait les points de toutes les photos en même temps, une par cœur du processeur, chacune agrandie deux fois (environ 2,5 Go par photo en Détaillé). L'app limite désormais ce nombre à ce que la mémoire libre permet. Les points trouvés sont les mêmes ; seule cette étape peut durer plus longtemps sur un PC qui manque de mémoire. Le Journal technique indique combien de photos sont traitées à la fois.
- Windows : COLMAP et OpenMVS tournent en priorité basse. L'ordinateur reste utilisable pendant le calcul, et le calcul va aussi vite quand on ne s'en sert pas.

Rappel de la 0.2.0 : couleurs des modèles « Plusieurs photos » corrigées sous Windows, aperçu Rendu par défaut, suppression d'un projet depuis la liste.

## Installer

- Windows 10 ou 11, 64 bits : `Berria.Craft_0.3.0_x64-setup.exe`. L'installeur n'est pas signé : SmartScreen demande une fois « Informations complémentaires » puis « Exécuter quand même ». La mise à jour garde les projets.
- Mac (puce Apple, macOS 14 ou plus récent) : `Berria.Craft_0.3.0_aarch64.dmg`, ajouté à cette release une fois construit sur un Mac. L'app n'est pas notarisée : au premier lancement, l'autoriser dans Réglages Système > Confidentialité et sécurité > « Ouvrir quand même ».

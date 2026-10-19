# Smart Task

Smart Task est un gestionnaire Windows de macros clavier et souris. Il enregistre une séquence d'actions, la sauvegarde en preset JSON et permet de la rejouer à une vitesse et un nombre de répétitions choisis.

## Utilisation sans code

Vous n'avez pas besoin de programmer vos macros. Dans l'application, choisissez **Rec**, effectuez les actions voulues, puis arrêtez l'enregistrement. Smart Task sauvegarde automatiquement la séquence dans `smart_task_presets/`. Sélectionnez ensuite le preset pour le rejouer ou ajoutez plusieurs presets dans Sandbox pour les enchaîner.

Le JSON est un format ouvert destiné aux personnes qui souhaitent inspecter ou modifier manuellement les événements. Cette étape est facultative.

## Fonctions

- Enregistrement des frappes, clics et déplacements de souris.
- Relecture avec réglage de vitesse et répétitions.
- Enchaînement et réordonnancement de plusieurs presets.
- Presets conservés sous forme de fichiers JSON lisibles.

## Exécution depuis les sources

Nécessite Python 3 et `pynput` pour l'enregistrement et la relecture. Pillow est facultatif et sert au chargement de logo PNG dans l'interface.

```powershell
py -m pip install pynput pillow
py bot.py
```

Sans `pynput`, l'interface peut démarrer, mais l'enregistrement et la relecture sont désactivés.

## Sécurité

Une macro rejoue des entrées clavier et souris dans l'application au premier plan. Inspectez les presets dont vous ne connaissez pas l'origine et vérifiez la fenêtre active avant d'exécuter une séquence. Utilisez le bouton **Stop** dans Smart Task pour arrêter la relecture.

## Licence

Ce projet est distribué sous licence MIT. Consultez le fichier [LICENSE](LICENSE).

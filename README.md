# APK Builder All-in-One

Un seul `.exe` Windows : il télécharge et installe tout seul **JDK 17**, **Android SDK** et **Gradle**
(dans `%LOCALAPPDATA%\APKBuilder\tools`), puis compile votre projet Android en **APK**.
Aucun prérequis à installer.

## Obtenir le .exe via GitHub
1. Créez un dépôt GitHub et poussez ces fichiers.
2. Onglet **Actions** > *Build APK Builder (.exe)* (démarre au push, ou **Run workflow**).
3. Téléchargez `APKBuilder.exe` dans les **Artifacts**.
4. Release publique : `git tag v1.0 && git push origin v1.0`.

## Utilisation
1. Lancez `APKBuilder.exe`.
2. Choisissez un dossier de projet Android, importez un `.zip`, ou cliquez sur **✚ Nouveau (Hello World)**
   pour créer un projet d'exemple prêt à compiler (Java, sans dépendance, package `com.example.myapp`).
3. Cliquez **Compiler l'APK**. Au premier lancement, les outils sont téléchargés (~1-2 Go, connexion requise).
4. Release : l'APK est signé automatiquement (keystore généré, mot de passe `android`).
   Pour publier sur le Play Store, utilisez votre propre keystore.

## Notes
- Le projet doit être un projet Gradle Android (avec `settings.gradle`). `gradlew.bat` est utilisé s'il existe,
  sinon Gradle 8.7 téléchargé.
- En acceptant l'installation, vous acceptez les licences Android SDK.

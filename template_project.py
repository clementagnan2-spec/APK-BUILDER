"""Modèle de projet Android « Hello World » (Java, sans dépendance externe).
Compatible avec AGP 8.5.2 + Gradle 8.7 + JDK 17 + SDK 34 (ceux installés par APK Builder)."""
import re
from pathlib import Path

PACKAGE = "com.example.myapp"

FILES = {
    "settings.gradle": """pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "__NAME__"
include ':app'
""",
    "build.gradle": """plugins {
    id 'com.android.application' version '8.5.2' apply false
}
""",
    "gradle.properties": """org.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8
android.nonTransitiveRClass=true
""",
    ".gitignore": """build/
.gradle/
local.properties
*.apk
""",
    "app/build.gradle": """plugins {
    id 'com.android.application'
}

android {
    namespace '__PKG__'
    compileSdk 34

    defaultConfig {
        applicationId "__PKG__"
        minSdk 24
        targetSdk 34
        versionCode 1
        versionName "1.0"
    }

    buildTypes {
        release {
            minifyEnabled false
        }
    }

    compileOptions {
        sourceCompatibility JavaVersion.VERSION_17
        targetCompatibility JavaVersion.VERSION_17
    }
}
""",
    "app/src/main/AndroidManifest.xml": """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <application
        android:label="@string/app_name"
        android:theme="@android:style/Theme.Material.Light.DarkActionBar">
        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>

</manifest>
""",
    "app/src/main/res/values/strings.xml": """<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">__NAME__</string>
    <string name="hello">Bonjour depuis __NAME__ !</string>
    <string name="button_label">Cliquez-moi</string>
</resources>
""",
    "app/src/main/java/com/example/myapp/MainActivity.java": """package __PKG__;

import android.app.Activity;
import android.os.Bundle;
import android.view.Gravity;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

public class MainActivity extends Activity {
    private int count = 0;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setPadding(48, 48, 48, 48);

        TextView title = new TextView(this);
        title.setText(R.string.hello);
        title.setTextSize(24);
        title.setGravity(Gravity.CENTER);

        TextView counter = new TextView(this);
        counter.setText("Clics : 0");
        counter.setTextSize(18);
        counter.setPadding(0, 32, 0, 32);

        Button button = new Button(this);
        button.setText(R.string.button_label);
        button.setOnClickListener(v -> {
            count++;
            counter.setText("Clics : " + count);
        });

        root.addView(title);
        root.addView(counter);
        root.addView(button);
        setContentView(root);
    }
}
""",
}


def clean_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9 _-]", "", name or "").strip()
    return name or "HelloWorld"


def create_project(parent: Path, name: str) -> Path:
    """Crée le projet dans parent/<nom> (suffixe numérique si déjà existant). Retourne le dossier."""
    name = clean_name(name)
    folder = re.sub(r"\s+", "_", name)
    dest = Path(parent) / folder
    i = 2
    while dest.exists():
        dest = Path(parent) / f"{folder}_{i}"
        i += 1
    for rel, content in FILES.items():
        f = dest / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content.replace("__PKG__", PACKAGE).replace("__NAME__", name),
                     encoding="utf-8", newline="\n")
    return dest

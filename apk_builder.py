"""APK Builder All-in-One
Télécharge et installe automatiquement JDK 17, Android SDK et Gradle,
puis compile un projet Android en APK (avec signature automatique en Release)."""
import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import urllib.request
import zipfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import template_project

APP_NAME = "APK Builder All-in-One"
BASE = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "APKBuilder"
TOOLS = BASE / "tools"
PROJECTS = BASE / "projects"
JDK_DIR = TOOLS / "jdk17"
SDK_DIR = TOOLS / "android-sdk"
GRADLE_DIR = TOOLS / "gradle"
KEYSTORE = TOOLS / "apkbuilder.keystore"
CONFIG_FILE = BASE / "config.json"

JDK_URL = "https://api.adoptium.net/v3/binary/latest/17/ga/windows/x64/jdk/hotspot/normal/eclipse"
CMDLINE_URL = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
GRADLE_URL = "https://services.gradle.org/distributions/gradle-8.7-bin.zip"
SDK_PACKAGES = ["platform-tools", "platforms;android-34", "build-tools;34.0.0"]

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Cancelled(Exception):
    pass


# ---------- helpers ----------
def has_jdk():
    return (JDK_DIR / "bin" / "java.exe").exists()


def sdkmanager():
    return SDK_DIR / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat"


def has_sdk():
    return sdkmanager().exists() and (SDK_DIR / "platform-tools").exists() \
        and (SDK_DIR / "build-tools").exists()


def has_gradle():
    return (GRADLE_DIR / "bin" / "gradle.bat").exists()


def find_project_root(base):
    base = Path(base)
    for root, dirs, files in os.walk(base):
        if len(Path(root).relative_to(base).parts) > 3:
            dirs[:] = []
            continue
        if "settings.gradle" in files or "settings.gradle.kts" in files:
            return Path(root)
    return None


def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg):
    try:
        BASE.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("840x640")
        self.minsize(720, 520)
        self.cfg = load_config()
        self.proc = None
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self._pmode = None

        self.project = tk.StringVar(value=self.cfg.get("project", ""))
        self.variant = tk.StringVar(value=self.cfg.get("variant", "Debug"))
        self.autosign = tk.BooleanVar(value=self.cfg.get("autosign", True))
        self.status = tk.StringVar(value="Prêt.")
        self.tools_var = tk.StringVar()

        self._build_ui()
        self.refresh_tools()
        self.after(100, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}
        ttk.Label(self, text="APK Builder — tout-en-un", font=("Segoe UI", 14, "bold")
                  ).pack(anchor="w", padx=12, pady=(10, 0))
        ttk.Label(self, text="JDK, Android SDK et Gradle sont installés automatiquement.",
                  foreground="#555").pack(anchor="w", padx=12)

        tf = ttk.LabelFrame(self, text="Outils")
        tf.pack(fill="x", padx=10, pady=8)
        ttk.Label(tf, textvariable=self.tools_var).pack(side="left", padx=8, pady=6)
        self.btn_setup = ttk.Button(tf, text="⚙ Installer / réparer les outils",
                                    command=lambda: self.start("setup"))
        self.btn_setup.pack(side="right", padx=8, pady=6)

        frm = ttk.Frame(self)
        frm.pack(fill="x", padx=10)
        frm.columnconfigure(1, weight=1)
        ttk.Label(frm, text="Projet Android :").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.project).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Dossier…", command=self.browse).grid(row=0, column=2, **pad)
        ttk.Button(frm, text="Importer ZIP…", command=self.import_zip).grid(row=0, column=3, **pad)
        ttk.Button(frm, text="✚ Nouveau (Hello World)", command=self.new_project).grid(row=0, column=4, **pad)
        ttk.Label(frm, text="Type de build :").grid(row=1, column=0, sticky="w", **pad)
        opt = ttk.Frame(frm)
        opt.grid(row=1, column=1, columnspan=4, sticky="w")
        ttk.Combobox(opt, textvariable=self.variant, values=["Debug", "Release"],
                     state="readonly", width=10).pack(side="left", padx=8)
        ttk.Checkbutton(opt, text="Signer automatiquement l'APK Release",
                        variable=self.autosign).pack(side="left", padx=8)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(8, 0))
        self.btn_build = ttk.Button(bar, text="▶ Compiler l'APK", command=lambda: self.start("build"))
        self.btn_build.pack(side="left", padx=4)
        self.btn_clean = ttk.Button(bar, text="Nettoyer", command=lambda: self.start("clean"))
        self.btn_clean.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(bar, text="■ Arrêter", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        ttk.Button(bar, text="Ouvrir le dossier APK", command=self.open_apk_dir).pack(side="right", padx=4)

        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(fill="x", padx=14, pady=6)

        logf = ttk.Frame(self)
        logf.pack(fill="both", expand=True, padx=10, pady=4)
        self.log = tk.Text(logf, wrap="none", bg="#1e1e1e", fg="#d4d4d4",
                           insertbackground="white", font=("Consolas", 9))
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", padx=12, pady=(2, 8))

    def refresh_tools(self):
        m = lambda ok: "✔" if ok else "✘"
        self.tools_var.set(f"JDK 17 {m(has_jdk())}    Android SDK {m(has_sdk())}    Gradle {m(has_gradle())}")

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.project.get() or str(Path.home()))
        if d:
            self.project.set(d)

    def import_zip(self):
        f = filedialog.askopenfilename(filetypes=[("Projet Android (.zip)", "*.zip")])
        if not f:
            return
        dest = PROJECTS / Path(f).stem
        try:
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            with zipfile.ZipFile(f) as z:
                z.extractall(dest)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Impossible d'extraire le ZIP : {e}")
            return
        root = find_project_root(dest)
        if root:
            self.project.set(str(root))
            self._write(f"[info] Projet importé : {root}\n")
        else:
            messagebox.showerror(APP_NAME, "Aucun projet Gradle (settings.gradle) trouvé dans ce ZIP.")

    def new_project(self):
        name = simpledialog.askstring(APP_NAME, "Nom du nouveau projet :", initialvalue="HelloWorld",
                                      parent=self)
        if name is None:
            return
        try:
            dest = template_project.create_project(PROJECTS, name)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Impossible de créer le projet : {e}")
            return
        self.project.set(str(dest))
        self._write(f"[info] Projet « Hello World » créé : {dest}\n")
        self.status.set("Projet créé. Cliquez sur « Compiler l'APK ».")

    def _write(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_progress(self, pct):
        if pct is None:
            if self._pmode != "i":
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
                self._pmode = "i"
        else:
            if self._pmode != "d":
                self.progress.stop()
                self.progress.configure(mode="determinate")
                self._pmode = "d"
            self.progress["value"] = pct

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._write(payload)
                elif kind == "pct":
                    self._set_progress(payload)
                elif kind == "status":
                    self.status.set(payload)
                elif kind == "refresh":
                    self.refresh_tools()
                elif kind == "done":
                    self._finished(*payload)
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _set_busy(self, busy):
        self.busy = busy
        st = "disabled" if busy else "normal"
        for b in (self.btn_build, self.btn_clean, self.btn_setup):
            b.configure(state=st)
        self.btn_stop.configure(state="normal" if busy else "disabled")

    # ---------- lancement ----------
    def start(self, action):
        if self.busy:
            return
        proj = Path(self.project.get().strip() or ".")
        if action in ("build", "clean"):
            if not self.project.get().strip() or not find_project_root(proj) == proj:
                messagebox.showerror(APP_NAME, "Sélectionnez un dossier de projet Android valide "
                                     "(contenant settings.gradle) ou importez un ZIP.")
                return
        if action in ("build", "setup") and not (has_jdk() and has_sdk()):
            if not messagebox.askokcancel(
                    APP_NAME,
                    "Les outils manquants vont être téléchargés (environ 1 à 2 Go) :\n"
                    "• JDK 17 (Eclipse Temurin)\n• Android SDK (Google)\n• Gradle\n\n"
                    "En continuant, vous acceptez les licences de l'Android SDK "
                    "(developer.android.com/studio/terms)."):
                return
        self.cfg.update(project=self.project.get(), variant=self.variant.get(),
                        autosign=self.autosign.get())
        save_config(self.cfg)
        self.cancel.clear()
        self._set_busy(True)
        self._set_progress(None)
        self.status.set("Travail en cours…")
        threading.Thread(target=self._pipeline, args=(action, proj), daemon=True).start()

    def stop(self):
        self.cancel.set()
        if self.proc and self.proc.poll() is None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                           creationflags=NO_WINDOW, capture_output=True)
        self.msg("\n[arrêt demandé]\n")

    def _on_close(self):
        self.cancel.set()
        if self.proc and self.proc.poll() is None:
            self.stop()
        self.destroy()

    # ---------- travail (thread) ----------
    def msg(self, text):
        self.q.put(("log", text))

    def _env(self):
        env = os.environ.copy()
        env["JAVA_HOME"] = str(JDK_DIR)
        env["PATH"] = str(JDK_DIR / "bin") + os.pathsep + env.get("PATH", "")
        env["ANDROID_HOME"] = env["ANDROID_SDK_ROOT"] = str(SDK_DIR)
        return env

    def run_cmd(self, cmd, cwd=None, input_text=None):
        self.proc = subprocess.Popen(
            cmd, cwd=cwd, env=self._env(), shell=isinstance(cmd, str),
            stdin=subprocess.PIPE if input_text else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        if input_text:
            try:
                self.proc.stdin.write(input_text)
                self.proc.stdin.close()
            except OSError:
                pass
        for line in self.proc.stdout:
            if line.lstrip().startswith("[") and "%" in line:
                continue  # barres de progression sdkmanager
            self.msg(line)
        code = self.proc.wait()
        if self.cancel.is_set():
            raise Cancelled()
        return code

    def download(self, url, dest, label):
        self.msg(f"Téléchargement : {label}…\n")
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "APKBuilder/1.0"})
        last = -1
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if self.cancel.is_set():
                    raise Cancelled()
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = int(done * 100 / total)
                    if pct != last:
                        last = pct
                        self.q.put(("pct", pct))
                        self.q.put(("status", f"{label} : {pct} %  ({done >> 20}/{total >> 20} Mo)"))
        self.q.put(("pct", None))

    def extract_flat(self, zip_path, dest):
        self.q.put(("status", "Extraction…"))
        tmp = Path(tempfile.mkdtemp(dir=TOOLS))
        try:
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(tmp)
            items = list(tmp.iterdir())
            src = items[0] if len(items) == 1 and items[0].is_dir() else tmp
            if dest.exists():
                shutil.rmtree(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def install_zip(self, url, label, dest):
        z = TOOLS / (label.replace(" ", "_") + ".zip")
        self.download(url, z, label)
        self.extract_flat(z, dest)
        z.unlink(missing_ok=True)
        self.q.put(("refresh", None))

    def ensure_tools(self, need_gradle):
        TOOLS.mkdir(parents=True, exist_ok=True)
        if not has_jdk():
            self.install_zip(JDK_URL, "JDK 17", JDK_DIR)
        if not sdkmanager().exists():
            self.install_zip(CMDLINE_URL, "Android command-line tools",
                             SDK_DIR / "cmdline-tools" / "latest")
        if not has_sdk():
            sm = sdkmanager()
            self.q.put(("status", "Acceptation des licences Android…"))
            self.run_cmd(f'"{sm}" --sdk_root="{SDK_DIR}" --licenses', input_text="y\n" * 60)
            self.q.put(("status", "Installation des composants Android SDK…"))
            pkgs = " ".join(f'"{p}"' for p in SDK_PACKAGES)
            code = self.run_cmd(f'"{sm}" --sdk_root="{SDK_DIR}" {pkgs}')
            if code != 0:
                raise RuntimeError("L'installation de l'Android SDK a échoué.")
            self.q.put(("refresh", None))
        if need_gradle and not has_gradle():
            self.install_zip(GRADLE_URL, "Gradle 8.7", GRADLE_DIR)

    def write_local_properties(self, proj):
        lp = proj / "local.properties"
        lines = []
        if lp.exists():
            lines = [l for l in lp.read_text(encoding="utf-8", errors="ignore").splitlines()
                     if not l.startswith("sdk.dir")]
        sdk = str(SDK_DIR).replace("\\", "\\\\").replace(":", "\\:")
        lines.append(f"sdk.dir={sdk}")
        lp.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def sign_release(self, proj):
        bts = sorted((SDK_DIR / "build-tools").glob("*"))
        apksigner = bts[-1] / "apksigner.bat" if bts else None
        if not apksigner or not apksigner.exists():
            self.msg("[avertissement] apksigner introuvable, APK non signé.\n")
            return
        if not KEYSTORE.exists():
            self.msg("Création d'un keystore de signature…\n")
            self.run_cmd([str(JDK_DIR / "bin" / "keytool.exe"), "-genkeypair", "-keystore",
                          str(KEYSTORE), "-alias", "apkbuilder", "-keyalg", "RSA",
                          "-keysize", "2048", "-validity", "10000", "-storepass", "android",
                          "-keypass", "android", "-dname", "CN=APK Builder"])
        for apk in proj.rglob("build/outputs/apk/release/*-unsigned.apk"):
            out = apk.with_name(apk.name.replace("-unsigned", "-signed"))
            self.msg(f"Signature de {apk.name}…\n")
            self.run_cmd([str(apksigner), "sign", "--ks", str(KEYSTORE), "--ks-pass", "pass:android",
                          "--key-pass", "pass:android", "--out", str(out), str(apk)])

    def _pipeline(self, action, proj):
        code = 0
        try:
            wrapper = proj / "gradlew.bat"
            self.ensure_tools(need_gradle=(action != "setup" and not wrapper.exists()))
            if action != "setup":
                self.write_local_properties(proj)
                gradle = str(wrapper) if wrapper.exists() else str(GRADLE_DIR / "bin" / "gradle.bat")
                task = "clean" if action == "clean" else f"assemble{self.variant.get()}"
                self.msg(f"\n=== {Path(gradle).name} {task} ===\n")
                self.q.put(("status", f"Exécution de {task}…"))
                self.q.put(("pct", None))
                code = self.run_cmd([gradle, task, "--console=plain", "--no-daemon"], cwd=proj)
                if code == 0 and action == "build" and self.variant.get() == "Release" \
                        and self.autosign.get():
                    self.sign_release(proj)
        except Cancelled:
            code = -2
        except Exception as e:
            self.msg(f"\nErreur : {e}\n")
            code = -1
        self.q.put(("done", (code, action)))

    # ---------- fin ----------
    def _finished(self, code, action):
        self.progress.stop()
        self._pmode = None
        self.progress.configure(mode="determinate", value=0)
        self._set_busy(False)
        self.refresh_tools()
        if code == -2:
            self.status.set("Annulé.")
        elif code != 0:
            self.status.set(f"Échec (code {code}). Voir le journal.")
        elif action == "build":
            apks = self.find_apks()
            if apks:
                self.status.set(f"Succès : {apks[0].name}")
                self._write("\n✔ APK généré(s) :\n" + "\n".join(f"  {a}" for a in apks) + "\n")
                if messagebox.askyesno(APP_NAME, "Compilation réussie. Ouvrir le dossier de l'APK ?"):
                    self.open_apk_dir()
            else:
                self.status.set("Terminé (aucun APK trouvé).")
        else:
            self.status.set("Terminé avec succès.")

    def find_apks(self):
        proj = Path(self.project.get().strip())
        found = list(proj.rglob("build/outputs/apk/**/*.apk"))
        return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)

    def open_apk_dir(self):
        apks = self.find_apks() if self.project.get().strip() else []
        target = apks[0].parent if apks else Path(self.project.get().strip() or BASE)
        if target.exists():
            os.startfile(str(target))


if __name__ == "__main__":
    App().mainloop()

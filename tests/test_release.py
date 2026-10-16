import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = tempfile.TemporaryDirectory(prefix="glyph-tests-")
os.environ.update(XDG_DATA_HOME=str(Path(SANDBOX.name) / "data"),
                  XDG_CONFIG_HOME=str(Path(SANDBOX.name) / "config"),
                  GLYPH_DICTIONARY_DIR=str(Path(SANDBOX.name) / "dicts"),
                  QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="generic")
sys.path.insert(0, str(ROOT / "app"))
import database
import hotkeys
from text_format import sentence_start, standard_word


class CoreTests(unittest.TestCase):
    def setUp(self):
        database.initialize()
        with database.connect() as db:
            db.execute("DELETE FROM words"); db.execute("DELETE FROM collections")
            db.execute("DELETE FROM settings WHERE key='current_collection'")

    def test_capture_and_batch_preserve_reviews(self):
        for value in ("STRAIN", "Strain", "strain"): database.capture(value, value)
        row = database.list_words()[0]
        self.assertEqual((row["display"], row["encounter_count"]), ("strain", 3))
        database.review_word(row["id"], 2)
        sat = database.add_collection("SAT"); reading = database.add_collection("Reading")
        database.assign_words_to_collection([row["id"], row["id"]], sat)
        database.assign_words_to_collection([row["id"]], reading)
        self.assertEqual(database.word_collection_ids(row["id"]), {sat, reading})
        database.assign_words_to_collection([row["id"]], 0)
        self.assertEqual(database.word_collection_ids(row["id"]), set())
        self.assertEqual(database.review_state(row["id"])["rating"], 2)
        self.assertEqual(database.list_words()[0]["encounter_count"], 3)

    def test_format_and_manual_override(self):
        self.assertEqual(standard_word("TAKE   INTO ACCOUNT"), "take into account")
        self.assertEqual(sentence_start("the NASA mission"), "The NASA mission")
        database.capture("STRAIN", "strain")
        word_id = database.list_words()[0]["id"]
        database.rename_word(word_id, "Strain", "strain")
        database.capture("strain", "strain")
        self.assertEqual(database.list_words()[0]["display"], "Strain")

    def test_old_sense_reviews_do_not_override_whole_word_due(self):
        database.capture("strain", "strain"); word_id = database.list_words()[0]["id"]
        database.review_word(word_id, 3, "obsolete-sense")
        self.assertEqual(len(database.list_words(due_only=True)), 1)


class HotkeyTests(unittest.TestCase):
    def prepare(self):
        manager = hotkeys.Hotkeys(); manager.config.parent.mkdir(parents=True, exist_ok=True)
        root_config = manager.config.parent / "test-root.kdl"
        root_config.write_text(f"include {hotkeys.kdl_string(manager.bindings)}\n")
        manager.bindings.write_text(hotkeys.idle_config())
        manager.config.write_text(json.dumps({"backend": "niri", "config": str(root_config)}))
        return manager

    def test_shortcuts_registered_and_released(self):
        manager = self.prepare()
        try:
            with patch("hotkeys.shutil.which", return_value="niri"), patch("hotkeys.subprocess.run", return_value=SimpleNamespace(returncode=0)):
                self.assertTrue(manager.configure("Alt+E", "Alt+Shift+E", "Alt+R"))
            text = manager.bindings.read_text()
            self.assertIn('"--action" "capture"', text)
            self.assertIn('"--action" "ocr"', text)
            self.assertIn("open-floating true", text)
            self.assertFalse(hotkeys.valid_keys(["E", "Alt+E", "Alt+R"]))
            self.assertFalse(hotkeys.valid_keys(["Alt+E"] * 3))
        finally: manager.close()
        self.assertNotIn('"--action"', manager.bindings.read_text())

    def test_failed_validation_restores_previous_file(self):
        manager = self.prepare(); original = manager.bindings.read_text()
        with patch("hotkeys.shutil.which", return_value="niri"), patch("hotkeys.subprocess.run", return_value=SimpleNamespace(returncode=1)):
            self.assertFalse(manager.configure("Alt+E", "Alt+Shift+E", "Alt+R"))
        self.assertEqual(manager.bindings.read_text(), original)
        manager.close()

    def test_appimage_uses_persistent_image_path(self):
        with patch.dict(os.environ, GLYPH_LAUNCHER="/tmp/apps with spaces/Glyph.AppImage"):
            text = hotkeys.bindings_text(["Alt+E", "Alt+Shift+E", "Alt+R"])
        self.assertIn('spawn "/tmp/apps with spaces/Glyph.AppImage" "--action"', text)
        self.assertNotIn(".mount_", text)

    def test_no_active_bindings_before_guard_ready(self):
        manager = self.prepare(); previous = manager.bindings.read_text()
        with patch("hotkeys.shutil.which", return_value="niri"), patch.object(manager, "ensure_guard_ready", side_effect=RuntimeError("not ready")):
            self.assertFalse(manager.configure("Alt+E", "Alt+Shift+E", "Alt+R"))
        self.assertEqual(manager.bindings.read_text(), previous)
        manager.close()

    def test_real_niri_syntax(self):
        if not shutil.which("niri"): self.skipTest("niri not installed")
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.kdl"
            config.write_text(hotkeys.bindings_text(["Alt+E", "Alt+Shift+E", "Alt+R"], Path(folder) / "some path/glyph"))
            result = subprocess.run(["niri", "validate", "--config", str(config)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_guard_cleans_after_parent_crash(self):
        manager = self.prepare()
        code = """import os
from types import SimpleNamespace
from unittest.mock import patch
from hotkeys import Hotkeys
h=Hotkeys()
with patch('hotkeys.shutil.which',return_value='niri'),patch('hotkeys.subprocess.run',return_value=SimpleNamespace(returncode=0)):
    assert h.configure('Alt+E','Alt+Shift+E','Alt+R')
os._exit(0)
"""
        environment = dict(os.environ, PYTHONPATH=str(ROOT / "app"))
        subprocess.run([sys.executable, "-c", code], env=environment, check=True)
        deadline = time.monotonic() + 4
        while '"--action"' in manager.bindings.read_text() and time.monotonic() < deadline: time.sleep(.03)
        self.assertNotIn('"--action"', manager.bindings.read_text())


class PackagingTests(unittest.TestCase):
    def test_appimage_installation_preserves_data_and_image(self):
        import appimage_integration as integration
        with tempfile.TemporaryDirectory(prefix="glyph-appimage-install-") as folder:
            home = Path(folder); image = home / "some apps/Glyph.AppImage"
            image.parent.mkdir(); image.write_bytes(b"test-image")
            personal = home / "share/glyph"; personal.mkdir(parents=True)
            (personal / "glyph.db").write_bytes(b"private-test-words")
            with patch.dict(os.environ, APPIMAGE=str(image)), patch("appimage_integration.Path.home", return_value=home), patch.object(integration, "DATA_DIR", personal), patch.object(integration, "CONFIG_DIR", home / "config/glyph"):
                integration.install()
                self.assertIn(str(image), (home / ".local/bin/glyph").read_text())
                self.assertIn("X-Glyph-AppImage=true", (home / "share/applications/local.glyph.Glyph.desktop").read_text())
                self.assertFalse((personal / "application").exists())
                integration.install(uninstall=True)
                self.assertFalse((home / ".local/bin/glyph").exists())
            self.assertEqual(image.read_bytes(), b"test-image")
            self.assertEqual((personal / "glyph.db").read_bytes(), b"private-test-words")

    def test_appimage_build_inputs_and_allowlist(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from build_release import archive
        lock = json.loads((ROOT / "scripts/appimage-lock.json").read_text())
        self.assertEqual(len(lock["wheels"]), 5)
        self.assertTrue(all(len(wheel["sha256"]) == 64 for wheel in lock["wheels"]))
        with tempfile.TemporaryDirectory() as folder:
            with tarfile.open(archive(output=folder)) as tar:
                names = tar.getnames()
            self.assertTrue(any(name.endswith("/scripts/AppRun") for name in names))
            self.assertTrue(any(name.endswith("/scripts/in_appimage_build_env.sh") for name in names))
            self.assertFalse(any("/.build/" in name for name in names))

    def test_staged_runtime_diagnostic(self):
        launcher = ROOT / ".build/Glyph.AppDir/AppRun"
        if not launcher.exists(): self.skipTest("AppImage not built")
        environment = dict(os.environ); environment.pop("GLYPH_DICTIONARY_DIR", None)
        result = subprocess.run([str(launcher), "--diagnose"], env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["helpers"], "all bundled")

    def test_source_package_is_allowlisted(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from build_release import archive
        with tempfile.TemporaryDirectory() as folder:
            bundle = archive(output=folder)
            with tarfile.open(bundle) as tar:
                names = tar.getnames()
            self.assertTrue(any(name.endswith("/app/hotkeys.py") for name in names))
            self.assertFalse(any(Path(name).suffix in (".db", ".csv", ".zip", ".pyc") for name in names))
            self.assertFalse(any(set(Path(name).parts) & {"data", "web-profile", ".git", ".aws"} for name in names))

    def test_installer_dry_home_and_recoverable_uninstall(self):
        with tempfile.TemporaryDirectory(prefix="glyph-install-test-") as folder:
            environment = dict(os.environ, XDG_DATA_HOME=str(Path(folder)/"share"), XDG_CONFIG_HOME=str(Path(folder)/"config"))
            command = [sys.executable, str(ROOT/"install.py"), "--home", folder]
            subprocess.run(command, env=environment, check=True, capture_output=True)
            launcher = Path(folder) / ".local/bin/glyph"
            self.assertTrue(launcher.is_file())
            self.assertIn("application/bin/glyph", launcher.read_text())
            self.assertTrue((Path(folder)/"share/applications/local.glyph.Glyph.desktop").is_file())
            personal = Path(folder)/"share/glyph/glyph.db"; personal.write_bytes(b"preserve-test-user-data")
            subprocess.run(command+["--uninstall"], env=environment, check=True, capture_output=True)
            self.assertFalse(launcher.exists())
            self.assertEqual(personal.read_bytes(), b"preserve-test-user-data")
            self.assertTrue((Path(folder)/"share/glyph/uninstalled-application").is_dir())

    def test_niri_install_adds_only_managed_include(self):
        if not shutil.which("niri"): self.skipTest("niri not installed")
        with tempfile.TemporaryDirectory(prefix="glyph-niri-install-test-") as folder:
            config_home = Path(folder)/"config"
            root_config = config_home/"niri/config.kdl"
            root_config.parent.mkdir(parents=True)
            original = 'binds {\n    Mod+Return { spawn "terminal"; }\n}\n'
            root_config.write_text(original)
            environment = dict(os.environ, XDG_DATA_HOME=str(Path(folder)/"share"), XDG_CONFIG_HOME=str(config_home))
            command = [sys.executable,str(ROOT/"install.py"),"--home",folder]
            subprocess.run(command+["--niri"],env=environment,check=True,capture_output=True)
            self.assertIn(original.strip(),root_config.read_text())
            self.assertEqual(root_config.with_name('config.kdl.before-glyph').read_text(),original)
            self.assertIn('open-floating true',(config_home/'glyph/niri-bindings.kdl').read_text())
            result=subprocess.run(['niri','validate','--config',str(root_config)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run(command+["--uninstall"],env=environment,check=True,capture_output=True)
            self.assertNotIn('Glyph managed',root_config.read_text())
            self.assertIn('Mod+Return',root_config.read_text())


class OCRTests(unittest.TestCase):
    def test_local_tesseract_pipeline(self):
        if not shutil.which('tesseract'): self.skipTest('Tesseract not installed')
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QFont,QImage,QPainter
        from PyQt6.QtWidgets import QApplication
        import ocr_capture
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(prefix='glyph-ocr-test-') as folder:
            image=QImage(720,100,QImage.Format.Format_RGB32); image.fill(Qt.GlobalColor.white)
            painter=QPainter(image); painter.setPen(Qt.GlobalColor.black); painter.setFont(QFont('DejaVu Sans',32))
            painter.drawText(20,65,'MISCELLANEOUS'); painter.end()
            sample=Path(folder)/'sample.png'; image.save(str(sample))
            original_run=ocr_capture.run
            def command(arguments,timeout=20):
                if arguments[0]=='slurp': return SimpleNamespace(returncode=0,stdout='0,0 720x100')
                if arguments[0]=='grim':
                    shutil.copy2(sample,arguments[-1]); return SimpleNamespace(returncode=0)
                return original_run(arguments,timeout)
            with patch('ocr_capture.run',side_effect=command):
                self.assertEqual(ocr_capture.recognize(),'MISCELLANEOUS')


class InterfaceTests(unittest.TestCase):
    def test_group_selection_and_order(self):
        try:
            from PyQt6.QtCore import Qt
            from PyQt6.QtWidgets import QApplication, QMainWindow, QToolButton
            from main_qt import GlyphWindow, install_style
        except ImportError: self.skipTest("PyQt6 not installed")
        app = QApplication.instance() or QApplication([]); install_style(app)
        database.initialize()
        database.capture("strain", "strain"); database.capture("reserve", "reserve")
        sat = database.add_collection("SAT")
        window = GlyphWindow.__new__(GlyphWindow); QMainWindow.__init__(window)
        window.current_word=None; window.view_mode="all"; window.collection_id=None; window.web=None; window.last_db_state=(0,0)
        window.build_ui(); window.load_words(); window.set_view("collections")
        tree = window.word_list
        groups = {tree.topLevelItem(i).data(0,Qt.ItemDataRole.UserRole)["group_id"]:tree.topLevelItem(i) for i in range(tree.topLevelItemCount())}
        self.assertIn(0,groups); self.assertIn(sat,groups)
        window.multi_select_button.setChecked(True)
        self.assertFalse(window.batch_bar.isHidden())
        tree.clearSelection(); self.assertFalse(window.batch_group_button.isEnabled())
        groups[0].child(0).setSelected(True); self.assertTrue(window.batch_group_button.isEnabled())
        ids = tree.selected_word_ids(); window.assign_selected_words(ids,sat)
        self.assertIn(sat,database.word_collection_ids(ids[0]))
        self.assertEqual([b.text() for b in window.local_widget.findChildren(QToolButton)][:5],["×","−","+","✎","▣"])
        window.hide(); window.deleteLater(); app.processEvents()


if __name__ == "__main__": unittest.main()

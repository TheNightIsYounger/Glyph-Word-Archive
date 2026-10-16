"""Offline AppImage smoke checks. All test user data goes into a temp directory."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    with tempfile.TemporaryDirectory(prefix="glyph-bundle-check-") as folder:
        root = Path(folder)
        os.environ.update(XDG_DATA_HOME=str(root / "data"), XDG_CONFIG_HOME=str(root / "config"), XDG_CACHE_HOME=str(root / "cache"))
        from paths import APP_ROOT, DICTIONARY_DIR
        from PyQt6.QtCore import PYQT_VERSION_STR, qVersion
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        import database
        database.initialize()
        assert database.lookup_dictionary("strain"), "ECDICT missing"
        assert len(database.lookup_wordnet("strain")) >= 15, "WordNet missing"
        database.capture("STRAIN", "strain"); database.capture("Strain", "strain")
        assert len(database.list_words()) == 1
        assert database.list_words()[0]["encounter_count"] == 2
        for name in ("python3", "grim", "slurp", "wl-paste", "tesseract", "notify-send"):
            found = Path(shutil.which(name) or "/missing").resolve()
            assert APP_ROOT in found.parents, f"External dependency used: {name}: {found}"
        result = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, check=True)
        assert "eng" in result.stdout
        print(json.dumps({"python": sys.version.split()[0], "pyqt": PYQT_VERSION_STR, "qt": qVersion(),
                          "dictionaries": str(DICTIONARY_DIR), "helpers": "all bundled", "gpu_policy": os.environ.get("GLYPH_GPU_SELECTED", "system"), "offline_checks": "PASS"}, indent=2), flush=True)
        if "--gui" not in sys.argv: return 0
        from PyQt6.QtCore import QTimer, Qt
        from PyQt6.QtGui import QFont, QImage, QPainter
        from PyQt6.QtWidgets import QApplication
        from main_qt import GlyphWindow, install_style
        app = QApplication([str(APP_ROOT / "AppRun")]); app.setApplicationName("Glyph"); app.setQuitOnLastWindowClosed(False)
        install_style(app)
        window = GlyphWindow(); window.show(); window.create_web(); window.pages.setCurrentIndex(1)
        window.web.setHtml('<html><body style="height:4000px;background:#f5f7ff"><div style="position:fixed;top:30px;left:20px;padding:24px;background:#d6f3e4;color:#172b26;font:24px sans-serif" id="result">Glyph WebEngine</div><script>window.glyphTest=17;document.getElementById("result").textContent="JavaScript + rendering OK";window.scrollTo(0,300);</script></body></html>')
        passed = []
        def verify(ok):
            if not ok: return
            def complete(value):
                if value != 17: return
                assert not window.web_profile.isOffTheRecord()
                assert str(root) in window.web_profile.persistentStoragePath()
                window.hide(); window.freeze_web(True); window.show(); window.freeze_web(False)
                image = QImage(720, 100, QImage.Format.Format_RGB32); image.fill(Qt.GlobalColor.white)
                painter = QPainter(image); painter.setPen(Qt.GlobalColor.black); painter.setFont(QFont("DejaVu Sans", 32))
                painter.drawText(20, 65, "MISCELLANEOUS"); painter.end()
                sample = root / "ocr.png"; image.save(str(sample))
                result = subprocess.run(["tesseract", str(sample), "stdout", "-l", "eng", "--psm", "7"], capture_output=True, text=True, check=True)
                assert "MISCELLANEOUS" in result.stdout, result.stdout
                def finish():
                    if "--screenshot" in sys.argv:
                        destination = sys.argv[sys.argv.index("--screenshot") + 1]
                        assert window.grab().save(destination)
                    print("PASS: bundled GUI, WebEngine JavaScript, persistent profile, hide/show, real OCR", flush=True)
                    passed.append(True); app.quit()
                QTimer.singleShot(600, finish)
            window.web.page().runJavaScript("window.glyphTest", complete)
        window.web.loadFinished.connect(verify)
        app.aboutToQuit.connect(window.shutdown)
        QTimer.singleShot(20000, app.quit)
        app.exec()
        from PyQt6 import sip
        sip.delete(window); sip.delete(app)
        if not passed: raise RuntimeError("WebEngine smoke check timed out")
    return 0


if __name__ == "__main__": raise SystemExit(main())

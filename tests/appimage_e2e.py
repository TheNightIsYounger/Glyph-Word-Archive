"""Run explicitly on a real niri session; never modifies the live niri config."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result: return result
        time.sleep(.1)
    raise AssertionError("Timed out waiting for test condition")


def main():
    image = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix="glyph-appimage-e2e-") as folder:
        home = Path(folder)
        environment = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home / "data"), XDG_CONFIG_HOME=str(home / "config"), XDG_CACHE_HOME=str(home / "cache"))
        environment.pop("GLYPH_DICTIONARY_DIR", None)
        niri_config = home / "config/niri/config.kdl"; niri_config.parent.mkdir(parents=True)
        original = 'binds {\n    Mod+Return { spawn "terminal"; }\n}\n'
        niri_config.write_text(original)
        bindings = home / "config/glyph/niri-bindings.kdl"
        def command(*args): return subprocess.run([str(image), *args], env=environment, capture_output=True, text=True, check=True, timeout=20)
        command("--install", "--niri")
        assert original.strip() in niri_config.read_text()
        assert not (home / "data/glyph/application").exists()
        def window_pids():
            result = subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True, text=True, check=True)
            return {entry["pid"] for entry in json.loads(result.stdout) if entry.get("app_id") == "local.glyph.Glyph"}
        before = window_pids()
        with (home / "application.log").open("w+") as log:
            process = subprocess.Popen([str(image)], env=environment, stdout=log, stderr=log)
            child = None
            try:
                child = next(iter(wait_for(lambda: window_pids() - before)))
                text = wait_for(lambda: bindings.read_text() if '"--action"' in bindings.read_text() else None)
                assert str(image) in text and ".mount_" not in text
                command("--action", "toggle"); wait_for(lambda: child not in window_pids())
                command("--action", "toggle"); wait_for(lambda: child in window_pids())
                command("--action", "quit"); assert process.wait(timeout=12) == 0
                wait_for(lambda: '"--action"' not in bindings.read_text())
                command("--action", "toggle"); assert child not in window_pids()
                # Restart, then kill only the identified test application's PID.
                process = subprocess.Popen([str(image)], env=environment, stdout=log, stderr=log)
                child = next(iter(wait_for(lambda: window_pids() - before)))
                wait_for(lambda: '"--action"' in bindings.read_text())
                os.kill(child, signal.SIGKILL); process.wait(timeout=12)
                wait_for(lambda: '"--action"' not in bindings.read_text())
                command("--uninstall")
                assert (home / "data/glyph/glyph.db").exists()
                assert image.is_file()
                assert "Glyph managed" not in niri_config.read_text()
                print("PASS: native AppImage install, stable shortcut paths, hide/show, quit, inactive after exit, crash cleanup, uninstall preserves image/user data")
            finally:
                if process.poll() is None:
                    if child and child in window_pids(): os.kill(child, signal.SIGTERM)
                    try: process.wait(timeout=6)
                    except subprocess.TimeoutExpired: process.terminate()
                if sys.exc_info()[0]:
                    log.flush(); log.seek(0); print(log.read()[-2500:], file=sys.stderr)


if __name__ == "__main__": main()

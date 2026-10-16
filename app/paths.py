import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
APP_ID = "local.glyph.Glyph"
VERSION = "0.1.0"


def xdg_path(variable, fallback):
    return Path(os.environ.get(variable, str(Path.home() / fallback))).expanduser()


DATA_DIR = xdg_path("XDG_DATA_HOME", ".local/share") / "glyph"
CACHE_DIR = xdg_path("XDG_CACHE_HOME", ".cache") / "glyph"
CONFIG_DIR = xdg_path("XDG_CONFIG_HOME", ".config") / "glyph"
ASSET_DIR = APP_ROOT / "assets"
_bundled_dictionaries = APP_ROOT / "dictionaries"
_default_dictionaries = _bundled_dictionaries if any(_bundled_dictionaries.glob("*.db")) else DATA_DIR / "dictionaries"
DICTIONARY_DIR = Path(os.environ.get("GLYPH_DICTIONARY_DIR", _default_dictionaries)).expanduser().resolve()


def ensure_directories():
    for folder in (DATA_DIR, CACHE_DIR, CONFIG_DIR):
        folder.mkdir(parents=True, exist_ok=True)

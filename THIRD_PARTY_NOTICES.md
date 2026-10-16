# Third-party notices

## Glyph application

Application source: GPL-3.0-only, see `LICENSE`. Application contributors: Glyph contributors, 2026. This grant covers the application code and its original assets, not independently licensed data or dependencies. No third-party endorsement is implied.

## ECDICT

- Upstream: https://github.com/skywind3000/ECDICT
- Data: `ecdict.csv`, source commit `82c9872` (2025-01-02).
- Upstream license: MIT. Preserve the complete notice in `licenses/ECDICT-MIT.txt`.
- Upstream notice currently identifies Copyright (c) 2025 Linwei; the original text is reproduced without replacing its attribution.
- Modification: conversion from CSV to a local SQLite `entries` table, retaining English definitions, Chinese reference text and other selected fields. It is not an Oxford/Collins licensed offline dictionary.
- Provenance qualification: upstream describes compilation from several pre-existing sources. The upstream MIT statement supplies the declared permission, but this project has not independently established every upstream contributor's chain of rights. Upstream does not warrant non-infringement. This notice does not expand the rights upstream can grant.

## Open English WordNet 2025 and Princeton WordNet

- Upstream: https://github.com/globalwordnet/english-wordnet
- Edition: https://en-word.net/downloads
- Credit: Open English WordNet Team and Princeton University WordNet.
- Open English WordNet: CC BY 4.0; underlying Princeton WordNet: WordNet License.
- Full notices: `licenses/Open-English-WordNet-2025.txt` and `licenses/Princeton-WordNet.txt`.
- Modification: conversion of JSON to SQLite; selected definitions, examples, synonym groups, antonyms and word-family relationships extracted for lookup. The application does not claim endorsement or that its Chinese definitions align sense-by-sense with WordNet.
- Citation: John P. McCrae, Alexandre Rademaker, Francis Bond, Ewa Rudnicka and Christiane Fellbaum (2019), *English WordNet 2019 – An Open-Source WordNet for English*, Proceedings of the 10th Global WordNet Conference.

## Python, PyQt6, Qt and Qt WebEngine

- Python: https://docs.python.org/3/license.html
- PyQt6 / PyQt6-WebEngine: https://www.riverbankcomputing.com/software/pyqt (GPLv3 option used; application distributed with GPL-compatible terms).
- Qt / Qt WebEngine: https://www.qt.io/licensing and component-specific notices. Qt WebEngine also contains Chromium and additional third-party components.
- Source-only archives distribute application source and optional dictionary databases, not runtime binaries. The AppImage additionally bundles Python, required PyQt/Qt libraries, Qt WebEngine/Chromium, and command helpers. Its `licenses/runtime/` preserves component notices, and `usr/share/glyph/bundle-manifest.json` records exact versions/hashes. Corresponding source material is distributed separately alongside the AppImage; see `APPIMAGE.md`. This summary is not a replacement for the component notices or source-distribution obligations.

## External command dependencies

- Tesseract OCR: https://github.com/tesseract-ocr/tesseract — Apache-2.0.
- Tesseract English trained data: https://github.com/tesseract-ocr/tessdata — see upstream Apache-2.0 notice.
- grim: https://gitlab.freedesktop.org/emersion/grim — MIT.
- slurp: https://github.com/emersion/slurp — MIT.
- wl-clipboard: https://github.com/bugaevc/wl-clipboard — GPL-3.0.
- libnotify: https://gitlab.gnome.org/GNOME/libnotify — LGPL-2.1-or-later.
- niri: https://github.com/YaLTeR/niri — GPL-3.0-or-later.

Source installations invoke these as separately installed tools. The AppImage bundles Tesseract and English trained data, grim, slurp, wl-paste and notify-send with their required libraries; niri itself is never bundled. Ubuntu package copyright notices and source/patch archives are retained for the bundled tools and libraries.

## AppImage runtime

- AppImage type2-runtime: https://github.com/AppImage/type2-runtime, MIT, upstream commit `8f39b89e2ac31e1640b3d3f7e9a5108e6ce805fa`.
- The runtime statically links musl, libfuse, squashfuse, zstd, zlib and mimalloc. Preserve their separate notices and source/relinking materials; the runtime's own MIT license does not replace their licenses. No proprietary AppImage licensing is imposed.

## Online dictionaries

Oxford Learner's Dictionaries, Merriam-Webster and Collins are accessed at their public HTTPS sites inside a normal Qt WebEngine view. No downloaded content, audio, login session, browser cache or provider logo is shipped as a dictionary dataset. Users interact with the original site's consent/login/access controls. Access and content rights remain subject to each site's terms; product names identify destinations and do not indicate affiliation. Websites can change or refuse embedded access.

## Publication note

Do not publish developer/user databases, cookies, website snapshots, exam content, private configuration or credentials. Dictionary conversion does not transfer ownership of upstream definitions. A public upstream repository and a disclaimer do not eliminate possible third-party rights claims.

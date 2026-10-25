"""Messages in the user's language, for the server, the engine and the Blender step.

The strings live in app/static/i18n/<lang>.json, shared with the interface; the keys of this side start with
"srv.". The language comes from LOWPOLY_LANG, which the server sets from the saved choice or the system language,
so Blender and the other child processes inherit it. Standard library only: boot.py imports it before any venv.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = os.path.join(ROOT, "app", "static", "i18n")
LANGUAGES = {"en": "English", "fr": "Français", "es": "Español", "de": "Deutsch", "pt-BR": "Português (Brasil)",
             "zh-CN": "简体中文", "ja": "日本語"}
DEFAULT = "en"
_cache = {}


def language():
    lang = os.environ.get("LOWPOLY_LANG", DEFAULT)
    return lang if lang in LANGUAGES else DEFAULT


def strings(lang):
    if lang not in _cache:
        try:
            with open(os.path.join(FILES, f"{lang}.json"), encoding="utf-8") as f:
                _cache[lang] = json.load(f)
        except (OSError, ValueError):
            _cache[lang] = {}
    return _cache[lang]


def plural_form(lang, n):
    """CLDR categories for whole numbers: French and Portuguese count 0 as one, Chinese and Japanese have no
    plural."""
    if lang in ("zh-CN", "ja"):
        return "other"
    return "one" if n == 1 or (n == 0 and lang in ("fr", "pt-BR")) else "other"


def tr(key, **values):
    """The message for key in the current language, English when it is missing there, the key itself as a last
    resort. A message with forms takes the one for values["n"]."""
    lang = language()
    text = strings(lang).get(key, strings(DEFAULT).get(key, key))
    if isinstance(text, dict):
        text = text.get(plural_form(lang, values.get("n", 0)), text.get("other", key))
    return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def match(tag):
    """The supported language closest to a system tag such as fr_FR.UTF-8, pt-PT or zh-Hans-CN."""
    t = (tag or "").replace("_", "-").split(".")[0].lower()
    if t.startswith("zh"):
        # traditional Chinese readers get English rather than the simplified script
        return DEFAULT if any(x in t for x in ("hant", "-tw", "-hk", "-mo")) else "zh-CN"
    if t.startswith("pt"):
        return "pt-BR"
    base = t.split("-")[0]
    return base if base in LANGUAGES else DEFAULT


def system_language():
    """The language of the system's interface, read natively: WebView2 does not report it to the page."""
    try:
        if sys.platform == "win32":
            import ctypes
            import locale
            return locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
        if sys.platform == "darwin":
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True,
                                 timeout=5).stdout
            found = re.findall(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)*", out)
            return found[0] if found else ""
    except (OSError, subprocess.SubprocessError, AttributeError, ValueError):
        pass
    return os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""


def prefs_path(data_dir):
    return os.path.join(data_dir, "prefs.json")


def saved_language(data_dir):
    try:
        with open(prefs_path(data_dir), encoding="utf-8") as f:
            lang = json.load(f).get("language")
        return lang if lang in LANGUAGES else None
    except (OSError, ValueError, AttributeError):
        return None


def save_language(data_dir, lang):
    os.makedirs(data_dir, exist_ok=True)
    tmp = prefs_path(data_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"language": lang}, f)
    os.replace(tmp, prefs_path(data_dir))


def startup_language(data_dir):
    """The saved choice, else the system's language; written to LOWPOLY_LANG for this process and its children."""
    lang = saved_language(data_dir) or match(system_language())
    os.environ["LOWPOLY_LANG"] = lang
    return lang

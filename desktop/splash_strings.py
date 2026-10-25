"""Copies the "splash." strings of app/static/i18n/*.json into desktop/ui/index.html.

The start page shows before the server exists, so it cannot fetch the language files: it carries its own copy.
python desktop/splash_strings.py   (tests/i18n_test.py checks the copy is current)
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "desktop", "ui", "index.html")
LANGS = ("en", "fr", "es", "de", "pt-BR", "zh-CN", "ja")
BLOCK = re.compile(r"const STRINGS = \{.*?\n\};\n", re.S)


def block():
    parts = []
    for lang in LANGS:
        with open(os.path.join(ROOT, "app", "static", "i18n", f"{lang}.json"), encoding="utf-8") as f:
            strings = {k: v for k, v in sorted(json.load(f).items()) if k.startswith("splash.")}
        body = "".join(f"    {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)},\n" for k, v in strings.items())
        parts.append(f"  {json.dumps(lang)}: {{\n{body}  }},\n")
    return "const STRINGS = {\n" + "".join(parts) + "};\n"


def main():
    with open(PAGE, encoding="utf-8") as f:
        page = f.read()
    with open(PAGE, "w", encoding="utf-8", newline="\n") as f:
        f.write(BLOCK.sub(lambda m: block(), page, count=1))


if __name__ == "__main__":
    main()

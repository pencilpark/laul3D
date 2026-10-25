"""Translations: the seven language files agree with English, the code only uses keys that exist.

python tests/i18n_test.py
"""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))
import i18n  # noqa: E402

PH = re.compile(r"\{(\w+)\}")


def placeholders(v):
    return set().union(*(set(PH.findall(t)) for t in (v.values() if isinstance(v, dict) else [v])))


def main():
    files = {lang: json.load(open(os.path.join(i18n.FILES, f"{lang}.json"), encoding="utf-8")) for lang in i18n.LANGUAGES}
    en = files["en"]
    for lang, data in files.items():
        assert set(data) == set(en), (lang, sorted(set(en) ^ set(data))[:10])
        for k, v in data.items():
            assert isinstance(v, dict) == isinstance(en[k], dict), (lang, k)
            assert placeholders(v) == placeholders(en[k]), (lang, k, v)
            texts = list(v.values()) if isinstance(v, dict) else [v]
            assert all(t.strip() and not re.search(r"<[a-zA-Z/]", t) for t in texts), (lang, k, v)
            if isinstance(v, dict):
                assert "other" in v and (lang in ("zh-CN", "ja") or "one" in v), (lang, k, sorted(v))

    used = set()
    sources = [os.path.join(ROOT, "app", "static", "index.html"), os.path.join(ROOT, "app", "server.py"),
               os.path.join(ROOT, "desktop", "boot.py"), *glob.glob(os.path.join(ROOT, "engine", "*.py"))]
    for path in sources:
        text = open(path, encoding="utf-8").read()
        used |= set(re.findall(r"""["'`]((?:ui|srv|boot)\.[a-z0-9_]+)["'`]""", text))
        used |= set(re.findall(r'data-i18n="([^"]+)"', text))
        for attr in re.findall(r'data-i18n-attr="([^"]+)"', text):
            used |= {pair.split(":", 1)[1] for pair in attr.split(";")}
    assert used, "no translated text found"
    assert used <= set(en), sorted(used - set(en))

    sys.path.insert(0, os.path.join(ROOT, "desktop"))
    import splash_strings
    page = open(splash_strings.PAGE, encoding="utf-8").read()
    assert splash_strings.BLOCK.search(page).group(0) == splash_strings.block(), \
        "start page strings out of date: run python desktop/splash_strings.py"

    for tag, lang in (("fr_FR.UTF-8", "fr"), ("pt-PT", "pt-BR"), ("zh-Hans-CN", "zh-CN"), ("zh_TW", "en"),
                      ("de-AT", "de"), ("ja-JP", "ja"), ("es-419", "es"), ("C", "en"), ("it_IT", "en")):
        assert i18n.match(tag) == lang, (tag, i18n.match(tag))
    os.environ["LOWPOLY_LANG"] = "fr"
    assert i18n.tr("srv.unknown_language") == files["fr"]["srv.unknown_language"]
    assert i18n.tr("srv.no_such_key") == "srv.no_such_key"
    os.environ["LOWPOLY_LANG"] = "xx"
    assert i18n.language() == "en"
    assert [i18n.plural_form(lang, 0) for lang in ("fr", "pt-BR", "en", "ja")] == ["one", "one", "other", "other"]
    print(f"traductions : {len(en)} clés dans {len(files)} langues, {len(used)} citées par le code")
    return 0


if __name__ == "__main__":
    sys.exit(main())

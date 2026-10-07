"""Build the static in-browser site (SPEC UC-8) for GitHub Pages: index.html + boot.js + stockguard.zip.

    python3 scripts/build_site.py --out site
    python3 -m http.server -d site 8000      # then open http://127.0.0.1:8000
"""
import argparse
import os
import shutil
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PKG = os.path.join(ROOT, "src", "stockguard")


def build(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    html = open(os.path.join(PKG, "web", "index.html"), encoding="utf-8").read()
    marker = "<script>\nconst $ ="
    assert marker in html, "index.html layout changed: boot.js must load before the page script"
    html = html.replace(marker, '<script src="boot.js"></script>\n' + marker, 1)
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(html)
    shutil.copyfile(os.path.join(ROOT, "site_src", "boot.js"), os.path.join(out, "boot.js"))
    open(os.path.join(out, ".nojekyll"), "w").close()
    with zipfile.ZipFile(os.path.join(out, "stockguard.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for dp, dn, fn in os.walk(PKG):
            dn[:] = [d for d in dn if d != "__pycache__"]
            for f in sorted(fn):
                if f.endswith((".py", ".html")):
                    full = os.path.join(dp, f)
                    z.write(full, os.path.relpath(full, os.path.dirname(PKG)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "site"))
    build(ap.parse_args().out)

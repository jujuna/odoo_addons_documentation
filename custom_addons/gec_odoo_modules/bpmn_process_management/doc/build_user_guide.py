"""Build the self-contained user guide (images embedded as data URIs).

    python3 doc/build_user_guide.py

Georgian: user_guide_src.html (images/) -> user_guide.html
English:  user_guide_src_en.html (images_en/, falling back to images/) -> user_guide_en.html
Each is written to doc/ and to static/doc/ (served by the module; the route
/bpmn_process_management/guide picks the user's language)."""
import base64
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


GUIDES = [("user_guide_src.html", "user_guide.html", ["images"]),
          ("user_guide_src_en.html", "user_guide_en.html", ["images_en", "images"])]


def data_uri(name, folders):
    for folder in folders:
        path = os.path.join(HERE, folder, name)
        if os.path.exists(path):
            with open(path, "rb") as f:
                return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    raise SystemExit("missing image: %s" % name)


def build(src, out, folders):
    with open(os.path.join(HERE, src), encoding="utf-8") as f:
        html = f.read()
    html = re.sub(r"\{\{img:([\w.-]+)\}\}",
                  lambda m: '<img src="%s" alt="" loading="lazy">' % data_uri(m.group(1), folders), html)
    html = re.sub(r"\{\{imgraw:([\w.-]+)\}\}",
                  lambda m: '<img src="%s" alt="">' % data_uri(m.group(1), folders), html)
    missing = re.findall(r"\{\{[^}]+\}\}", html)
    if missing:
        raise SystemExit("unresolved placeholders: %s" % missing)
    for path in (os.path.join(HERE, out), os.path.join(ROOT, "static", "doc", out)):
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        print(path, len(html) // 1024, "KB")


def main():
    for src, out, folders in GUIDES:
        if os.path.exists(os.path.join(HERE, src)):
            build(src, out, folders)


if __name__ == "__main__":
    main()

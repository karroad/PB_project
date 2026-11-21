"""Renders the shared site spec into a static, deployable build directory."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import DictLoader, Environment, select_autoescape

from ..config import settings
from .templates import JS, TEMPLATES

_env = Environment(loader=DictLoader(TEMPLATES), autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)


def nav_pages(spec: dict) -> list[dict]:
    pages = [p for p in spec["plan"]["sitemap"] if p["slug"] != ""]
    return [{"slug": "", "title": "Home"}] + [{"slug": p["slug"], "title": p["title"]} for p in pages]


def render_static(spec: dict, build_dir: Path, media_dir: Path, base_url: str, slug: str) -> list[str]:
    """Writes the build and returns the list of written relative file paths."""
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)
    written: list[str] = []

    def write(rel: str, text: str) -> None:
        out = build_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        written.append(rel)

    if media_dir.exists():
        shutil.copytree(media_dir, build_dir / "assets" / "media")
        written += [f"assets/media/{p.name}" for p in (build_dir / "assets" / "media").iterdir()]

    brand, c, seo = spec["brand"], spec["content"], spec["seo"]
    base_url = base_url.rstrip("/") + "/"
    common = {
        "brand": brand, "c": c, "req": spec["requirements"], "images": spec["images"], "nav": nav_pages(spec),
        "base_url": base_url, "lang": spec["requirements"].get("language", "en"), "year": datetime.now().year,
        "jsonld": json.dumps(seo.get("organization", {})),
        "form_action": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/public/forms/{slug}",
    }

    def page(template: str, rel_dir: str, key: str, current: str, **extra) -> None:
        depth = len([x for x in rel_dir.split("/") if x])
        meta = seo["pages"].get(key) or {"title": brand["name"], "description": brand["tagline"], "keywords": []}
        html = _env.get_template(template).render(
            **common, root="../" * depth, path=(rel_dir + "/" if rel_dir else ""), meta=meta, current=current, **extra
        )
        write(f"{rel_dir}/index.html" if rel_dir else "index.html", html)

    slugs = {p["slug"] for p in spec["plan"]["sitemap"]}
    page("home.html", "", "", "")
    if "about" in slugs:
        page("about.html", "about", "about", "about")
    if "services" in slugs:
        page("services.html", "services", "services", "services")
    if "shop" in slugs and c.get("products"):
        page("shop.html", "shop", "shop", "shop")
    page("blog.html", "blog", "blog", "blog")
    for a in c["articles"]:
        page("post.html", f"blog/{a['slug']}", f"blog/{a['slug']}", "blog", a=a)
    faq_ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in c["faq"]]}
    page("faq.html", "faq", "faq", "faq", faq_jsonld=json.dumps(faq_ld))
    page("contact.html", "contact", "contact", "contact")
    page("thanks.html", "contact/thanks", "contact", "contact")
    html404 = _env.get_template("404.html").render(**common, root=urlparse(base_url).path or "/", path="404",
                                                   meta={"title": "Not found", "description": "Page not found", "keywords": []}, current="")
    write("404.html", html404)

    write("assets/css/site.css", _env.get_template("site.css").render(p=brand["palette"], brand=brand))
    write("assets/js/site.js", JS)

    urls = [""] + [p["slug"] + "/" for p in spec["plan"]["sitemap"] if p["slug"]] + [f"blog/{a['slug']}/" for a in c["articles"]]
    today = datetime.now().date().isoformat()
    sm = "\n".join(f"  <url><loc>{base_url}{u}</loc><lastmod>{today}</lastmod></url>" for u in urls)
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{sm}\n</urlset>\n')
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base_url}sitemap.xml\n")
    return written

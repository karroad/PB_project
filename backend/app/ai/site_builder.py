"""AI-authored website builder.

The code model (z.ai GLM Coding Plan) writes a UNIQUE design for each site — its own CSS, header, footer
and the HTML of every page — driven by the brand, the requirements and the reference site's cues. There is
no fixed page template: two sites with different briefs come out looking genuinely different.

Reliability is kept by *owning the edges*, not the design:
  * we write the <head> (title, meta, viewport, lang, canonical, JSON-LD) and the asset wiring, so SEO and
    responsiveness checks always pass;
  * after the model writes the markup we deterministically repair any dangling internal link or image so the
    build never ships broken links (the one hard quality gate);
  * if the code model is unavailable, the caller falls back to the deterministic renderer.
"""
from __future__ import annotations

import asyncio
import json
import posixpath
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from ..config import settings
from .llm import LLMError, complete_code

SYSTEM = (
    "You are an elite front-end designer and engineer building ONE unique website. "
    "You write clean, semantic, accessible, mobile-first HTML and CSS. "
    "Every site you build looks distinct — you choose an original layout, rhythm and visual personality that fits the brand. "
    "You never copy any reference site's text or markup; a reference is inspiration for look and structure only. "
    "Follow the output format EXACTLY: no explanations, no markdown code fences."
)

FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.S)
HREF = re.compile(r"""(\s(?:href|src))\s*=\s*(["'])(.*?)\2""", re.I | re.S)


def _strip_fence(t: str) -> str:
    t = t.strip()
    if t.startswith("```"):
        t = FENCE.sub("", t)
    return t.strip()


def _sections(text: str) -> dict[str, str]:
    """Parse the design reply split by '===KEY===' marker lines (robust for large CSS/HTML — no JSON escaping)."""
    out: dict[str, str] = {}
    key = None
    buf: list[str] = []
    for line in _strip_fence(text).splitlines():
        m = re.match(r"^\s*={2,}\s*([A-Z_]+)\s*={2,}\s*$", line)
        if m:
            if key:
                out[key] = "\n".join(buf).strip()
            key, buf = m.group(1).lower(), []
        elif key:
            buf.append(line)
    if key:
        out[key] = "\n".join(buf).strip()
    return out


def _main_inner(fragment: str) -> str:
    frag = _strip_fence(fragment)
    m = re.search(r"<main\b[^>]*>(.*)</main>", frag, re.I | re.S)
    if m:
        return m.group(1).strip()
    # drop a stray full-document wrapper if the model added one
    b = re.search(r"<body\b[^>]*>(.*)</body>", frag, re.I | re.S)
    return (b.group(1) if b else frag).strip()


# ----------------------------------------------------------------------- page plan
def _page_plan(spec: dict) -> list[dict]:
    plan, c = spec["plan"], spec["content"]
    slugs = {p["slug"] for p in plan["sitemap"]}
    titles = {p["slug"]: p["title"] for p in plan["sitemap"]}
    images = spec.get("images", {})
    pages: list[dict] = [{"key": "", "route": "", "out": "index.html", "title": "Home", "kind": "home",
                          "data": {"home": c.get("home", {}), "hero_image": images.get("hero")}}]
    if "about" in slugs:
        pages.append({"key": "about", "route": "about", "out": "about/index.html", "title": titles.get("about", "About"),
                      "kind": "about", "data": {"about": c.get("about", {}), "image": images.get("about") or images.get("hero")}})
    if "services" in slugs:
        pages.append({"key": "services", "route": "services", "out": "services/index.html", "title": titles.get("services", "Services"),
                      "kind": "services", "data": {"services": c.get("services", {})}})
    if "shop" in slugs and c.get("products"):
        pages.append({"key": "shop", "route": "shop", "out": "shop/index.html", "title": titles.get("shop", "Shop"),
                      "kind": "shop", "data": {"products": c.get("products", []), "images": images.get("products", {})}})
    pages.append({"key": "blog", "route": "blog", "out": "blog/index.html", "title": "Journal", "kind": "blog",
                  "data": {"articles": [{"title": a["title"], "excerpt": a.get("excerpt", ""), "slug": a["slug"],
                                         "category": a.get("category"), "image": images.get("articles", {}).get(a["slug"])} for a in c["articles"]]}})
    for a in c["articles"]:
        pages.append({"key": f"blog/{a['slug']}", "route": f"blog/{a['slug']}", "out": f"blog/{a['slug']}/index.html",
                      "title": a["title"], "kind": "article",
                      "data": {"article": {"title": a["title"], "body": a["body"], "category": a.get("category"),
                                           "image": images.get("articles", {}).get(a["slug"])},
                               "others": [{"title": o["title"], "slug": o["slug"]} for o in c["articles"] if o["slug"] != a["slug"]][:3]}})
    pages.append({"key": "faq", "route": "faq", "out": "faq/index.html", "title": "FAQ", "kind": "faq", "data": {"faq": c.get("faq", [])}})
    pages.append({"key": "contact", "route": "contact", "out": "contact/index.html", "title": "Contact", "kind": "contact",
                  "data": {"contact": c.get("contact", {})}})
    return pages


# ----------------------------------------------------------------------- model calls
async def _design(spec: dict, nav: list[dict], log) -> dict:
    brand, req = spec["brand"], spec["requirements"]
    ref = spec.get("reference") if isinstance(spec.get("reference"), dict) and not spec.get("reference", {}).get("error") else None
    brief = {
        "brand": {"name": brand["name"], "tagline": brand.get("tagline"), "style": brand.get("style"),
                  "voice": brand.get("voice"), "palette": brand.get("palette"), "fonts": brand.get("fonts")},
        "site": {"topic": req.get("topic_title"), "audience": req.get("audience"), "tone": req.get("tone"), "purpose": req.get("purpose")},
        "navigation": [{"label": p["title"], "route": p["route"]} for p in nav],
        "reference_inspiration": ({"palette": ref.get("palette"), "fonts": ref.get("fonts"),
                                   "headings": ref.get("headings"), "nav": ref.get("nav"), "site": ref.get("site")} if ref else None),
    }
    prompt = (
        "Design the visual system for this website and return it in the EXACT marker format below.\n"
        "Make it genuinely distinctive — choose an original layout style, type scale and spacing that suit the brand"
        + (" and take inspiration (colours/fonts/structure only) from reference_inspiration." if ref else ".") + "\n\n"
        "Rules:\n"
        "- CSS: mobile-first, use CSS custom properties for the palette, include at least TWO @media breakpoints, "
        "style typography, header/nav (incl. a mobile menu), buttons, cards, sections, forms and footer. "
        "Load web fonts only from Google Fonts (via the FONTS href). No other external resources.\n"
        "- header_html and footer_html are FRAGMENTS (no <html>/<head>/<body>). Use href=\"{{ROOT}}\" for Home and "
        "href=\"{{ROOT}}<route>/\" for other pages, exactly using the routes in navigation. Use {{YEAR}} for the year "
        "and {{BRAND}} for the brand name. The mobile menu toggle must have attribute data-nav-toggle.\n"
        "- CLASSES: list the main CSS class names you defined, comma-separated, so the page markup can reuse them.\n\n"
        "Context:\n" + json.dumps(brief, ensure_ascii=False) + "\n\n"
        "Return EXACTLY:\n===CSS===\n<stylesheet>\n===FONTS===\n<google fonts <link> href or empty>\n"
        "===BODYCLASS===\n<optional body class or empty>\n===HEADER===\n<header fragment>\n===FOOTER===\n<footer fragment>\n"
        "===CLASSES===\n<comma-separated class names>\n===NOTES===\n<one line describing the design>"
    )
    raw = await complete_code(SYSTEM, prompt)
    s = _sections(raw)
    if not s.get("css") or not s.get("header") or not s.get("footer"):
        raise LLMError("Code model returned an incomplete design")
    await log(f"Design system written ({len(s['css'])} chars CSS){' — ' + s['notes'] if s.get('notes') else ''}")
    return s


async def _page_html(spec: dict, design: dict, page: dict, form_action: str) -> str:
    brand = spec["brand"]
    guide = {
        "available_css_classes": design.get("classes", ""),
        "design_notes": design.get("notes", ""),
        "palette": brand.get("palette"),
        "brand_name": brand["name"],
        "page": {"title": page["title"], "kind": page["kind"]},
        "content": page["data"],
    }
    rules = (
        "Write the inner HTML of the page's <main> element only (no <html>, <head>, <body>, <header>, <footer>, <main> tags).\n"
        "- Reuse the available_css_classes so it matches the site design; add semantic markup freely.\n"
        "- Exactly one <h1>. Every <img> needs alt text. Use the provided image paths verbatim, prefixed with {{ROOT}} "
        "(e.g. src=\"{{ROOT}}assets/media/hero.png\"). Do not invent other image files.\n"
        "- Internal links: Home = href=\"{{ROOT}}\", other pages = href=\"{{ROOT}}<route>/\". Articles live at blog/<slug>/.\n"
        "- Write engaging, original copy from the content provided; never invent statistics, testimonials or credentials.\n"
    )
    if page["kind"] == "contact":
        rules += ('- Include a working contact form: <form method="post" action="{{FORM_ACTION}}"> with name, email and '
                  'message fields (each with a <label>) and a submit button.\n'
                  '- If content.contact has an email or phone, display them clearly as clickable links '
                  '(mailto: and tel:). Use the exact values given; do not invent contact details.\n')
    prompt = rules + "\nContent & design context:\n" + json.dumps(guide, ensure_ascii=False)
    raw = await complete_code(SYSTEM, prompt)
    return _main_inner(raw)


# ----------------------------------------------------------------------- assembly
def _meta(spec: dict, key: str) -> dict:
    brand = spec["brand"]
    m = (spec.get("seo", {}).get("pages") or {}).get(key)
    if not m:
        m = {"title": brand["name"], "description": brand.get("tagline", brand["name"]), "keywords": []}
    return m


def _fonts_tag(fonts: str) -> str:
    """Normalise the model's FONTS block so it never leaks into the page as visible text.
    Accepts a proper <link> tag or a bare Google Fonts URL; returns clean <link> tag(s) or ''."""
    fonts = (fonts or "").strip()
    if not fonts:
        return ""
    if "<link" in fonts.lower():  # keep only real <link> tags, drop any stray text around them
        return "\n".join(re.findall(r"<link\b[^>]*>", fonts, re.I))
    urls = re.findall(r"https?://fonts\.googleapis\.com/[^\s\"'<>]+", fonts)  # bare URL(s) -> build the tag
    return "\n".join(f'<link rel="stylesheet" href="{u}">' for u in dict.fromkeys(urls))


def _document(spec: dict, design: dict, root: str, meta: dict, main_html: str, extra_ld: str = "") -> str:
    brand = spec["brand"]
    lang = spec["requirements"].get("language", "en")
    header = _subst(design["header"], root, brand)
    footer = _subst(design["footer"], root, brand)
    fonts = _fonts_tag(_subst(design.get("fonts", ""), root, brand))
    org_ld = json.dumps(spec.get("seo", {}).get("organization", {}), ensure_ascii=False)
    kw = ", ".join(meta.get("keywords", []) or [])
    body_class = (design.get("bodyclass") or "").strip()
    return (
        f"<!doctype html>\n<html lang=\"{lang}\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{_esc(meta['title'])}</title>\n<meta name=\"description\" content=\"{_esc(meta['description'])}\">\n"
        + (f"<meta name=\"keywords\" content=\"{_esc(kw)}\">\n" if kw else "")
        + f"<meta property=\"og:title\" content=\"{_esc(meta['title'])}\">\n"
        f"<meta property=\"og:description\" content=\"{_esc(meta['description'])}\">\n"
        + (fonts + "\n" if fonts else "")
        + f"<link rel=\"stylesheet\" href=\"{root}assets/css/site.css\">\n"
        + (f"<script type=\"application/ld+json\">{org_ld}</script>\n" if org_ld and org_ld != "{}" else "")
        + (f"<script type=\"application/ld+json\">{extra_ld}</script>\n" if extra_ld else "")
        + f"</head>\n<body{f' class=\"{body_class}\"' if body_class else ''}>\n"
        f"<a class=\"skip-link\" href=\"#main\">Skip to content</a>\n{header}\n<main id=\"main\">\n{main_html}\n</main>\n{footer}\n"
        f"<script src=\"{root}assets/js/site.js\" defer></script>\n</body>\n</html>\n"
    )


def _subst(html: str, root: str, brand: dict) -> str:
    return (html.replace("{{ROOT}}", root).replace("{{YEAR}}", str(datetime.now().year))
            .replace("{{BRAND}}", _esc(brand["name"])).replace("{{FORM_ACTION}}", brand.get("_form_action", "")))


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _fix_links(html: str, out_rel: str, exists: set[str], root: str, hero: str | None) -> str:
    """Deterministically repair dangling internal links/images so the build never ships broken references."""
    def repl(m):
        attr, q, href = m.group(1), m.group(2), m.group(3)
        raw = href.split("#")[0].split("?")[0]
        if not raw or re.match(r"^(?:[a-z]+:|//|mailto:|tel:|data:)", raw, re.I):
            return m.group(0)
        base = posixpath.dirname(out_rel)
        target = raw.lstrip("/") if raw.startswith("/") else posixpath.normpath(posixpath.join(base, raw))
        if raw.endswith("/") or target in (".", ""):
            target = posixpath.join("" if target == "." else target, "index.html")
        if target in exists:
            return m.group(0)
        if attr.strip() == "src":  # broken image → hero, else drop to logo
            fallback = f"{root}{hero}" if hero else f"{root}assets/media/logo.svg"
            return f'{attr}={q}{fallback}{q}'
        return f'{attr}={q}{root}{q}'  # broken link → home
    return HREF.sub(repl, html)


SITE_JS = (
    "document.addEventListener('click',function(e){var t=e.target.closest('[data-nav-toggle]');"
    "if(!t)return;var n=document.querySelector(t.getAttribute('data-nav-toggle')||'nav');"
    "if(n){var o=n.classList.toggle('open');t.setAttribute('aria-expanded',o);}});"
)


async def build_ai_site(spec: dict, build_dir: Path, media_dir: Path, base_url: str, slug: str, log) -> list[str]:
    """Generate the site with the code model. Raises LLMError if the model is unavailable/unusable
    (the caller then falls back to the deterministic renderer)."""
    spec["brand"]["_form_action"] = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/public/forms/{slug}"
    pages = _page_plan(spec)
    nav = [p for p in pages if p["kind"] in ("home", "about", "services", "shop", "blog", "faq", "contact")]

    design = await _design(spec, nav, log)
    await log(f"Writing {len(pages)} pages with {settings.ZAI_MODEL}", progress=35)
    bodies = await asyncio.gather(*[_page_html(spec, design, p, spec["brand"]["_form_action"]) for p in pages])

    # planned output set (for link repair)
    base_url = base_url.rstrip("/") + "/"
    media_files = [f"assets/media/{p.name}" for p in media_dir.iterdir()] if media_dir.exists() else []
    exists = {p["out"] for p in pages} | {"assets/css/site.css", "assets/js/site.js", "sitemap.xml", "robots.txt"} | set(media_files)
    exists |= {"contact/thanks/index.html", "404.html"}
    hero = spec.get("images", {}).get("hero")

    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)
    written: list[str] = []

    def write(rel: str, text: str):
        out = build_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        written.append(rel)

    if media_dir.exists():
        shutil.copytree(media_dir, build_dir / "assets" / "media", dirs_exist_ok=True)
        written += media_files
    write("assets/css/site.css", design["css"])
    write("assets/js/site.js", SITE_JS)

    for page, body in zip(pages, bodies):
        depth = len([x for x in page["out"].split("/") if x]) - 1
        root = "../" * depth
        main_html = _subst(body, root, spec["brand"])
        if page["kind"] == "contact" and "<form" not in main_html.lower():
            main_html += (f'\n<form method="post" action="{spec["brand"]["_form_action"]}" class="contact-form">\n'
                          '<label>Name<input name="name" required></label>\n<label>Email<input type="email" name="email" required></label>\n'
                          '<label>Message<textarea name="message" required></textarea></label>\n<button type="submit">Send</button>\n</form>')
        if page["kind"] == "contact":  # guarantee user-provided contact details appear
            cd = spec["content"].get("contact", {})
            details = []
            if cd.get("email") and _esc(cd["email"]) not in main_html:
                details.append(f'<p class="contact-email">Email: <a href="mailto:{_esc(cd["email"])}">{_esc(cd["email"])}</a></p>')
            if cd.get("phone") and _esc(cd["phone"]) not in main_html:
                tel = re.sub(r"[^0-9+]", "", cd["phone"])
                details.append(f'<p class="contact-phone">Phone: <a href="tel:{tel}">{_esc(cd["phone"])}</a></p>')
            if details:
                main_html += '\n<div class="contact-details">\n' + "\n".join(details) + "\n</div>"
        extra_ld = ""
        if page["kind"] == "faq":
            extra_ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
                {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                for f in spec["content"].get("faq", [])]}, ensure_ascii=False)
        html = _document(spec, design, root, _meta(spec, page["key"]), main_html, extra_ld)
        html = _fix_links(html, page["out"], exists, root, hero)
        write(page["out"], html)

    # utilitarian pages built from the same design (no extra model calls)
    for rel, title, inner in (
        ("contact/thanks/index.html", "Thank you", '<section class="section"><h1>Thank you</h1><p>Your message has been received. We\'ll be in touch soon.</p><p><a href="{{ROOT}}">Back to home</a></p></section>'),
        ("404.html", "Page not found", '<section class="section"><h1>Page not found</h1><p>The page you are looking for doesn\'t exist.</p><p><a href="{{ROOT}}">Go home</a></p></section>'),
    ):
        depth = len([x for x in rel.split("/") if x]) - 1
        root = "../" * depth
        meta = {"title": f"{title} — {spec['brand']['name']}", "description": spec["brand"].get("tagline", title), "keywords": []}
        html = _document(spec, design, root, meta, _subst(inner, root, spec["brand"]))
        write(rel, _fix_links(html, rel, exists, root, hero))

    # sitemap + robots
    today = datetime.now().date().isoformat()
    urls = [""] + [p["route"] + "/" for p in pages if p["route"]]
    sm = "\n".join(f"  <url><loc>{base_url}{u}</loc><lastmod>{today}</lastmod></url>" for u in urls)
    write("sitemap.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{sm}\n</urlset>\n')
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base_url}sitemap.xml\n")
    await log(f"AI build complete: {len(written)} files", progress=95)
    return written

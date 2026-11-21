"""Static quality gate run on the build artefact before anything is deployed."""
from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

SECRET_PATTERNS = [
    (r"sk-ant-[A-Za-z0-9_\-]{10,}", "Anthropic API key"),
    (r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", "Private key"),
    (r"(?i)x-shopify-access-token", "Shopify token header"),
    (r"shpat_[a-f0-9]{20,}", "Shopify admin token"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
]
SEVERITY_PENALTY = {"critical": 25, "major": 8, "minor": 3}


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title, self.in_title = "", False
        self.meta: dict[str, str] = {}
        self.links: list[str] = []
        self.assets: list[str] = []
        self.imgs: list[dict] = []
        self.forms: list[dict] = []
        self.h1 = 0
        self.lang = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title":
            self.in_title = True
        elif tag == "meta" and a.get("name"):
            self.meta[a["name"].lower()] = a.get("content", "")
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "link" and a.get("href") and a.get("rel") in ("stylesheet", "icon"):
            self.assets.append(a["href"])
        elif tag == "script" and a.get("src"):
            self.assets.append(a["src"])
        elif tag == "img":
            self.imgs.append(a)
        elif tag == "form":
            self.forms.append(a)
        elif tag == "h1":
            self.h1 += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title += data


def _resolve(page_rel: str, href: str) -> str | None:
    href = href.split("#")[0].split("?")[0]
    if not href or re.match(r"^(?:[a-z]+:|//)", href):
        return None
    base = posixpath.dirname(page_rel)
    target = posixpath.normpath(posixpath.join(base, href)) if not href.startswith("/") else href.lstrip("/")
    if href.endswith("/") or target in (".", ""):
        target = posixpath.join("" if target == "." else target, "index.html")
    return target


def run_checks(build_dir: Path, state: dict, secrets: list[str]) -> dict:
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str, severity: str = "major", warn: bool = False) -> None:
        status = "pass" if ok else ("warn" if warn else "fail")
        checks.append({"name": name, "status": status, "severity": severity, "detail": detail})

    pages = sorted(str(p.relative_to(build_dir)).replace("\\", "/") for p in build_dir.rglob("*.html"))
    add("Homepage available", "index.html" in pages, "index.html present" if "index.html" in pages else "No index.html in build", "critical")

    missing_title, missing_desc, no_viewport, bad_h1, no_lang = [], [], [], [], []
    broken_links: set[str] = set()
    missing_imgs: set[str] = set()
    no_alt = 0
    bad_forms = 0
    heavy = []
    for rel in pages:
        text = (build_dir / rel).read_text(encoding="utf-8", errors="ignore")
        p = _PageParser()
        p.feed(text)
        if not p.title.strip():
            missing_title.append(rel)
        if rel != "404.html" and not (50 <= len(p.meta.get("description", "")) <= 170):
            missing_desc.append(rel)
        if "width=device-width" not in p.meta.get("viewport", ""):
            no_viewport.append(rel)
        if p.h1 != 1:
            bad_h1.append(rel)
        if not p.lang:
            no_lang.append(rel)
        if rel == "404.html":
            continue
        for href in p.links + p.assets:
            t = _resolve(rel, href)
            if t and not (build_dir / t).exists():
                broken_links.add(f"{rel} → {href}")
        for img in p.imgs:
            t = _resolve(rel, img.get("src", ""))
            if t and not (build_dir / t).exists():
                missing_imgs.add(img.get("src", ""))
            if "alt" not in img:
                no_alt += 1
        for f in p.forms:
            if not f.get("action") or f.get("method", "get").lower() != "post":
                bad_forms += 1
        if len(text.encode()) > 150_000:
            heavy.append(rel)

    add("Page titles", not missing_title, f"{len(pages) - len(missing_title)}/{len(pages)} pages have a <title>", "major")
    add("Meta descriptions", not missing_desc, "All pages have 50–170 char descriptions" if not missing_desc else f"{len(missing_desc)} pages need attention", "minor", warn=True)
    add("Responsive viewport", not no_viewport, "Viewport meta on every page" if not no_viewport else f"Missing on {len(no_viewport)} pages", "major")
    css = build_dir / "assets" / "css" / "site.css"
    css_text = css.read_text(encoding="utf-8") if css.exists() else ""
    add("Responsive breakpoints", "@media" in css_text, f"{css_text.count('@media')} media queries", "minor")
    add("Single H1 per page", not bad_h1, "Heading structure OK" if not bad_h1 else f"{len(bad_h1)} pages without exactly one H1", "minor", warn=True)
    add("Language attribute", not no_lang, "lang set on <html>", "minor")
    add("Internal links & navigation", not broken_links, "All internal links resolve" if not broken_links else f"{len(broken_links)} broken: " + "; ".join(sorted(broken_links)[:4]), "critical")
    add("Images", not missing_imgs, "All images present" if not missing_imgs else f"Missing: {', '.join(sorted(missing_imgs)[:4])}", "major")
    add("Image alt attributes", no_alt == 0, "Every <img> has alt" if not no_alt else f"{no_alt} images without alt", "minor")
    add("Forms", bad_forms == 0, "Forms post to a handler" if not bad_forms else f"{bad_forms} forms misconfigured", "major")
    add("Page weight", not heavy, "All pages < 150KB HTML" if not heavy else f"Heavy pages: {', '.join(heavy[:3])}", "minor", warn=True)

    sm = build_dir / "sitemap.xml"
    sm_ok, sm_detail = False, "sitemap.xml missing"
    if sm.exists():
        try:
            urls = ET.parse(sm).getroot().findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url")
            sm_ok, sm_detail = len(urls) > 0, f"{len(urls)} URLs"
        except ET.ParseError as e:
            sm_detail = f"Invalid XML: {e}"
    add("Sitemap", sm_ok, sm_detail, "major")
    rb = build_dir / "robots.txt"
    add("robots.txt", rb.exists() and "Sitemap:" in rb.read_text(encoding="utf-8"), "Present with sitemap reference" if rb.exists() else "Missing", "major")

    leaks = []
    for f in build_dir.rglob("*"):
        if f.is_file() and f.suffix in (".html", ".js", ".css", ".json", ".txt", ".xml"):
            t = f.read_text(encoding="utf-8", errors="ignore")
            leaks += [f"{label} in {f.name}" for pat, label in SECRET_PATTERNS if re.search(pat, t)]
            leaks += [f"Provider credential in {f.name}" for s in secrets if s and len(s) >= 8 and s in t]
    add("No leaked credentials", not leaks, "No secrets found in public files" if not leaks else "; ".join(leaks[:3]), "critical")

    orig = state.get("originality", {})
    score = orig.get("score", 1.0)
    add("Content originality", score >= 0.6, f"{score * 100:.0f}% unique vs other sites" + (f" (closest: {orig['closest']})" if orig.get("closest") else ""), "major", warn=True)
    flags = state.get("content_review", {}).get("flags", [])
    add("Content review", not flags, "No unverifiable claims or placeholders" if not flags else f"{len(flags)} flagged: {flags[0]}", "minor", warn=True)

    penalty = sum(SEVERITY_PENALTY[c["severity"]] * (1 if c["status"] == "fail" else 0.3) for c in checks if c["status"] != "pass")
    critical = [c for c in checks if c["status"] == "fail" and c["severity"] == "critical"]
    return {
        "score": max(0, round(100 - penalty)),
        "passed": sum(c["status"] == "pass" for c in checks),
        "warnings": sum(c["status"] == "warn" for c in checks),
        "failed": sum(c["status"] == "fail" for c in checks),
        "critical_failures": [c["name"] for c in critical],
        "blocking": bool(critical),
        "pages": len(pages),
        "checks": checks,
    }

"""Fetch a user-provided reference website and extract *inspiration cues* from it — palette, fonts,
structure, topics and tone — never its text verbatim. The generated site takes ideas from these cues;
it does not copy the reference.

Safety: this fetches a URL the user typed, so it is SSRF-guarded. Every hostname (and every redirect hop)
must resolve only to public IP addresses — requests to localhost, private ranges, link-local and cloud
metadata endpoints are refused. The response is size-capped and only text/html is parsed.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from ..errors import ConfigurationError

MAX_BYTES = 800_000
TIMEOUT = 12
MAX_REDIRECTS = 4
UA = "SiteForgeBot/1.0 (+https://siteforge.local; reads a reference page for design inspiration)"


# ----------------------------------------------------------------------- SSRF guard
def _resolve_public(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        raise ConfigurationError(f"Reference site {host} could not be resolved", hint="Check the URL.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_reserved, ip.is_multicast, ip.is_unspecified)):
            raise ConfigurationError("That reference URL points to a private/internal address, which isn't allowed",
                                     hint="Use a public website URL.")


def _check_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ConfigurationError("Reference URL must start with http:// or https://")
    if not p.hostname:
        raise ConfigurationError("Reference URL has no host")
    _resolve_public(p.hostname)
    return url


# ----------------------------------------------------------------------- HTML parsing
class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.keywords = ""
        self.headings: list[str] = []
        self.nav: list[str] = []
        self.styles: list[str] = []          # inline <style> blocks + style="" attrs
        self.text_parts: list[str] = []
        self._stack: list[str] = []
        self._grab: str | None = None         # current heading/anchor tag being captured
        self._buf: list[str] = []
        self._skip = 0                         # inside script/style: don't collect visible text

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self._stack.append(tag)
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        if tag == "style":
            self._grab = "style"; self._buf = []
        if a.get("style"):
            self.styles.append(a["style"])
        if tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name in ("description", "og:description") and a.get("content") and not self.description:
                self.description = a["content"].strip()
            elif name == "keywords" and a.get("content"):
                self.keywords = a["content"].strip()
        if tag in ("h1", "h2", "h3") and len(self.headings) < 25:
            self._grab = "h"; self._buf = []
        elif tag == "a" and "nav" in " ".join(self._stack[-4:]) + " " + (a.get("class") or "") and len(self.nav) < 20:
            self._grab = "nav"; self._buf = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1
        text = "".join(self._buf).strip()
        if self._grab == "style" and tag == "style":
            self.styles.append(text)
        elif self._grab == "h" and tag in ("h1", "h2", "h3") and text:
            self.headings.append(text[:120])
        elif self._grab == "nav" and tag == "a" and text:
            self.nav.append(text[:40])
        if tag in ("style", "h1", "h2", "h3", "a"):
            self._grab = None; self._buf = []
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_data(self, data):
        if self._grab:
            self._buf.append(data)
        elif not self._skip and self._stack and self._stack[-1] not in ("title",):
            s = data.strip()
            if len(s) > 2 and len(self.text_parts) < 400:
                self.text_parts.append(s)
        if self._stack[-1:] == ["title"] and not self.title:
            self.title = data.strip()[:200]


HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
FONT = re.compile(r"font-family\s*:\s*([^;{}]+)", re.I)
GENERIC_FONTS = {"inherit", "initial", "unset", "sans-serif", "serif", "monospace", "system-ui", "-apple-system", "cursive", "fantasy"}


def _cues(html: str, final_url: str) -> dict:
    ex = _Extractor()
    try:
        ex.feed(html)
    except Exception:  # noqa: BLE001 — malformed markup must never break generation
        pass
    css = " ".join(ex.styles)
    palette: list[str] = []
    for h in HEX.findall(css):
        h = h.lower()
        if h not in palette and h not in ("#ffffff", "#000000"):
            palette.append(h)
    fonts: list[str] = []
    for fam in FONT.findall(css):
        first = fam.split(",")[0].strip().strip("'\"")
        if first and first.lower() not in GENERIC_FONTS and first not in fonts:
            fonts.append(first[:40])
    sample = " ".join(ex.text_parts)
    sample = re.sub(r"\s+", " ", sample).strip()[:1500]
    return {
        "url": final_url,
        "site": urlparse(final_url).hostname or final_url,
        "title": ex.title,
        "description": ex.description[:300],
        "headings": ex.headings[:20],
        "nav": list(dict.fromkeys(ex.nav))[:12],
        "palette": palette[:8],
        "fonts": fonts[:4],
        "keywords": [k.strip()[:40] for k in ex.keywords.split(",") if k.strip()][:12],
        "excerpt": sample,
    }


async def fetch_reference(url: str) -> dict:
    """Returns inspiration cues, or raises ConfigurationError for a bad/blocked URL."""
    url = _check_url(url.strip())
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False,
                                 headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}) as c:
        for _ in range(MAX_REDIRECTS):
            try:
                r = await c.get(url)
            except httpx.HTTPError as e:
                raise ConfigurationError(f"Couldn't fetch the reference site: {e.__class__.__name__}", hint="Check the URL is reachable.") from e
            if r.is_redirect and r.headers.get("location"):
                url = _check_url(urljoin(url, r.headers["location"]))
                continue
            break
        else:
            raise ConfigurationError("Reference site redirected too many times")
        if r.status_code >= 400:
            raise ConfigurationError(f"Reference site returned HTTP {r.status_code}")
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype.lower():
            raise ConfigurationError(f"Reference URL is not a web page (content-type {ctype or 'unknown'})")
        html = r.text[:MAX_BYTES]
    cues = _cues(html, str(r.url))
    if not (cues["title"] or cues["headings"] or cues["excerpt"]):
        raise ConfigurationError("Couldn't read any content from the reference site (it may require JavaScript)")
    return cues

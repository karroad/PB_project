"""Reference-website inspiration: the SSRF-safe fetcher, cue extraction, and that cues flow into the pipeline."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai import reference
from app.errors import ConfigurationError
from app.main import app
from tests.conftest import login, wait_job

SAMPLE_HTML = """
<html><head><title>Alpine Huts Collective</title>
<meta name="description" content="Mountain huts and high trails across the Alps.">
<meta name="keywords" content="alpine, huts, trails, mountaineering">
<style>:root{--brand:#1f6feb} body{font-family:'Spectral', serif; color:#0b2545}
.btn{background:#e8a33d;font-family:"Inter",sans-serif}</style></head>
<body><nav><a href="/">Home</a><a href="/huts">Huts</a><a href="/trails">Trails</a></nav>
<h1>Huts above the clouds</h1><h2>Plan your traverse</h2><h2>Season &amp; access</h2>
<p>Some descriptive paragraph about the high routes and the people who keep the huts.</p>
<script>var x=1;</script></body></html>
"""


def _route(monkeypatch, handler, public=True):
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw.pop("follow_redirects", None)
        return real(transport=httpx.MockTransport(handler), timeout=kw.get("timeout", 10),
                    headers=kw.get("headers"), follow_redirects=False)

    monkeypatch.setattr(reference.httpx, "AsyncClient", factory)
    if public:
        monkeypatch.setattr(reference, "_resolve_public", lambda host: None)


def test_reference_blocks_private_and_loopback(monkeypatch):
    import socket
    for addr in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1"):
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, _addr=addr, **k: [(2, 1, 6, "", (_addr, 0))])
        with pytest.raises(ConfigurationError, match="private|internal"):
            import asyncio
            asyncio.run(reference.fetch_reference("http://internal-service/"))


def test_reference_requires_http_scheme():
    import asyncio
    with pytest.raises(ConfigurationError, match="http"):
        asyncio.run(reference.fetch_reference("ftp://files.example.com/x"))


def test_reference_extracts_palette_fonts_structure(monkeypatch):
    _route(monkeypatch, lambda req: httpx.Response(200, text=SAMPLE_HTML, headers={"content-type": "text/html; charset=utf-8"}))
    import asyncio
    cues = asyncio.run(reference.fetch_reference("https://huts.example"))
    assert cues["title"] == "Alpine Huts Collective"
    assert cues["description"].startswith("Mountain huts")
    assert "#1f6feb" in cues["palette"] and "#e8a33d" in cues["palette"]  # brand colours, not #fff/#000
    assert "Spectral" in cues["fonts"] and "Inter" in cues["fonts"]  # generic families (serif/sans-serif) dropped
    assert "Huts above the clouds" in cues["headings"] and "Plan your traverse" in cues["headings"]
    assert "Huts" in cues["nav"] and "Trails" in cues["nav"]
    assert "alpine" in cues["keywords"]


def test_reference_rejects_non_html(monkeypatch):
    _route(monkeypatch, lambda req: httpx.Response(200, text="{}", headers={"content-type": "application/json"}))
    import asyncio
    with pytest.raises(ConfigurationError, match="not a web page"):
        asyncio.run(reference.fetch_reference("https://api.example/data.json"))


def test_reference_follows_and_revalidates_redirects(monkeypatch):
    def handler(req):
        if req.url.host == "start.example":
            return httpx.Response(301, headers={"location": "https://final.example/home"})
        return httpx.Response(200, text=SAMPLE_HTML, headers={"content-type": "text/html"})

    _route(monkeypatch, handler)
    import asyncio
    cues = asyncio.run(reference.fetch_reference("https://start.example"))
    assert cues["site"] == "final.example"


def test_website_build_uses_reference(asgi_http, monkeypatch):
    """Creating a site with a reference URL: cues bias the brand palette/fonts and show in the requirements step."""
    async def fake(url):
        return {"url": url, "site": "huts.example", "title": "Alpine Huts Collective",
                "description": "Mountain huts.", "headings": ["Huts above the clouds", "Plan your traverse"],
                "nav": ["Huts", "Trails"], "palette": ["#1f6feb", "#e8a33d", "#0b2545"],
                "fonts": ["Spectral", "Inter"], "keywords": ["alpine", "huts"], "excerpt": "high routes"}
    monkeypatch.setattr("app.agents.pipeline_agents.fetch_reference", fake)
    with TestClient(app) as client:
        h = login(client)
        r = client.post("/api/websites", headers=h, json={"prompt": "A website about alpine hiking huts and trails",
                                                           "stack": "static", "reference_url": "huts.example"})
        assert r.status_code == 201, r.text
        site_id = r.json()["website"]["id"]
        assert r.json()["website"]["id"]  # reference_url normalised to https:// and stored
        j = wait_job(client, h, r.json()["job"]["id"], statuses=("completed", "failed"))
        assert j["status"] == "completed", [(s["key"], s["error"]) for s in j["steps"]]
        site = client.get(f"/api/websites/{site_id}", headers=h).json()["website"]
        assert site["config"]["reference_url"] == "https://huts.example"
        brand = site["config"]["brand"]
        assert brand["palette"]["primary"] == "#1f6feb"  # seeded from the reference
        assert brand["fonts"]["heading"] == "Spectral"
        req_step = next(s for s in j["steps"] if s["key"] == "requirements")
        assert any("huts.example" in str(hl).lower() for hl in req_step.get("output", {}).get("highlights", []))

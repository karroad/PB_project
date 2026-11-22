"""The AI site builder: the code model writes the design + pages, and dangling links/images are repaired
so the build always passes the hard quality gate. The model call is faked (no network)."""
import asyncio

import pytest

from app.agents.quality import run_checks
from app.ai import offline, site_builder

DESIGN = """===CSS===
:root{--primary:#1f6feb}body{font-family:system-ui;margin:0}
.wrap{max-width:1100px;margin:0 auto;padding:0 20px}
@media (min-width:700px){.grid{display:grid;grid-template-columns:1fr 1fr}}
@media (min-width:1000px){.grid{grid-template-columns:repeat(3,1fr)}}
===FONTS===
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter&display=swap">
===BODYCLASS===
theme-editorial
===HEADER===
<header class="wrap"><a href="{{ROOT}}">{{BRAND}}</a><button data-nav-toggle="nav">Menu</button><nav id="nav"></nav></header>
===FOOTER===
<footer class="wrap"><p>© {{YEAR}} {{BRAND}}</p></footer>
===CLASSES===
wrap, grid, btn, card
===NOTES===
Editorial, generous whitespace, two-column features
"""


def _fake_page(title):
    # one valid link (home), one dangling link (ghost/), one missing image — both must be repaired
    return (f"<section class='wrap'><h1>{title}</h1><p>Original copy here.</p>"
            "<a href='{{ROOT}}'>Home</a> <a href='{{ROOT}}ghost/'>Ghost</a>"
            "<img src='{{ROOT}}assets/media/missing.png' alt='pic'></section>")


async def _fake_complete(system, prompt):
    return DESIGN if "Design the visual system" in prompt else _fake_page("A Page")


def _spec(tmp_path, prompt="A website about alpine hiking huts and trails"):
    req = offline.requirements(prompt, "static")
    plan = offline.plan(req, "static")
    brand = offline.brand(req)
    content = offline.content(req, plan, brand)
    seo = offline.seo(req, plan, brand, content)
    media = tmp_path / "media"
    media.mkdir()
    (media / "logo.svg").write_text("<svg/>")
    (media / "hero.png").write_bytes(b"\x89PNG\r\n")
    images = {"logo": "assets/media/logo.svg", "hero": "assets/media/hero.png", "articles": {a["slug"]: "assets/media/hero.png" for a in content["articles"]}}
    return {"requirements": req, "plan": plan, "brand": brand, "content": content, "seo": seo, "images": images,
            "slug": "alpine-huts", "base_url": "http://preview.local/", "domain": None, "reference": None}, media


def test_ai_build_passes_quality_and_repairs_links(tmp_path, monkeypatch):
    monkeypatch.setattr(site_builder, "complete_code", _fake_complete)
    spec, media = _spec(tmp_path)
    build = tmp_path / "build"

    async def log(msg, progress=None):
        pass

    files = asyncio.run(site_builder.build_ai_site(spec, build, media, "http://preview.local/", "alpine-huts", log))
    assert "index.html" in files and "assets/css/site.css" in files
    css = (build / "assets/css/site.css").read_text()
    assert "@media" in css and "--primary" in css  # the model's own stylesheet, not the template

    index = (build / "index.html").read_text()
    assert "ghost/" not in index          # dangling link repaired
    assert "missing.png" not in index     # missing image repaired to the hero
    assert "<title>" in index and 'name="viewport"' in index and 'lang="' in index  # head owned by us

    res = run_checks(build, {}, [])
    assert res["blocking"] is False, res["critical_failures"]
    links = next(c for c in res["checks"] if c["name"] == "Internal links & navigation")
    assert links["status"] == "pass", links
    assert (build / "404.html").exists() and (build / "contact/thanks/index.html").exists()
    assert (build / "sitemap.xml").exists() and (build / "robots.txt").exists()


def test_ai_build_raises_when_design_incomplete(tmp_path, monkeypatch):
    async def bad(system, prompt):
        return "===CSS===\n/* only css, no header/footer */"
    monkeypatch.setattr(site_builder, "complete_code", bad)
    spec, media = _spec(tmp_path)

    async def log(msg, progress=None):
        pass

    from app.ai.llm import LLMError
    with pytest.raises(LLMError):
        asyncio.run(site_builder.build_ai_site(spec, tmp_path / "b", media, "http://preview.local/", "x", log))

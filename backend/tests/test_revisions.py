"""Change requests ("comments") on a built website: applied, rebuilt, tested, redeployed, reversible."""
import json

from fastapi.testclient import TestClient

from app.agents.revision import Interpreter, _affected_pages, _apply_seo_lines, diff_paths
from app.ai import llm
from app.main import app
from tests.conftest import login, make_live, publish, wait_job


def _live_site(client, h, prompt="A website about sustainable living at home"):
    return make_live(client, h, prompt)


def test_offline_change_request_end_to_end(asgi_http):
    with TestClient(app) as client:
        h = login(client)
        site = _live_site(client, h)
        comment = ('Change the headline to "Live lighter, waste less"\n'
                   "Make the primary colour #0f766e\n"
                   "Use a dark theme\n"
                   'Add FAQ "Do you ship abroad?" answer "Yes, to 30 countries."\n'
                   'Add an article about "composting in small apartments"\n'
                   "Remove the FAQ page from the menu")
        r = client.post(f"/api/websites/{site['id']}/changes", headers=h, json={"instruction": comment})
        assert r.status_code == 200, r.text
        job = r.json()
        assert [s["key"] for s in job["steps"]] == ["revise", "development", "testing", "preview"]
        j = wait_job(client, h, job["id"], statuses=("completed", "failed"))
        assert j["status"] == "completed", [(s["key"], s["error"]) for s in j["steps"]]

        cfg = client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]["config"]
        assert cfg["content"]["home"]["hero_title"] == "Live lighter, waste less"
        assert cfg["brand"]["palette"]["primary"] == "#0f766e" and cfg["brand"]["palette"]["background"] == "#0b1020"
        assert cfg["content"]["faq"][-1]["q"] == "Do you ship abroad?"
        assert cfg["content"]["articles"][0]["title"].startswith("Composting In Small Apartments")
        assert all(p["slug"] != "faq" for p in cfg["plan"]["sitemap"])
        rev = cfg["revisions"][-1]
        assert rev["n"] == 1 and len(rev["summary"]) == 6

        # the change lands on the PREVIEW first; the live site is untouched until publishing
        preview = client.get(f"/preview/{site['slug']}/").text
        assert "Live lighter, waste less" in preview and 'href="faq/"' not in preview.split("<main")[0]  # gone from the menu
        assert "Live lighter, waste less" not in client.get(f"/sites/{site['slug']}/").text
        css = client.get(f"/preview/{site['slug']}/assets/css/site.css").text
        assert "--primary:#0f766e" in css and "--bg:#0b1020" in css
        new_slug = cfg["content"]["articles"][0]["slug"]
        assert client.get(f"/preview/{site['slug']}/blog/{new_slug}/").status_code == 200  # new article page + image built
        assert client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]["status"] == "live"

        assert publish(client, h, site["id"])["status"] == "completed"
        assert "Live lighter, waste less" in client.get(f"/sites/{site['slug']}/").text
        deps = client.get(f"/api/websites/{site['id']}/deployments", headers=h).json()
        assert [d["version"] for d in deps] == [2, 1]  # published change = new, reversible version
        revs = client.get(f"/api/websites/{site['id']}/revisions", headers=h).json()
        assert revs["revisions"][0]["instruction"].startswith("Change the headline") and revs["examples"]


def test_unclear_request_fails_safely_and_site_stays_live(asgi_http):
    with TestClient(app) as client:
        h = login(client)
        site = _live_site(client, h, "A website about urban beekeeping")
        r = client.post(f"/api/websites/{site['id']}/changes", headers=h, json={"instruction": "make it feel more premium somehow"})
        j = wait_job(client, h, r.json()["id"], statuses=("completed", "failed"))
        revise = j["steps"][0]
        assert j["status"] == "failed" and revise["output"]["error"]["code"] == "revision_not_understood"
        assert "ANTHROPIC_API_KEY" in revise["output"]["error"]["hint"]
        after = client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]
        assert after["status"] == "live" and client.get(f"/sites/{site['slug']}/").status_code == 200
        assert client.post(f"/api/websites/{site['id']}/changes", headers=h, json={"instruction": "x"}).status_code == 422


class EditorProvider(llm.TextProvider):
    """Fake AI editor: rewrites the tagline and FAQ like a model would, returning the full spec."""
    name, offline = "fake-ai", False

    async def complete(self, system, prompt):
        if "Website editor" not in system:
            return "{}"  # other agents: keep built-in output
        spec = json.loads(prompt.split("Return JSON with exactly this shape (values are examples to improve on):\n", 1)[1])
        spec["brand"]["tagline"] = "Friendly help for busy beekeepers."
        spec["content"]["faq"].insert(0, {"q": "How much honey does one hive make?", "a": "It varies a lot by season and location."})
        spec["summary"] = ["Friendlier tagline", "Added a FAQ about honey yield"]
        return json.dumps(spec)


def test_ai_change_request(asgi_http, monkeypatch):
    monkeypatch.setattr(llm, "_provider", EditorProvider())
    with TestClient(app) as client:
        h = login(client)
        site = _live_site(client, h, "A website about backyard beekeeping")
        r = client.post(f"/api/websites/{site['id']}/changes", headers=h, json={"instruction": "Make the tagline friendlier and add a FAQ about honey yield"})
        j = wait_job(client, h, r.json()["id"], statuses=("completed", "failed"))
        assert j["status"] == "completed", [(s["key"], s["error"]) for s in j["steps"]]
        cfg = client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]["config"]
        assert cfg["brand"]["tagline"] == "Friendly help for busy beekeepers."
        assert cfg["revisions"][-1]["summary"] == ["Friendlier tagline", "Added a FAQ about honey yield"]
        assert "brand.tagline" in cfg["revisions"][-1]["changed"]


def test_seo_structured_edit_end_to_end(asgi_http):
    """Regression test: editing an SEO field must update ONLY seo.pages, never misfire into the
    headline/tagline/etc — and must be recognised as not needing any page re-coded."""
    with TestClient(app) as client:
        h = login(client)
        site = _live_site(client, h, "A website about backyard beekeeping")
        before = client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]["config"]
        original_hero = before["content"]["home"]["hero_title"]

        instruction = 'SEO title for page "": Bee Calm — Backyard Beekeeping Made Simple'
        r = client.post(f"/api/websites/{site['id']}/changes", headers=h, json={"instruction": instruction})
        assert r.status_code == 200, r.text
        j = wait_job(client, h, r.json()["id"], statuses=("completed", "failed"))
        assert j["status"] == "completed", [(s["key"], s["error"]) for s in j["steps"]]

        cfg = client.get(f"/api/websites/{site['id']}", headers=h).json()["website"]["config"]
        assert cfg["seo"]["pages"][""]["title"] == "Bee Calm — Backyard Beekeeping Made Simple"
        assert cfg["content"]["home"]["hero_title"] == original_hero  # untouched — this is the bug that was fixed
        assert cfg["revisions"][-1]["changed"] == ["seo.pages..title"]


def test_apply_seo_lines_handles_empty_page_key_and_multiline_values():
    seo = {"pages": {}}
    remaining, done = _apply_seo_lines(seo, 'SEO title for page "": New Title\nSEO description for page "about": A longer description. With two sentences.')
    assert remaining.strip() == ""
    assert seo["pages"][""]["title"] == "New Title"
    assert seo["pages"]["about"]["description"] == "A longer description. With two sentences."
    assert len(done) == 2


def test_quoted_text_regex_matches_empty_string_not_later_text():
    """The old `.+?` quantifier required at least one char, so an empty "" pair was skipped and
    paired with a later, unrelated quote instead — this is the exact bug that corrupted a field."""
    from app.agents.revision import Q
    import re
    m = re.search(Q, 'pages[""].title to "Some Real Value"')
    assert m.group(1) == ""  # the adjacent empty quotes, not "].title to "


def test_affected_pages_scoping():
    assert _affected_pages(["seo.pages..title"]) == []
    assert _affected_pages(["content.home.hero_title", "content.contact.email"]) == ["", "contact"]
    assert _affected_pages(["content.articles"]) is None  # new/changed article: unsafe, full rebuild
    assert _affected_pages(["brand.palette.primary"]) is None  # design change: unsafe, full rebuild


def test_interpreter_units():
    spec = {"brand": {"name": "A", "tagline": "t", "palette": {"primary": "#111111", "secondary": "#222222", "accent": "#333333", "background": "#ffffff",
                                                               "surface": "#ffffff", "text": "#000000", "muted": "#555555"}, "fonts": {"heading": "Inter", "body": "Inter"}},
            "content": {"home": {"hero_title": "x", "hero_subtitle": "y", "cta_primary": "z"}, "contact": {"email": "a@b.co"}, "faq": [], "articles": [], "about": {"intro": ""}},
            "plan": {"sitemap": [{"slug": ""}, {"slug": "about"}]}}
    before = json.loads(json.dumps(spec))
    unknown = Interpreter(spec).apply('Use Playfair Display for headings; rename to "Bee Calm"; set contact email to hi@beecalm.co; make it navy. Do a backflip')
    assert spec["brand"]["fonts"]["heading"] == "Playfair Display" and spec["brand"]["name"] == "Bee Calm"
    assert spec["content"]["contact"]["email"] == "hi@beecalm.co" and spec["brand"]["palette"]["primary"] == "#1e3a8a"
    assert unknown == ["Do a backflip"]
    assert set(diff_paths(before, spec)) == {"brand.fonts.heading", "brand.name", "content.contact.email", "brand.palette.primary"}

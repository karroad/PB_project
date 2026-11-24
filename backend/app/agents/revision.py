"""Revision Agent: applies a user's change request ("comment") to an existing website.

* With an AI provider: any free-form instruction ("make the tone friendlier, add a FAQ about
  shipping, use a darker green") is applied by the model to the site spec.
* Offline: a built-in interpreter understands common edits (colours, dark/light theme, fonts,
  headline/subtitle/tagline/name/button/email, add/remove FAQ, add/remove article, hide pages).
* SEO metadata (the SEO tab's Save button): a structured 'SEO <FIELD> for page "<slug>": <value>'
  line per field, applied deterministically regardless of AI availability — no model call needed.

The edited spec is then rebuilt, re-tested and redeployed as a new version by the normal
development → testing → deployment → verify steps, so every change can be rolled back.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone

from ..ai import offline
from ..ai.images import generate_image
from ..errors import PipelineError
from .base import Agent, StepContext, chips, kv

COLOR_NAMES = {
    "blue": "#2563eb", "navy": "#1e3a8a", "sky": "#0ea5e9", "teal": "#0d9488", "cyan": "#0891b2", "green": "#16a34a",
    "emerald": "#059669", "olive": "#4d7c0f", "lime": "#65a30d", "yellow": "#ca8a04", "gold": "#d4a017", "orange": "#ea580c",
    "red": "#dc2626", "crimson": "#be123c", "pink": "#db2777", "rose": "#e11d48", "purple": "#7c3aed", "violet": "#8b5cf6",
    "brown": "#7c5c45", "black": "#111111", "gray": "#4b5563", "grey": "#4b5563", "white": "#ffffff",
}
COLOR = r"(#[0-9a-fA-F]{6}\b|" + "|".join(COLOR_NAMES) + r")"
SLOT = {"primary": "primary", "main": "primary", "brand": "primary", "accent": "accent", "secondary": "secondary",
        "background": "background", "bg": "background", "text": "text", "surface": "surface", "button": "primary", "link": "primary"}
DARK = {"background": "#0b1020", "surface": "#131b34", "text": "#e6e9f5", "muted": "#94a3b8"}
LIGHT = {"background": "#f8fafc", "surface": "#ffffff", "text": "#0f172a", "muted": "#64748b"}
PAGES = {"about": "about", "services": "services", "offer": "services", "blog": "blog", "journal": "blog", "faq": "faq", "contact": "contact", "shop": "shop"}
Q = r"[\"“”'‘’](.*?)[\"“”'‘’]"  # quoted text — .*? (not .+?) so an empty "" pair matches itself
# rather than being skipped over, which would otherwise pair with a later, unrelated quote.

# Structured SEO field edits (what the SEO tab's Save button sends): parsed deterministically and
# unconditionally — never through the free-text AI or the generic setters below — so editing a meta
# title/description/keywords can never be misread as an edit to the headline, tagline, etc., and never
# needs an AI call (metadata text is plain strings, there is nothing for a model to usefully add).
_SEO_LINE = re.compile(r'(?im)^[ \t]*seo[ \t]+(title|description|keywords)[ \t]+for[ \t]+page[ \t]+"([^"]*)"[ \t]*:[ \t]*(.*?)[ \t]*$')


def _apply_seo_lines(seo: dict, instruction: str) -> tuple[str, list[str]]:
    """Applies every 'SEO <FIELD> for page "<slug>": <value>' line directly to seo['pages'][slug],
    and returns (remaining_instruction_with_those_lines_removed, human-readable summaries)."""
    done: list[str] = []

    def _take(m: re.Match) -> str:
        field, slug, value = m.group(1).lower(), m.group(2), m.group(3).strip()
        page = seo.setdefault("pages", {}).setdefault(slug, {})
        if field == "keywords":
            page["keywords"] = [k.strip() for k in value.split(",") if k.strip()]
            done.append(f"SEO keywords for “{slug or 'Home'}” → {value}")
        else:
            page[field] = value
            done.append(f"SEO {field} for “{slug or 'Home'}” → “{value}”")
        return ""

    return _SEO_LINE.sub(_take, instruction), done


# Content fields that are each confined to exactly one known page's body, so a change to them can
# be rebuilt by re-rendering only that page instead of the whole site. Anything else (brand, palette,
# fonts, plan/sitemap, articles, products, images) can ripple into the shared design or several pages,
# so it is deliberately left out — those fall back to a full, safe rebuild.
_SAFE_CONTENT_PAGE = {"content.home": "", "content.about": "about", "content.services": "services",
                      "content.contact": "contact", "content.faq": "faq"}


def _affected_pages(changed: list[str]) -> list[str] | None:
    """Which page(s) need their body re-rendered for this diff, or None if the rest of the
    rebuild can't safely be skipped (an unrecognised/structural field changed)."""
    pages: set[str] = set()
    for p in changed:
        if p.startswith("seo."):
            continue  # SEO metadata is assembled locally at render time, never needs a body re-render
        hit = next((key for prefix, key in _SAFE_CONTENT_PAGE.items() if p == prefix or p.startswith(prefix + ".")), None)
        if hit is None:
            return None
        pages.add(hit)
    return sorted(pages)

EXAMPLES = [
    'Change the headline to "Live lighter, waste less"',
    "Make the primary colour dark green",
    "Use a dark theme",
    'Add FAQ "Do you ship abroad?" answer "Yes, to 30 countries."',
    'Add an article about "composting in small apartments"',
    "Remove the FAQ page from the menu",
    'Change the tagline to "Small steps, big impact."',
    "Use Playfair Display for headings",
]


def _hex(token: str) -> str:
    t = token.lower()
    return t if t.startswith("#") else COLOR_NAMES[t]


def _flatten(d, prefix=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(d, list):
        out[prefix] = json.dumps(d, sort_keys=True, ensure_ascii=False)[:2000]
    else:
        out[prefix] = d
    return out


def diff_paths(before: dict, after: dict) -> list[str]:
    a, b = _flatten(before), _flatten(after)
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


class Interpreter:
    """Deterministic interpreter for common change requests (works without any AI key)."""

    def __init__(self, spec: dict):
        self.s = spec
        self.done: list[str] = []
        self.new_articles: list[dict] = []

    def apply(self, instruction: str) -> list[str]:
        parts = [p.strip() for p in re.split(r"[\n;]+|(?<=[.!?])\s+(?=[A-Z])", instruction) if p.strip()]
        unknown = []
        for part in parts:
            if not self._one(part):
                unknown.append(part)
        return unknown

    def _set(self, path: str, value, label: str):
        node = self.s
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
        self.done.append(label)

    def _one(self, text: str) -> bool:  # noqa: C901 — a flat list of rules reads best
        t = text.strip().rstrip(".")
        low = t.lower()
        pal = self.s["brand"]["palette"]

        if re.search(r"\b(dark (mode|theme|background|design)|make it dark|darker theme)\b", low):
            pal.update(DARK); self.done.append("Dark theme"); return True
        if re.search(r"\b(light (mode|theme|background|design)|make it light|lighter theme)\b", low):
            pal.update(LIGHT); self.done.append("Light theme"); return True
        m = re.search(r"\b(primary|main|brand|accent|secondary|background|bg|text|surface|button|link)\s*(?:colou?r)?\s*(?:to|=|:|should be|into)?\s*(?:a\s+)?(?:dark\s+|deep\s+)?" + COLOR, low)
        if m and ("colo" in low or "make" in low or "change" in low or "set" in low or "use" in low):
            slot = SLOT[m.group(1)]
            pal[slot] = _hex(m.group(2)); self.done.append(f"{slot.capitalize()} colour → {pal[slot]}"); return True
        m = re.search(r"\b(?:make it|colou?rs? (?:to|should be)|change (?:the )?colou?rs? to|use)\s+(?:a\s+)?(?:dark\s+|deep\s+)?" + COLOR + r"\b", low)
        if m:
            pal["primary"] = _hex(m.group(1)); self.done.append(f"Primary colour → {pal['primary']}"); return True

        m = re.search(r"\buse\s+(.+?)\s+(?:font\s+)?for\s+(headings?|titles?|body|text|everything)\b", t, re.I) or \
            re.search(r"\b(heading|title|body|text)s?\s+font\s*(?:to|=|:)?\s*[\"“']?([A-Za-z0-9 ]{3,40}?)[\"”']?$", t, re.I)
        if m:
            if m.re.pattern.startswith(r"\buse"):
                font, target = m.group(1).strip(" \"'“”"), m.group(2).lower()
            else:
                target, font = m.group(1).lower(), m.group(2).strip()
            font = " ".join(w.capitalize() if w.islower() else w for w in font.split())
            if target.startswith(("heading", "title", "everything")):
                self.s["brand"]["fonts"]["heading"] = font
            if target.startswith(("body", "text", "everything")):
                self.s["brand"]["fonts"]["body"] = font
            self.done.append(f"Font for {target} → {font}"); return True

        setters = [
            (r"\b(?:hero title|headline|main heading|hero heading)\b", "content.home.hero_title", "Headline"),  # bare "title" excluded: too easily confused with an SEO/meta title edit
            (r"\b(?:subtitle|subheading|sub-heading|hero text|intro text)\b", "content.home.hero_subtitle", "Subtitle"),
            (r"\btagline|slogan\b", "brand.tagline", "Tagline"),
            (r"\b(?:button|call to action|cta)\b", "content.home.cta_primary", "Main button"),
            (r"\b(?:about (?:intro|text))\b", "content.about.intro", "About intro"),
        ]
        for pat, path, label in setters:
            if re.search(pat, low):
                q = re.search(Q, t)
                if q:
                    self._set(path, q.group(1).strip(), f"{label} → “{q.group(1).strip()}”"); return True
        m = re.search(r"\b(?:rename(?: the site)?(?: to)?|(?:site|website|brand) name\s*(?:to|=|:)?)\s*" + Q, t, re.I)
        if m:
            self._set("brand.name", m.group(1).strip(), f"Name → “{m.group(1).strip()}”"); return True
        m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", t)
        if m and "email" in low:
            self._set("content.contact.email", m.group(0), f"Contact email → {m.group(0)}"); return True

        m = re.search(r"\badd (?:a |an |new )?(?:faq|question)\b.*?" + Q + r".*?(?:answer|a:|->|with)\s*" + Q, t, re.I)
        if m:
            self.s["content"]["faq"].append({"q": m.group(1).strip(), "a": m.group(2).strip()})
            self.done.append(f"Added FAQ “{m.group(1).strip()}”"); return True
        m = re.search(r"\b(?:remove|delete) (?:the )?(?:faq|question)\b.*?" + Q, t, re.I)
        if m:
            before = len(self.s["content"]["faq"])
            self.s["content"]["faq"] = [f for f in self.s["content"]["faq"] if m.group(1).lower() not in f["q"].lower()]
            if len(self.s["content"]["faq"]) < before:
                self.done.append(f"Removed FAQ “{m.group(1)}”"); return True

        m = re.search(r"\badd (?:a |an |new )?(?:article|blog post|post)\s+(?:about|on|titled|called)\s+[\"“']?(.+?)[\"”']?$", t, re.I)
        if m:
            subject = m.group(1).strip()
            titled = re.search(r"\b(titled|called)\b", low)
            title = offline.title_case(subject) if titled else f"{offline.title_case(subject)}: A Practical Guide"
            r = offline.rng_for(title, "revision")
            body = [p.format(T=offline.title_case(subject), t=subject) for p in r.sample(offline._PARA, 5)]
            art = {"slug": offline.slugify(title), "title": title, "category": "Guides", "excerpt": body[0][:150].rsplit(" ", 1)[0] + "…",
                   "body": body, "read_minutes": 4, "image_prompt": f"Editorial image about {subject}"}
            if any(a["slug"] == art["slug"] for a in self.s["content"]["articles"]):
                art["slug"] += "-2"
            self.s["content"]["articles"].insert(0, art)
            self.new_articles.append(art)
            self.done.append(f"Added article “{title}”"); return True
        m = re.search(r"\b(?:remove|delete) (?:the )?(?:article|post|blog post)\b.*?" + Q, t, re.I)
        if m:
            before = len(self.s["content"]["articles"])
            self.s["content"]["articles"] = [a for a in self.s["content"]["articles"] if m.group(1).lower() not in a["title"].lower()]
            if not self.s["content"]["articles"]:
                raise PipelineError("A site needs at least one article", code="revision_invalid")
            if len(self.s["content"]["articles"]) < before:
                self.done.append(f"Removed article matching “{m.group(1)}”"); return True

        m = re.search(r"\b(?:remove|hide|delete) (?:the )?(" + "|".join(PAGES) + r")\b", low)
        if m and ("page" in low or "menu" in low or "nav" in low or "section" in low):
            slug = PAGES[m.group(1)]
            before = len(self.s["plan"]["sitemap"])
            self.s["plan"]["sitemap"] = [p for p in self.s["plan"]["sitemap"] if p["slug"] != slug]
            if len(self.s["plan"]["sitemap"]) < before:
                self.done.append(f"Removed “{m.group(1)}” from the menu"); return True
        return False


async def _ensure_images(ctx: StepContext, spec: dict) -> int:
    """Every article needs an image; create one for new/renamed articles."""
    imgs = spec.setdefault("images", {}).setdefault("articles", {})
    created = 0
    for a in spec["content"]["articles"]:
        if a["slug"] not in imgs:
            key = ctx.recorder.provider_secret("fal", "api_key")
            path, _ = await generate_image(a.get("image_prompt") or a["title"], ctx.site.media_dir / f"article-{a['slug']}", spec["brand"]["palette"], key)
            imgs[a["slug"]] = f"assets/media/{path.name}"
            created += 1
    return created


class RevisionAgent(Agent):
    key, title, agent_name = "revise", "Apply requested changes", "Revision Agent"
    description = "Applies your comment to the website's design and content."

    async def run(self, ctx: StepContext) -> dict:
        instruction = (ctx.params or {}).get("instruction", "").strip()
        if not instruction:
            raise PipelineError("No change request was provided", code="revision_empty")
        if "content" not in ctx.state:
            raise PipelineError("Generate the website before requesting changes", code="revision_no_site")
        await ctx.log(f"Change request: “{instruction[:160]}”", progress=10)
        editable = {k: copy.deepcopy(ctx.state[k]) for k in ("brand", "content", "seo", "plan") if k in ctx.state}
        before = copy.deepcopy(editable)

        # Structured SEO field edits are deterministic and need no AI — apply them first, unconditionally,
        # and only send whatever text is left (if any) through the offline interpreter / AI below.
        remaining, summary_lines = _apply_seo_lines(editable.setdefault("seo", {}), instruction)
        remaining = remaining.strip()

        if not remaining:
            pass  # the whole instruction was structured SEO edits — nothing else to interpret
        elif ctx.offline:
            interp = Interpreter(editable)
            unknown = interp.apply(remaining)
            if not interp.done and not summary_lines:
                raise PipelineError("Couldn't understand this change without an AI provider", code="revision_not_understood",
                                    hint="Add ANTHROPIC_API_KEY for free-form changes, or use a supported format, e.g. " + " · ".join(EXAMPLES[:4]))
            for u in unknown:
                await ctx.log(f"Skipped (not understood offline): “{u[:120]}”", level="warning")
            summary_lines += interp.done
        else:
            await ctx.log("Asking the AI to apply the change", progress=30)
            result = await ctx.ai_json(
                "Website editor",
                "Apply the user's change request to this website spec. Change ONLY what the request asks for and keep "
                "everything else identical. Keep the same JSON structure, keys and types. New articles need a unique slug, "
                "title, category, excerpt, 5-paragraph body and read_minutes. Also return 'summary': a list of short "
                "human-readable descriptions of what you changed.\n\nChange request: " + remaining,
                {**editable, "summary": ["…"]}, limit=250_000)  # the editor must see the whole site
            summary_lines += [s for s in result.pop("summary", []) if isinstance(s, str) and s != "…"]
            for k in editable:
                editable[k] = result.get(k, editable[k])
            for a in editable["content"].get("articles", []):
                a["slug"] = offline.slugify(a.get("slug") or a.get("title", "article"))
            known = {p["slug"] for p in before["plan"]["sitemap"]}
            editable["plan"]["sitemap"] = [p for p in editable["plan"]["sitemap"] if p.get("slug") in known] or before["plan"]["sitemap"]
            if not diff_paths(before, editable):  # AI unavailable or made no edit: try the built-in interpreter
                interp = Interpreter(editable)
                interp.apply(instruction)
                if interp.done:
                    await ctx.log("Applied with the built-in editor", level="warning")
                    summary_lines = interp.done

        for k, v in list(editable["brand"]["palette"].items()):
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(v)):
                editable["brand"]["palette"][k] = before["brand"]["palette"].get(k, "#333333")
        changed = diff_paths(before, editable)
        if not changed:
            raise PipelineError("The request didn't change anything", code="revision_no_change", hint="Rephrase the request more specifically.")
        # Tell the rebuild step exactly which page(s) actually need their body re-rendered by the code
        # model — a plain text edit (headline, subtitle, tagline button, contact info, FAQ, SEO meta)
        # only ever affects one known page (or none, for SEO), so there is no need to re-prompt the
        # model for every other page's unchanged code. None means "can't tell, rebuild everything"
        # (e.g. a new article, a design/colour/font change, or an AI-driven free-form edit).
        ctx.state["revision_affected_pages"] = _affected_pages(changed)

        # keep SEO in step with renamed brand / new articles
        if editable["brand"]["name"] != before["brand"]["name"] or len(editable["content"]["articles"]) != len(before["content"]["articles"]):
            fresh = offline.seo(ctx.state["requirements"], editable["plan"], editable["brand"], editable["content"])
            for key, meta in fresh["pages"].items():
                editable["seo"]["pages"].setdefault(key, meta)
            if editable["brand"]["name"] != before["brand"]["name"]:
                editable["seo"]["pages"][""] = fresh["pages"][""]
                ctx.update_site(name=editable["brand"]["name"])

        for k, v in editable.items():
            ctx.state[k] = v
        made = await _ensure_images(ctx, ctx.state)
        if made:
            await ctx.log(f"Created {made} image(s) for new articles")
        for line in summary_lines:
            await ctx.log(f"✓ {line}", level="success")

        rev = {"n": len(ctx.state.get("revisions", [])) + 1, "instruction": instruction[:2000], "summary": summary_lines or [f"{len(changed)} fields changed"],
               "changed": changed[:40], "job_id": ctx.recorder.job.id, "by": ctx.recorder.job.created_by,
               "at": datetime.now(timezone.utc).isoformat()}
        ctx.state["revisions"] = [*ctx.state.get("revisions", []), rev][-50:]
        await ctx.log(f"Revision #{rev['n']}: {len(changed)} field(s) updated — rebuilding", level="success", progress=100)
        return {"summary": "; ".join(rev["summary"])[:300], "highlights": [chips("Changes", rev["summary"][:10]),
                                                                          kv(("Fields changed", len(changed)), ("Revision", f"#{rev['n']}"))]}

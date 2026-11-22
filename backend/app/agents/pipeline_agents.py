"""The specialised agents that make up the website generation pipeline."""
from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import time

import httpx

from ..adapters.dns import DomainOrderRejected, DomainOrderUncertain, get_dns, rdap_lookup
from ..adapters.hosting import get_hosting
from ..adapters.stacks import STACKS, get_stack
from ..ai import offline
from ..ai.images import generate_image, svg_logo
from ..ai.llm import get_code_provider
from ..ai.reference import fetch_reference
from ..ai.site_builder import build_ai_site
from ..config import settings
from ..errors import ConfigurationError, PipelineError, QualityGateError, RetryableError
from .base import Agent, StepContext, chips, kv
from .quality import run_checks


def media_url(slug: str, rel: str) -> str:
    return f"/api/media/{slug}/{rel.split('/')[-1]}"


async def load_reference(ctx) -> dict | None:
    """Fetch the reference website's inspiration cues once and cache them in the job state.
    Non-fatal: a bad/blocked reference is recorded and the pipeline continues without it."""
    url = ctx.state.get("reference_url")
    if not url:
        return None
    cached = ctx.state.get("reference")
    if isinstance(cached, dict) and (cached.get("palette") is not None or cached.get("error")):
        return cached if not cached.get("error") else None
    await ctx.log(f"Studying reference site {url} for inspiration", progress=18)
    try:
        cues = await fetch_reference(url)
    except Exception as e:  # noqa: BLE001 — reference is optional; never fail generation over it
        ctx.state["reference"] = {"url": url, "error": str(getattr(e, "message", e))[:200]}
        await ctx.log(f"Couldn't use the reference ({getattr(e, 'message', e)}) — continuing without it", level="warning")
        return None
    ctx.state["reference"] = cues
    bits = [f"{len(cues['palette'])} colours", f"{len(cues['fonts'])} fonts", f"{len(cues['headings'])} headings"]
    await ctx.log(f"Reference read: {cues['site']} — {', '.join(bits)} (used as inspiration, not copied)", level="success", progress=28)
    return cues


def reference_context(ctx) -> dict | None:
    """Compact cue set passed to the AI as inspiration. The AI is told not to copy the reference's text."""
    ref = ctx.state.get("reference")
    if not isinstance(ref, dict) or ref.get("error"):
        return None
    return {"inspiration_only_do_not_copy_text": True, "site": ref.get("site"), "title": ref.get("title"),
            "description": ref.get("description"), "headings": ref.get("headings"), "nav": ref.get("nav"),
            "palette": ref.get("palette"), "fonts": ref.get("fonts"), "keywords": ref.get("keywords")}


# ----------------------------------------------------------------------------- 1
class RequirementsAgent(Agent):
    key, title, agent_name = "requirements", "Understand requirements", "Requirements Agent"
    description = "Analyses the instruction: purpose, audience, features and technical needs."

    async def run(self, ctx: StepContext) -> dict:
        await ctx.log("Parsing the instruction", progress=10)
        fallback = offline.requirements(ctx.site.prompt, ctx.site.stack)
        ref = await load_reference(ctx)
        await ctx.log(f"Topic detected: “{fallback['topic']}” · theme: {fallback['theme']}", progress=35)
        ctx_in = {"instruction": ctx.site.prompt, "selected_stack": ctx.site.stack}
        if ref:
            ctx_in["reference"] = reference_context(ctx)
        req = await ctx.ai_json("Requirements analyst",
                                "Analyse this website instruction and extract structured requirements. Keep 'theme' one of: "
                                + ", ".join(offline.THEMES)
                                + (". A reference site is provided for inspiration on purpose, audience and structure — take ideas, do not copy its wording." if ref else ""),
                                fallback, ctx_in)
        if req.get("theme") not in offline.THEMES:
            req["theme"] = fallback["theme"]
        rec = req.get("stack_recommendation") or fallback["stack_recommendation"]
        if rec.get("stack") not in STACKS:
            rec = fallback["stack_recommendation"]
        await ctx.log(f"Audience: {req['audience']}", progress=60)
        if ctx.site.stack == "auto":
            ctx.update_site(stack=rec["stack"], stack_selected_by="ai")
            await ctx.log(f"AI selected stack → {STACKS[rec['stack']].info.name}: {rec['reason']}", level="success", progress=80)
        else:
            await ctx.log(f"Using user-selected technology: {STACKS[ctx.site.stack].info.name}", progress=80)
            if rec["stack"] != ctx.site.stack:
                await ctx.log(f"Note: the brief also suits {STACKS[rec['stack']].info.name} — keeping the user's choice", level="info")
        if ctx.site.name in ("", "Untitled website") or ctx.state.get("name_from_ai", True):
            ctx.update_site(name=req["site_name"])
        ctx.state["requirements"] = req
        await ctx.log(f"{len(req['features'])} features identified", level="success", progress=100)
        highlights = [
            kv(("Topic", req["topic_title"]), ("Audience", req["audience"]), ("Tone", req["tone"]),
               ("Stack", f"{STACKS[ctx.site.stack].info.name} ({'AI' if ctx.site_updates.get('stack_selected_by') == 'ai' else 'user'})")),
            chips("Features", req["features"]),
        ]
        if ref:
            highlights.append(kv(("Inspired by", ref["site"]), ("Reference palette", ", ".join(ref["palette"]) or "—"),
                                 ("Reference fonts", ", ".join(ref["fonts"]) or "—")))
        return {"summary": f"{req['site_name']} — {req['purpose']}", "highlights": highlights}


# ----------------------------------------------------------------------------- 2
class PlanningAgent(Agent):
    key, title, agent_name = "planning", "Generate project plan", "Planning Agent"
    description = "Sitemap, architecture, database requirements and development plan."

    async def run(self, ctx):
        req = ctx.state["requirements"]
        await ctx.log("Drafting sitemap and information architecture", progress=20)
        fb = offline.plan(req, ctx.site.stack)
        ref = reference_context(ctx)
        plan = await ctx.ai_json("Information architect",
                                 "Create the sitemap and technical plan. Keep the page slugs of the example (you may add pages)."
                                 + (" A reference site's headings and navigation are provided — let them inspire the sections and sitemap." if ref else ""),
                                 fb, {"requirements": req, **({"reference": ref} if ref else {})})
        known = {p["slug"] for p in fb["sitemap"]}
        plan["sitemap"] = [p for p in plan["sitemap"] if p.get("slug") in known] or fb["sitemap"]
        await ctx.log(f"Sitemap: {len(plan['sitemap'])} pages", progress=55)
        await ctx.log(f"Database: {plan['database']['engine']}", progress=75)
        await ctx.log("Development plan ready", level="success", progress=100)
        ctx.state["plan"] = plan
        return {"summary": plan["design_direction"], "highlights": [
            chips("Sitemap", [p["title"] for p in plan["sitemap"]]),
            kv(("Rendering", plan["architecture"]["rendering"]), ("Database", plan["database"]["engine"]), ("Hosting", plan["architecture"]["hosting"])),
        ]}


# ----------------------------------------------------------------------------- 3
class BrandingAgent(Agent):
    key, title, agent_name = "branding", "Create brand & design", "Branding Agent"
    description = "Brand identity, logo, colours, typography and layout language."

    async def run(self, ctx):
        req = ctx.state["requirements"]
        await ctx.log("Exploring brand directions", progress=15)
        fb = offline.brand(req)
        ref = reference_context(ctx)
        if ref and ref.get("palette"):  # seed the offline fallback from the reference's own colours
            pal = ref["palette"]
            for i, key in enumerate(("primary", "secondary", "accent")):
                if i < len(pal) and key in fb["palette"]:
                    fb["palette"][key] = pal[i]
            if ref.get("fonts"):
                fb["fonts"]["heading"] = ref["fonts"][0]
                fb["fonts"]["body"] = ref["fonts"][1] if len(ref["fonts"]) > 1 else ref["fonts"][0]
        b = await ctx.ai_json("Brand designer",
                              "Create a brand identity. Colours must be 6-digit hex with good text contrast."
                              + (" A reference site's palette and fonts are provided — draw inspiration from them for a cohesive look." if ref else ""),
                              fb, {"requirements": req, **({"reference": {"palette": ref["palette"], "fonts": ref["fonts"]}} if ref else {})})
        for k, v in list(b["palette"].items()):
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(v)):
                b["palette"][k] = fb["palette"].get(k, "#333333")
        await ctx.log(f"Palette: {', '.join(b['palette'].values())}", progress=45)
        await ctx.log(f"Typography: {b['fonts']['heading']} / {b['fonts']['body']}", progress=65)
        ctx.site.media_dir.mkdir(parents=True, exist_ok=True)
        (ctx.site.media_dir / "logo.svg").write_text(svg_logo(b["name"], b["palette"]), encoding="utf-8")
        await ctx.log("Logo mark generated", level="success", progress=100)
        ctx.state["brand"] = b
        ctx.state.setdefault("images", {})["logo"] = "assets/media/logo.svg"
        return {"summary": b["tagline"], "highlights": [
            {"type": "palette", "items": [{"name": k, "hex": v} for k, v in b["palette"].items()]},
            {"type": "fonts", "items": [b["fonts"]["heading"], b["fonts"]["body"]]},
            {"type": "images", "items": [{"url": media_url(ctx.site.slug, "logo.svg"), "label": "Logo"}]},
            kv(("Style", b["style"]), ("Voice", b["voice"])),
        ]}


# ----------------------------------------------------------------------------- 4
def shingles(texts: list[str], n: int = 5) -> set[str]:
    words = re.findall(r"[a-z']+", " ".join(texts).lower())
    return {hashlib.md5(" ".join(words[i:i + n]).encode()).hexdigest()[:10] for i in range(max(0, len(words) - n + 1))}


CLAIM_PATTERNS = [r"\b\d{2,3}\s?%", r"\bguarantee", r"\b#1\b", r"\bnumber one\b", r"\baward[- ]winning\b", r"\blorem ipsum\b", r"\bTODO\b", r"\bclinically proven\b"]


class ContentAgent(Agent):
    key, title, agent_name = "content", "Generate content", "Content Agent"
    description = "Original pages, articles, FAQs and product copy, checked for originality."

    async def run(self, ctx):
        req, plan, brand = ctx.state["requirements"], ctx.state["plan"], ctx.state["brand"]
        await ctx.log("Writing homepage and page copy", progress=10)
        fb = offline.content(req, plan, brand)
        ref = reference_context(ctx)
        ctx_in = {"requirements": req, "brand": {"name": brand["name"], "voice": brand["voice"]}, "pages": [p["title"] for p in plan["sitemap"]]}
        if ref:
            ctx_in["reference_topics"] = {"headings": ref.get("headings"), "keywords": ref.get("keywords"), "site": ref.get("site")}
        c = await ctx.ai_json("Senior content writer",
                              "Write original website copy and 4 blog articles (5 paragraphs each, 60-110 words per paragraph). "
                              "Keep slugs URL-safe. Do not invent statistics, testimonials or credentials."
                              + (" Reference topics are provided for inspiration on themes to cover — write fresh, original copy; never reuse the reference's sentences." if ref else ""),
                              fb, ctx_in)
        for a in c["articles"]:
            a["slug"] = offline.slugify(a.get("slug") or a["title"])
        await ctx.log(f"{len(c['articles'])} articles drafted", progress=45)
        for a in c["articles"]:
            await ctx.log(f"✍  {a['title']}")
        await ctx.log(f"{len(c['faq'])} FAQs written", progress=65)

        texts = [p for a in c["articles"] for p in a["body"]] + c["about"]["body"]
        fp = shingles(texts)
        best, closest = 0.0, None
        for slug, other in ctx.recorder.other_fingerprints().items():
            if fp and other:
                sim = len(fp & other) / len(fp)
                if sim > best:
                    best, closest = sim, slug
        ctx.state["fingerprint"] = sorted(fp)[:600]
        ctx.state["originality"] = {"score": round(1 - best, 3), "closest": closest}
        level = "success" if best < 0.4 else "warning"
        await ctx.log(f"Originality check: {(1 - best) * 100:.0f}% unique across the portfolio", level=level, progress=85)

        flags = []
        for t in texts + [c["home"]["hero_subtitle"]]:
            for pat in CLAIM_PATTERNS:
                if re.search(pat, t, re.IGNORECASE):
                    flags.append(f"“{re.search(pat, t, re.IGNORECASE).group(0)}” needs verification")
        ctx.state["content_review"] = {"flags": flags[:10], "status": "needs_review" if flags else "auto_approved"}
        if flags:
            await ctx.log(f"{len(flags)} statements flagged for human review", level="warning")
        words = sum(len(t.split()) for t in texts)
        await ctx.log(f"{words:,} words of original copy", level="success", progress=100)
        ctx.state["content"] = c
        return {"summary": c["home"]["hero_title"], "highlights": [
            chips("Articles", [a["title"] for a in c["articles"]]),
            kv(("Words", f"{words:,}"), ("FAQs", len(c["faq"])), ("Products", len(c.get("products", []))), ("Originality", f"{(1 - best) * 100:.0f}%")),
        ]}


# ----------------------------------------------------------------------------- 5
class ImageAgent(Agent):
    key, title, agent_name = "images", "Generate images", "Image Agent (Fal.ai)"
    description = "Hero, editorial and product imagery via Fal.ai (SVG artwork fallback)."

    async def run(self, ctx):
        brand, c, req = ctx.state["brand"], ctx.state["content"], ctx.state["requirements"]
        key = ctx.recorder.provider_secret("fal", "api_key") or settings.FAL_KEY
        await ctx.log("Using Fal.ai" if key else "No Fal.ai key configured — generating vector artwork", progress=5)
        jobs: list[tuple[str, str, str, str]] = [
            ("hero", "hero", f"Hero image for a website about {req['topic']}, {brand['style']}, wide composition, no text", "landscape_16_9"),
            ("about", "about", f"Warm photo representing the people and mission behind {brand['name']} ({req['topic']})", "landscape_16_9"),
        ]
        jobs += [("article", a["slug"], a.get("image_prompt") or f"Editorial image for: {a['title']}", "landscape_16_9") for a in c["articles"]]
        jobs += [("product", p["slug"], f"Studio product photo: {p['name']}, clean background", "square_hd") for p in c.get("products", [])]
        images = ctx.state.setdefault("images", {})
        images.setdefault("articles", {})
        images.setdefault("products", {})
        sem = asyncio.Semaphore(3)
        done, sources, gallery = 0, set(), []

        async def one(kind, name, prompt, size):
            nonlocal done
            async with sem:
                path, source = await generate_image(prompt, ctx.site.media_dir / f"{kind}-{name}", brand["palette"], key, size)
            rel = f"assets/media/{path.name}"
            if kind in ("hero", "about"):
                images[kind] = rel
            else:
                images["articles" if kind == "article" else "products"][name] = rel
            done += 1
            sources.add(source)
            gallery.append({"url": media_url(ctx.site.slug, path.name), "label": name})
            await ctx.log(f"🖼  {kind}: {name}", progress=5 + 90 * done / len(jobs))

        await asyncio.gather(*(one(*j) for j in jobs))
        await ctx.log(f"{len(jobs)} images ready ({', '.join(sorted(sources))})", level="success", progress=100)
        return {"summary": f"{len(jobs)} images generated", "highlights": [{"type": "images", "items": gallery[:8]}]}


# ----------------------------------------------------------------------------- 6
class SEOAgent(Agent):
    key, title, agent_name = "seo", "Optimise SEO", "SEO Agent"
    description = "Titles, descriptions, keywords, structured data, sitemap and robots."

    async def run(self, ctx):
        req, plan, brand, c = (ctx.state[k] for k in ("requirements", "plan", "brand", "content"))
        await ctx.log("Researching keyword themes", progress=20)
        fb = offline.seo(req, plan, brand, c)
        s = await ctx.ai_json("Technical SEO specialist", "Write SEO metadata: titles <= 60 chars, descriptions 120-155 chars. Keep the page keys.", fb,
                              {"requirements": req, "pages": [p["slug"] for p in plan["sitemap"]], "articles": [a["title"] for a in c["articles"]]})
        fixed = 0
        for k, meta in fb["pages"].items():
            m = s["pages"].setdefault(k, meta)
            if len(m.get("title", "")) > 65:
                m["title"] = offline.clip(m["title"], 62)
                fixed += 1
            if not 50 <= len(m.get("description", "")) <= 170:
                m["description"] = meta["description"] if 50 <= len(meta["description"]) <= 170 else (meta["description"] + " " + brand["tagline"])[:158]
                fixed += 1
        await ctx.log(f"Metadata for {len(s['pages'])} URLs", progress=60)
        await ctx.log("Organization + FAQPage JSON-LD prepared", progress=80)
        if fixed:
            await ctx.log(f"Auto-corrected {fixed} out-of-range titles/descriptions", level="warning")
        await ctx.log("SEO configuration complete", level="success", progress=100)
        ctx.state["seo"] = s
        return {"summary": f"{len(s['pages'])} URLs optimised", "highlights": [chips("Keywords", s["keywords"][:8]), kv(("URLs", len(s["pages"])), ("Structured data", "Organization, FAQPage"))]}


# ----------------------------------------------------------------------------- 7
class DevelopmentAgent(Agent):
    key, title, agent_name = "development", "Develop website", "Development Agent"
    description = "Generates the stack-specific codebase and builds the production artefact."

    async def run(self, ctx):
        adapter = get_stack(ctx.site.stack)
        hosting = get_hosting(ctx.site.hosting_provider)
        if ctx.recorder.job.type in PREVIEW_JOBS:
            base_url = preview_url(ctx.site.slug)  # previews are built for their private preview link
            await ctx.log("Building for preview (nothing is published)")
        else:
            base_url = hosting.public_url(ctx.site)
            if base_url.startswith("pending://"):
                base_url = f"https://{ctx.site.slug}.example/"
            await ctx.log(f"Building for production at {base_url}")
        spec = {**{k: ctx.state[k] for k in ("requirements", "plan", "brand", "content", "seo", "images")},
                "slug": ctx.site.slug, "base_url": base_url, "domain": ctx.site.domain, "media_dir": str(ctx.site.media_dir),
                "reference": ctx.state.get("reference"),
                "form_action": f"{settings.PUBLIC_BASE_URL.rstrip('/')}/api/public/forms/{ctx.site.slug}"}
        source, build = ctx.site.workspace / "source", ctx.site.workspace / "build"
        if source.exists():
            shutil.rmtree(source)
        await ctx.log(f"Scaffolding {adapter.info.name} project", progress=15)
        src_files = adapter.scaffold(spec, source)
        await ctx.log(f"{len(src_files)} source files generated", progress=50)

        async def blog(msg, progress=None):
            await ctx.log(msg, progress=progress)

        authored_by = "template"
        code_provider = get_code_provider()
        if not code_provider.offline:
            try:
                await ctx.log(f"Designing & coding a unique site with {settings.ZAI_MODEL}", progress=25)
                built = await build_ai_site(spec, build, ctx.site.media_dir, base_url, ctx.site.slug, blog)
                authored_by = settings.ZAI_MODEL
            except Exception as e:  # noqa: BLE001 — never fail the build over the code model; fall back to the renderer
                await ctx.log(f"Code model unavailable ({getattr(e, 'message', e)}); using the built-in renderer", level="warning")
                built = await adapter.build(spec, source, build, ctx.site.media_dir, base_url, ctx.site.slug, blog)
        else:
            built = await adapter.build(spec, source, build, ctx.site.media_dir, base_url, ctx.site.slug, blog)
        await ctx.log(f"Production build: {len(built)} files", level="success", progress=100)
        ctx.state["build"] = {"stack": adapter.info.key, "source_files": len(src_files), "build_files": len(built), "base_url": base_url,
                              "authored_by": authored_by, "source_tree": sorted(src_files)[:80]}
        unique = authored_by != "template"
        return {"summary": (f"Unique {adapter.info.name} site coded by {authored_by}" if unique else f"{adapter.info.name} project with {len(src_files)} source files"),
                "highlights": [
            kv(("Stack", adapter.info.name), ("Code authored by", authored_by if unique else "built-in renderer"),
               ("Build files", len(built)), ("Deploy model", adapter.info.deploy_model)),
            chips("Files", sorted(src_files)[:10]),
        ]}


# ----------------------------------------------------------------------------- 8
async def purchase_domain(ctx: StepContext, provider, domain: str) -> dict:
    """Buys `domain` through the chosen provider exactly once and waits until it is active.

    State lives in the `domains` table, so resuming a job continues the same order instead of
    placing a new one. Order: re-check price → approval → order → poll until active.
    """
    rec = ctx.recorder
    dom = rec.get_domain(domain)
    if dom and dom.website_id not in (None, ctx.site.id) and dom.status != "failed":
        raise ConfigurationError(f"{domain} is already used by another website")
    if dom is None:
        dom = rec.save_domain(None, name=domain, provider=provider.key, account_id=ctx.site.dns_account_id, website_id=ctx.site.id, status="quoted")
    creds = ctx.credentials(ctx.site.dns_account_id)

    if dom.status == "active":
        await ctx.log(f"{domain} already registered with {provider.name}", level="success", progress=40)
        return {"domain": domain, "purchased": True, "expires_at": dom.expires_at}
    if dom.status in ("ordering", "unknown"):
        rec.save_domain(dom, status="unknown")
        raise PipelineError(f"A previous purchase attempt for {domain} was interrupted", code="domain_order_uncertain",
                            hint="Check the provider dashboard, then use Domains → Sync (bought) or Reset (not bought) and resume.")

    if dom.status in ("quoted", "failed"):
        if settings.DOMAIN_MAX_PRICE <= 0:
            raise ConfigurationError("Domain purchasing is disabled (DOMAIN_MAX_PRICE=0)")
        await ctx.log(f"Checking availability and price of {domain} with {provider.name}", progress=20)
        quote = (await provider.check_domains(creds, [domain]))[0]
        if not quote["available"]:
            rec.save_domain(dom, status="failed", error=f"Not available: {quote.get('reason')}")
            raise PipelineError(f"{domain} cannot be registered ({quote.get('reason') or 'unavailable'})", code="domain_unavailable",
                                hint="Pick another domain in the website settings, then resume.")
        price, cur = quote.get("price"), quote.get("currency") or ""
        if price is None or price > settings.DOMAIN_MAX_PRICE:
            rec.save_domain(dom, status="failed", price=price, currency=cur, error="Above price cap")
            raise PipelineError(f"{domain} costs {price} {cur}, above the {settings.DOMAIN_MAX_PRICE} cap", code="domain_price_cap",
                                hint="Choose a cheaper domain or raise DOMAIN_MAX_PRICE.")
        rec.save_domain(dom, status="quoted", price=price, renewal_price=quote.get("renewal_price"), currency=cur, error=None,
                        years=settings.DOMAIN_REGISTRATION_YEARS, auto_renew=settings.DOMAIN_AUTO_RENEW)
        await ctx.log(f"{domain} is available: {price} {cur} for {settings.DOMAIN_REGISTRATION_YEARS} year(s)"
                      + (f", renews at {quote['renewal_price']} {cur}" if quote.get("renewal_price") else ""), progress=30)
        if settings.APPROVAL_DOMAIN_PURCHASE:
            ctx.require_approval("register_domain", f"Buy {domain} via {provider.name} for {price} {cur} ({settings.DOMAIN_REGISTRATION_YEARS}y, auto-renew {'on' if settings.DOMAIN_AUTO_RENEW else 'off'})",
                                 {"domain": domain, "provider": provider.key, "price": price, "currency": cur, "renewal_price": quote.get("renewal_price")})
            # Prices can change between quote and approval: re-check and refuse if it went above the approved quote.
            fresh = (await provider.check_domains(creds, [domain]))[0]
            if not fresh["available"] or (fresh.get("price") or 0) > price:
                rec.save_domain(dom, status="failed", error="Price or availability changed after approval")
                raise PipelineError(f"{domain} changed after approval ({fresh.get('price')} {cur}, available={fresh['available']})",
                                    code="domain_quote_changed", hint="Resume the job to request a new approval.")

        rec.save_domain(dom, status="ordering")  # persisted before the billable call
        await ctx.log(f"Placing order for {domain} with {provider.name}", level="warning", progress=40)
        try:
            order = await provider.register_domain(creds, domain, settings.DOMAIN_REGISTRATION_YEARS, settings.DOMAIN_AUTO_RENEW)
        except DomainOrderRejected as e:
            rec.save_domain(dom, status="failed", error=e.message)
            raise
        except DomainOrderUncertain as e:
            rec.save_domain(dom, status="unknown", error=e.message)
            raise
        except Exception as e:  # anything unexpected during a billable call is treated as uncertain
            rec.save_domain(dom, status="unknown", error=str(e)[:300])
            raise DomainOrderUncertain(f"Unexpected error while ordering {domain}: {e}")
        rec.save_domain(dom, status=order["status"], order_ref=order.get("order_ref"))
        await ctx.log(f"Order accepted (ref {str(order.get('order_ref'))[:60]})", level="success", progress=45)

    # dom.status is now pending or active: wait for activation
    deadline = time.monotonic() + min(settings.DOMAIN_ACTIVATION_TIMEOUT_SECONDS, max(30, settings.STEP_TIMEOUT_SECONDS - 60))
    polls = 0
    while dom.status != "active":
        st = await provider.registration_status(creds, domain, dom.order_ref)
        if st["status"] == "active":
            rec.save_domain(dom, status="active", expires_at=st.get("expires_at"), error=None)
            break
        if st["status"] == "failed":
            rec.save_domain(dom, status="failed", error=st.get("message"))
            raise PipelineError(f"Registration of {domain} failed: {st.get('message')}", code="domain_registration_failed")
        polls += 1
        if polls == 1 or polls % 6 == 0:
            await ctx.log(f"Waiting for {domain} to activate… {st.get('message') or st.get('state') or ''}".strip())
        if time.monotonic() > deadline:
            raise RetryableError(f"{domain} is still activating at {provider.name}", code="domain_pending",
                                 hint="The order is placed and will not be repeated. Resume the job later to continue.")
        await asyncio.sleep(10 if not ctx.offline else 0.2)
    await ctx.log(f"{domain} is registered and active", level="success", progress=55)
    return {"domain": domain, "purchased": True, "price": dom.price, "currency": dom.currency, "expires_at": dom.expires_at}


class InfrastructureAgent(Agent):
    key, title, agent_name = "infrastructure", "Configure infrastructure", "Infrastructure Agent"
    description = "Hosting, domain, DNS, database and SSL — external changes need approval."

    async def run(self, ctx):
        site = ctx.site
        hosting = get_hosting(site.hosting_provider)
        ok, reason = hosting.enabled()
        if not ok:
            raise ConfigurationError(f"{hosting.name} is not available: {reason}", hint="Choose another hosting provider or enable this adapter.")
        plan = hosting.plan(site, ctx.state)
        await ctx.log(f"Hosting target: {hosting.name}", progress=10)
        infra = dict(ctx.state.get("infra") or {})
        infra.update({"hosting": hosting.key, "plan": plan})

        creds: dict = {}
        if hosting.external:
            if not site.hosting_account_id:
                raise ConfigurationError(f"{hosting.name} requires a connected provider account", hint="Add the account under Providers and attach it to this website.")
            creds = ctx.credentials(site.hosting_account_id)
            used, limit = ctx.recorder.account_usage(site.hosting_account_id)
            if limit and used > limit:
                raise ConfigurationError(f"Provider account limit reached ({used}/{limit} sites)", hint="Attach another provider account or raise the limit.")
            await ctx.log(f"Provider account verified ({used}/{limit or '∞'} sites)", progress=20)

        dns = get_dns(site.dns_provider)
        mode = ctx.state.get("domain_mode") or ("existing" if site.domain else "none")
        if site.domain and dns.key != "none" and mode == "buy":
            infra["domain"] = await purchase_domain(ctx, dns, site.domain)
        elif site.domain:
            await ctx.log(f"Looking up {site.domain} (RDAP)", progress=30)
            domain_info = await rdap_lookup(site.domain)
            if domain_info.get("available"):
                raise ConfigurationError(f"{site.domain} is not registered yet",
                                         hint="Choose “Buy a new domain” for this website, or register it first.")
            if domain_info.get("expires_at"):
                await ctx.log(f"Domain registered, expires {domain_info['expires_at'][:10]}")
            infra["domain"] = domain_info

        if hosting.requires_approval and settings.APPROVAL_PROVISION_HOSTING:
            ctx.require_approval("provision_hosting", f"Provision {hosting.name} resources for {site.domain or site.slug}", {"plan": plan})
            await ctx.log("Approval granted — provisioning", progress=60)
        if hosting.requires_approval or getattr(hosting, "always_provision", False):
            infra.update(await hosting.provision(site, creds, ctx.log))

        if dns.key != "none" and site.domain:
            target = infra.get("ipv4") or settings.SERVER_PUBLIC_IP or ("203.0.113.10" if settings.SANDBOX_PROVIDERS else "")
            if not target:
                await ctx.log("DNS skipped: no public IP for this hosting target (set SERVER_PUBLIC_IP)", level="warning")
            else:
                if settings.APPROVAL_DNS_CHANGES:
                    ctx.require_approval("configure_dns", f"Point {site.domain} (A record) to {target} via {dns.name}", {"domain": site.domain, "target": target})
                dns_creds = ctx.credentials(site.dns_account_id)
                await ctx.log(f"Upserting A record {site.domain} → {target}", progress=80)
                infra["dns"] = await dns.upsert_record(dns_creds, site.domain, "A", target)
                await ctx.log("DNS configured", level="success")
        else:
            await ctx.log("No DNS changes required", progress=80)

        ssl = {"local": "Served via platform URL" if not site.domain else "Platform host routing (TLS at Cloudflare edge or reverse proxy)",
               "docker": "Traefik + Let's Encrypt (when a domain is set)", "hetzner": "Caddy automatic HTTPS"}.get(hosting.key, "Provider managed")
        if dns.key == "cloudflare":
            ssl = "Cloudflare edge TLS (proxied) + origin certificate"
        infra["ssl"] = ssl
        db_engine = ctx.state["plan"]["database"]["engine"]
        infra["database"] = "not required" if db_engine == "none" else f"{db_engine} (isolated per site, provisioned with the stack)"
        await ctx.log(f"SSL: {ssl}", progress=90)
        await ctx.log("Infrastructure ready", level="success", progress=100)
        ctx.state["infra"] = infra
        return {"summary": f"{hosting.name} · SSL: {ssl}", "highlights": [kv(("Hosting", hosting.name), ("Domain", site.domain or "platform URL"),
                                                                              ("DNS", dns.name), ("SSL", ssl), ("Database", infra["database"]))]}


# ----------------------------------------------------------------------------- 9
class TestingAgent(Agent):
    key, title, agent_name = "testing", "Test & validate", "Testing Agent"
    description = "Links, navigation, forms, responsiveness, SEO, security and originality."

    async def run(self, ctx):
        build = ctx.site.workspace / "build"
        if not build.exists():
            raise PipelineError("No build artefact found", code="missing_build", hint="Re-run the development step.")
        await ctx.log("Crawling build artefact", progress=15)
        report = await asyncio.to_thread(run_checks, build, ctx.state, ctx.recorder.all_secret_values())
        for i, ch in enumerate(report["checks"]):
            icon = {"pass": "✔", "warn": "▲", "fail": "✖"}[ch["status"]]
            await ctx.log(f"{icon} {ch['name']} — {ch['detail']}", level={"pass": "info", "warn": "warning", "fail": "error"}[ch["status"]],
                          progress=15 + 80 * (i + 1) / len(report["checks"]))
        ctx.state["quality"] = report
        hl = [{"type": "checks", "items": report["checks"]}, kv(("Score", f"{report['score']}/100"), ("Pages", report["pages"]), ("Passed", report["passed"]), ("Warnings", report["warnings"]))]
        if report["blocking"]:
            raise QualityGateError(f"Quality gate blocked deployment: {', '.join(report['critical_failures'])}", details={"report": report})
        await ctx.log(f"Quality score {report['score']}/100 — deployment allowed", level="success", progress=100)
        return {"summary": f"Quality score {report['score']}/100", "highlights": hl}


# ----------------------------------------------------------------------------- 10
class DeploymentAgent(Agent):
    key, title, agent_name = "deployment", "Deploy website", "Deployment Agent"
    description = "Publishes an immutable, versioned artefact to the hosting target."

    async def run(self, ctx):
        site = ctx.site
        hosting = get_hosting(site.hosting_provider)
        if site.require_approval or not settings.AUTO_PUBLISH:  # default: publish automatically
            ctx.require_approval("publish", f"Publish {site.name} to {hosting.name}", {"quality": ctx.state.get("quality", {}).get("score")})
        version = ctx.recorder.next_version()
        await ctx.log(f"Deploying v{version} to {hosting.name}", progress=20)
        creds = ctx.credentials(site.hosting_account_id) if hosting.external else {}
        result = await hosting.deploy(site, site.workspace / "build", site.workspace / "source", version, creds, ctx.state.get("infra", {}), ctx.log)
        dep_id = ctx.recorder.create_deployment(version, hosting.key, result, ctx.state.get("quality", {}).get("score"))
        await ctx.log("Switching traffic to the new version", progress=80)
        ctx.state["deployment"] = {"id": dep_id, "version": version, "url": result["url"], "previous": site.current_deployment_id}
        ctx.recorder.switch_traffic(dep_id)
        await ctx.log(f"v{version} published", level="success", progress=100)
        return {"summary": f"v{version} → {result['url']}", "highlights": [kv(("Version", f"v{version}"), ("Provider", hosting.name), ("URL", result["url"]))]}


# ----------------------------------------------------------------------------- 11
class VerifyAgent(Agent):
    key, title, agent_name = "verify", "Verify & register", "Maintenance Agent"
    description = "Checks the live site, rolls back on failure, and registers it for monitoring."

    async def run(self, ctx):
        dep = ctx.state.get("deployment") or {}
        url = dep.get("url", "")
        await ctx.log(f"Probing {url}", progress=15)
        result = {"checked": False}
        hosting = get_hosting(ctx.site.hosting_provider)
        if hasattr(hosting, "verify"):
            await ctx.log("Requesting the site from the server itself (works before DNS has propagated)", progress=30)
            result = await hosting.verify(ctx.site, url)
            if result.get("status") != 200:
                rolled = ctx.recorder.rollback_traffic(dep.get("previous"))
                if rolled and dep.get("previous"):
                    from ..models import Deployment
                    prev = ctx.recorder.db.get(Deployment, dep["previous"])
                    await hosting.activate(ctx.site, prev)  # switch the server back too
                raise PipelineError(f"Server returned HTTP {result.get('raw_status')} for the new release" + (f"; rolled back to {rolled}" if rolled else ""),
                                    code="verification_failed", hint="Check the server's web-server logs (journalctl -u caddy).")
            await ctx.log(f"{result['via']} answers HTTP {result['raw_status']}", level="success", progress=60)
            if result.get("https"):
                await ctx.log("HTTPS certificate is issued automatically once DNS points to the server", level="info")
        elif url.startswith("http") and "<" not in url:
            last_err = None
            for attempt in range(3):
                try:
                    t0 = time.perf_counter()
                    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                        r = await c.get(url)
                        sm = await c.get(url.rstrip("/") + "/sitemap.xml")
                    ms = (time.perf_counter() - t0) * 1000
                    headers = {h: h in r.headers for h in ("x-content-type-options", "x-frame-options", "referrer-policy")}
                    result = {"checked": True, "status": r.status_code, "response_ms": round(ms), "headers": headers, "sitemap": sm.status_code, "https": url.startswith("https")}
                    if r.status_code == 200:
                        break
                    last_err = f"HTTP {r.status_code}"
                except httpx.HTTPError as e:
                    last_err = e.__class__.__name__
                await ctx.log(f"Attempt {attempt + 1} failed ({last_err}), retrying", level="warning")
                await asyncio.sleep(2 * (attempt + 1))
            if result.get("status") != 200:
                rolled = ctx.recorder.rollback_traffic(dep.get("previous"))
                msg = f"Live verification failed ({last_err})"
                if rolled:
                    msg += f"; automatically rolled back to {rolled}"
                raise PipelineError(msg, code="verification_failed", hint="Check the hosting provider logs; the previous version stays live.")
            await ctx.log(f"HTTP 200 in {result['response_ms']} ms", level="success", progress=45)
            missing = [h for h, ok in result["headers"].items() if not ok]
            await ctx.log("Security headers present" if not missing else f"Missing headers: {', '.join(missing)}", level="info" if not missing else "warning", progress=60)
            await ctx.log(f"Sitemap HTTP {result['sitemap']}", progress=70)
        else:
            await ctx.log("Provider-hosted URL — skipping HTTP probe (store may be password-protected)", level="warning", progress=60)
        ctx.recorder.mark_live(dep["id"], url, result)
        await ctx.log("Registered in dashboard and monitoring", level="success", progress=100)
        ctx.state["verification"] = result
        if ctx.state.get("preview"):
            ctx.state["preview"] = {**ctx.state["preview"], "published": True}  # live now matches the reviewed preview
        return {"summary": f"Live at {url}", "highlights": [{"type": "link", "url": url, "label": "Open live website"},
                                                            kv(("Status", result.get("status", "n/a")), ("Response", f"{result.get('response_ms', '–')} ms"), ("HTTPS", "yes" if result.get("https") else "no"))]}


# ----------------------------------------------------------------------------- preview
def preview_url(slug: str) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/preview/{slug}/"


class PreviewAgent(Agent):
    key, title, agent_name = "preview", "Live preview", "Preview Agent"
    description = "Publishes the tested build to a private preview link — nothing goes live and no domain is touched."

    async def run(self, ctx):
        build, dest = ctx.site.workspace / "build", ctx.site.workspace / "preview"
        if not build.exists():
            raise PipelineError("No build artefact found", code="missing_build", hint="Re-run the development step.")
        await ctx.log("Publishing build to the preview link", progress=30)
        tmp = ctx.site.workspace / "preview.tmp"
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(build, tmp)
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)  # swap in one step so the preview is never half-written
        url = preview_url(ctx.site.slug)
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
                r = await c.get(url)
            await ctx.log(f"Preview responds HTTP {r.status_code}", level="success" if r.status_code == 200 else "warning", progress=70)
        except httpx.HTTPError as e:
            await ctx.log(f"Could not probe preview ({e.__class__.__name__})", level="warning")
        revs = ctx.state.get("revisions", [])
        ctx.state["preview"] = {"url": url, "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "revision": len(revs),
                                "quality": (ctx.state.get("quality") or {}).get("score"), "published": False}
        if ctx.site.status != "live":
            ctx.update_site(status="preview")
        await ctx.log("Preview ready — review it, request changes, then publish when you're happy", level="success", progress=100)
        return {"summary": f"Preview ready at {url}", "highlights": [{"type": "link", "url": url, "label": "Open preview"},
                                                                    kv(("Quality", f"{ctx.state['preview']['quality']}/100"), ("Revision", f"#{len(revs)}"),
                                                                       ("Live site", "unchanged" if ctx.site.status == "live" else "not published yet"))]}


AGENTS: list[Agent] = [RequirementsAgent(), PlanningAgent(), BrandingAgent(), ContentAgent(), ImageAgent(), SEOAgent(),
                       DevelopmentAgent(), TestingAgent(), PreviewAgent(), InfrastructureAgent(), DeploymentAgent(), VerifyAgent()]
AGENT_BY_KEY = {a.key: a for a in AGENTS}

from .revision import RevisionAgent  # noqa: E402 — imported late to avoid a cycle

AGENT_BY_KEY[RevisionAgent.key] = RevisionAgent()

# Flow: build → preview → (change requests → preview)* → publish (hosting + domain) → live
BUILD_STEPS = ["development", "testing", "preview"]
JOB_TYPES = {
    "generate": ["requirements", "planning", "branding", "content", "images", "seo", *BUILD_STEPS],
    "revise": ["revise", *BUILD_STEPS],  # apply a user's change request to the preview
    "regenerate_content": ["content", "images", "seo", *BUILD_STEPS],
    "publish": ["infrastructure", "development", "testing", "deployment", "verify"],  # hosting + domain, then go live
    "redeploy": ["development", "testing", "deployment", "verify"],  # rebuild the live site as-is
}
PREVIEW_JOBS = {"generate", "revise", "regenerate_content"}

__all__ = ["AGENTS", "AGENT_BY_KEY", "JOB_TYPES", "RetryableError"]

"""Deterministic offline generator.

Used when no AI provider is configured, and as the schema/fallback for every AI call:
LLM output is merged on top of these defaults so a partial or malformed AI response can
never break the pipeline.
"""
from __future__ import annotations

import hashlib
import random
import re

THEMES: dict[str, dict] = {
    "eco": {
        "keywords": ["sustain", "eco", "green", "climate", "zero waste", "garden", "organic", "nature", "solar", "recycl", "plant"],
        "palette": ["#2f6b3f", "#8fbf6a", "#e9a23b", "#f7f5ee", "#ffffff", "#1d2b22", "#5d6b60"],
        "fonts": ["Fraunces", "Inter"], "style": "organic, warm and calm", "dark": False,
    },
    "tech": {
        "keywords": ["tech", "software", "ai ", "saas", "app", "cloud", "developer", "startup", "data", "cyber", "crypto", "robot"],
        "palette": ["#6366f1", "#06b6d4", "#f472b6", "#0b1020", "#131b34", "#e6e9f5", "#94a3b8"],
        "fonts": ["Space Grotesk", "Inter"], "style": "futuristic, crisp and confident", "dark": True,
    },
    "food": {
        "keywords": ["food", "restaurant", "recipe", "coffee", "bakery", "cafe", "kitchen", "cook", "wine", "vegan", "pizza"],
        "palette": ["#c2410c", "#f59e0b", "#65a30d", "#fffaf3", "#ffffff", "#2b1d12", "#7c6a58"],
        "fonts": ["Playfair Display", "Lato"], "style": "appetising, rich and inviting", "dark": False,
    },
    "health": {
        "keywords": ["health", "wellness", "yoga", "clinic", "medical", "dental", "therapy", "mental", "meditat", "nutrition", "spa"],
        "palette": ["#0f766e", "#5eead4", "#f97316", "#f4fbfa", "#ffffff", "#10302d", "#5b7472"],
        "fonts": ["DM Serif Display", "DM Sans"], "style": "clean, reassuring and airy", "dark": False,
    },
    "finance": {
        "keywords": ["finance", "invest", "bank", "money", "insurance", "account", "tax", "loan", "wealth", "budget", "legal", "law"],
        "palette": ["#1e3a8a", "#d4a017", "#10b981", "#f6f8fc", "#ffffff", "#0f1b3d", "#5b6785"],
        "fonts": ["Manrope", "Inter"], "style": "trustworthy, precise and premium", "dark": False,
    },
    "travel": {
        "keywords": ["travel", "tour", "hotel", "trip", "adventure", "beach", "hostel", "destination", "camping", "hiking"],
        "palette": ["#0369a1", "#f4a261", "#2a9d8f", "#fbf8f3", "#ffffff", "#12263a", "#5f6f7f"],
        "fonts": ["Cormorant Garamond", "Nunito Sans"], "style": "adventurous, sunny and open", "dark": False,
    },
    "fashion": {
        "keywords": ["fashion", "cloth", "apparel", "jewel", "beauty", "cosmetic", "boutique", "shoe", "style", "luxury"],
        "palette": ["#111111", "#e11d48", "#d4af37", "#faf7f5", "#ffffff", "#111111", "#6b6b6b"],
        "fonts": ["Bodoni Moda", "Jost"], "style": "editorial, bold and elegant", "dark": False,
    },
    "education": {
        "keywords": ["school", "course", "learn", "education", "tutor", "academy", "university", "training", "teach", "language"],
        "palette": ["#7c3aed", "#fbbf24", "#10b981", "#faf9ff", "#ffffff", "#1f1641", "#6b6385"],
        "fonts": ["Poppins", "Source Sans 3"], "style": "friendly, bright and structured", "dark": False,
    },
    "fitness": {
        "keywords": ["fitness", "gym", "workout", "sport", "running", "athlet", "crossfit", "cycling", "martial"],
        "palette": ["#dc2626", "#111827", "#facc15", "#f9fafb", "#ffffff", "#111827", "#6b7280"],
        "fonts": ["Oswald", "Roboto"], "style": "energetic, bold and punchy", "dark": False,
    },
    "pets": {
        "keywords": ["pet", "dog", "cat", "vet", "animal", "puppy", "groom"],
        "palette": ["#ea580c", "#0ea5e9", "#84cc16", "#fffbf5", "#ffffff", "#2a1f17", "#75685c"],
        "fonts": ["Baloo 2", "Nunito"], "style": "playful, warm and caring", "dark": False,
    },
    "home": {
        "keywords": ["interior", "furniture", "home", "architect", "real estate", "property", "decor", "renovat", "construction"],
        "palette": ["#7c5c45", "#c8a27a", "#4d7c6f", "#f8f5f0", "#ffffff", "#2d241d", "#74685d"],
        "fonts": ["Libre Baskerville", "Work Sans"], "style": "refined, natural and textured", "dark": False,
    },
    "art": {
        "keywords": ["art", "music", "photo", "design", "gallery", "film", "creative", "studio", "band", "podcast"],
        "palette": ["#9333ea", "#f43f5e", "#f59e0b", "#fdfaff", "#ffffff", "#1e1029", "#6e6378"],
        "fonts": ["Syne", "Karla"], "style": "expressive, vivid and artistic", "dark": False,
    },
    "business": {
        "keywords": [],
        "palette": ["#2563eb", "#0ea5e9", "#f59e0b", "#f8fafc", "#ffffff", "#0f172a", "#64748b"],
        "fonts": ["Plus Jakarta Sans", "Inter"], "style": "modern, professional and clear", "dark": False,
    },
}

ECOMMERCE_WORDS = ["shop", "store", "sell", "ecommerce", "e-commerce", "product", "boutique", "merch", "catalog"]
BLOG_WORDS = ["blog", "magazine", "news", "publication", "journal", "articles", "editorial"]
APP_WORDS = ["booking", "dashboard", "portal", "crm", "members", "membership", "saas", "login", "account", "reservation"]

STOP = {"a", "an", "the", "and", "or", "for", "of", "to", "in", "on", "with", "using", "about", "website", "site", "web"}


def clip(text: str, limit: int) -> str:
    """Shorten at a word boundary (never mid-word)."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    return cut + "…"


def rng_for(*parts: str) -> random.Random:
    seed = int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def title_case(s: str) -> str:
    return " ".join(w if w.isupper() else w.capitalize() for w in s.split())


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or "site"


def extract_topic(prompt: str) -> str:
    p = prompt.strip().rstrip(".")
    for pat in [
        r"\b(?:selling|sells|sell)\s+(.+?)(?:\s+(?:using|with|built|on|online)\b|[.,;]|$)",
        r"\babout\s+(.+?)(?:\s+(?:using|with|built|on|in|for)\b|[.,;]|$)",
        r"\bfor\s+(?:a|an|my|our)?\s*(.+?)(?:\s+(?:using|with|built|on)\b|[.,;]|$)",
        r"\b(?:website|site|store|blog|shop)\s+(?:for|of)\s+(.+?)(?:\s+(?:using|with)\b|[.,;]|$)",
    ]:
        m = re.search(pat, p, re.IGNORECASE)
        if m and len(m.group(1).split()) <= 8:
            return m.group(1).strip().lower()
    words = [w for w in re.findall(r"[a-zA-Z]+", p.lower()) if w not in STOP and w not in {"create", "build", "make", "generate"}]
    return " ".join(words[:3]) or "modern business"


def detect_theme(text: str) -> str:
    t = " " + text.lower() + " "
    best, best_hits = "business", 0
    for key, theme in THEMES.items():
        hits = sum(1 for k in theme["keywords"] if k in t)
        if hits > best_hits:
            best, best_hits = key, hits
    return best


def recommend_stack(prompt: str) -> dict:
    t = prompt.lower()
    if any(w in t for w in ECOMMERCE_WORDS):
        return {"stack": "nextjs", "reason": "The brief showcases products, so a fast Next.js site with a product catalogue and enquiry flow fits best."}
    if any(w in t for w in APP_WORDS):
        return {"stack": "laravel", "reason": "The brief needs accounts or business workflows, which suit a full server-side application framework."}
    if any(w in t for w in BLOG_WORDS):
        return {"stack": "wordpress", "reason": "The brief is publication-centred, so a CMS with editorial workflows fits best."}
    return {"stack": "nextjs", "reason": "A content-driven marketing site benefits from Next.js static generation: fast, SEO-friendly and cheap to host."}


# --------------------------------------------------------------------------- requirements

def requirements(prompt: str, stack: str) -> dict:
    topic = extract_topic(prompt)
    theme = detect_theme(prompt + " " + topic)
    r = rng_for(prompt)
    named = re.search(r"\b(?:called|named)\s+[\"']?([A-Z][\w&' -]{1,40}?)[\"']?(?:[.,;]|\s+(?:using|with|about|for)\b|$)", prompt)
    words = topic.split()
    key = title_case(topic) if 0 < len(words) <= 2 else (title_case(max(words, key=len)) if words else "Nova")
    suffix = r.choice(["Collective", "Journal", "Lab", "Atlas", "Commons", "Studio", "Hub", "Co."])
    site_name = named.group(1).strip() if named else f"{key} {suffix}"
    aud = re.search(r"\bfor\s+((?:busy|young|small|local|new|first|modern|aspiring)?\s*[a-z ]{3,40}?)(?:[.,;]|\s+(?:using|with)\b|$)", prompt.lower())
    audience = aud.group(1).strip() if aud and topic not in aud.group(1) else r.choice([
        f"people curious about {topic} who want practical, trustworthy guidance",
        f"beginners and enthusiasts exploring {topic}",
        f"busy professionals who care about {topic}",
    ])
    t = prompt.lower()
    ecommerce = any(w in t for w in ECOMMERCE_WORDS)
    features = ["Responsive multi-page layout", "Blog with original articles", "FAQ section", "Contact form", "SEO metadata, sitemap and robots.txt"]
    if ecommerce:
        features.insert(1, "Product catalogue")
    if any(w in t for w in ["newsletter", "subscribe"]):
        features.append("Newsletter signup")
    rec = recommend_stack(prompt)
    return {
        "topic": topic,
        "topic_title": title_case(topic),
        "theme": theme,
        "site_name": site_name,
        "purpose": f"Inform and inspire {audience} with original content about {topic}, and convert visitors into a returning audience.",
        "audience": audience,
        "tone": THEMES[theme]["style"],
        "language": "en",
        "features": features,
        "ecommerce": ecommerce,
        "needs_database": ecommerce or any(w in t for w in APP_WORDS),
        "needs_cms": any(w in t for w in BLOG_WORDS) or stack == "wordpress",
        "stack_recommendation": rec,
        "goals": ["Build trust through useful content", "Rank for core search terms", "Capture leads via the contact form"],
    }


# --------------------------------------------------------------------------- planning

def plan(req: dict, stack: str) -> dict:
    pages = [
        {"slug": "", "title": "Home", "purpose": "Introduce the brand and route visitors", "sections": ["Hero", "Pillars", "Featured articles", "FAQ teaser", "Call to action"]},
        {"slug": "about", "title": "About", "purpose": "Explain the mission and values", "sections": ["Story", "Values", "Approach"]},
        {"slug": "services", "title": "What we offer", "purpose": "Describe the core offering", "sections": ["Intro", "Offer grid"]},
    ]
    if req.get("ecommerce"):
        pages.append({"slug": "shop", "title": "Shop", "purpose": "Showcase products", "sections": ["Product grid"]})
    pages += [
        {"slug": "blog", "title": "Journal", "purpose": "Publish original articles", "sections": ["Article list", "Categories"]},
        {"slug": "faq", "title": "FAQ", "purpose": "Answer common questions", "sections": ["Questions"]},
        {"slug": "contact", "title": "Contact", "purpose": "Capture leads", "sections": ["Form", "Details"]},
    ]
    db = {"engine": "none", "tables": []}
    if req.get("needs_database") or stack in ("wordpress", "laravel"):
        db = {"engine": "mysql" if stack in ("wordpress", "laravel") else "postgresql",
              "tables": ["pages", "posts", "categories", "form_submissions"] + (["products", "orders"] if req.get("ecommerce") else [])}
    return {
        "sitemap": pages,
        "architecture": {
            "stack": stack,
            "rendering": {"nextjs": "Static export (SSG)", "wordpress": "PHP + MySQL CMS", "laravel": "Server-rendered Blade",
                          "static": "Plain static HTML"}.get(stack, "Static"),
            "hosting": "Containerised or static hosting behind a TLS reverse proxy",
        },
        "database": db,
        "design_direction": f"{req['tone'].capitalize()} visual language, generous whitespace, strong typography and imagery centred on {req['topic']}.",
        "dev_plan": ["Scaffold project from stack template", "Apply brand tokens", "Render pages from content model",
                     "Generate SEO assets", "Build production artefact", "Run quality gate", "Deploy and verify"],
    }


# --------------------------------------------------------------------------- branding

def brand(req: dict) -> dict:
    theme = THEMES[req["theme"]]
    p = theme["palette"]
    r = rng_for(req["site_name"], "brand")
    return {
        "name": req["site_name"],
        "tagline": r.choice([
            f"Practical ideas for {req['topic']} that fit real life.",
            f"Your trusted guide to {req['topic']}.",
            f"Make {req['topic']} simple, joyful and lasting.",
            f"Where {req['topic']} meets everyday life.",
        ]),
        "palette": {"primary": p[0], "secondary": p[1], "accent": p[2], "background": p[3], "surface": p[4], "text": p[5], "muted": p[6]},
        "fonts": {"heading": theme["fonts"][0], "body": theme["fonts"][1]},
        "style": theme["style"],
        "dark": theme["dark"],
        "voice": f"Warm, knowledgeable and concise. Speaks to {req['audience']} without jargon.",
        "radius": r.choice(["10px", "14px", "18px"]),
    }


# --------------------------------------------------------------------------- content

_FEATURE_POOL = [
    ("Practical guides", "Step-by-step guidance on {topic} you can put into action this week."),
    ("Honest perspective", "Balanced, transparent advice — what works, what doesn't and why."),
    ("Community driven", "Ideas shaped by readers who are on the same journey with {topic}."),
    ("Always up to date", "Content reviewed regularly so it reflects current thinking on {topic}."),
    ("Built for beginners", "Clear explanations that make {topic} approachable from day one."),
    ("Expert curated", "Resources selected for quality, so you spend less time searching."),
]
_ICONS = ["compass", "leaf", "spark", "shield", "heart", "star"]

_ARTICLE_PATTERNS = [
    ("A Beginner's Guide to {T}", "Guides"),
    ("{n} Simple Ways to Get Started with {T}", "Tips"),
    ("Common Myths About {T}, Explained", "Insights"),
    ("How to Build a Lasting {T} Routine", "Guides"),
    ("What Experts Wish You Knew About {T}", "Insights"),
    ("The Essential {T} Checklist", "Tips"),
]

_PARA = [
    "{T} can feel overwhelming at first, but the fundamentals are easier than most people expect. The key is to start small, stay consistent and focus on the changes that matter most to you.",
    "Before diving in, take a moment to define what success looks like. Clear goals make it far easier to choose the right approach to {t} and to notice your progress along the way.",
    "One of the most effective habits is to review what you already do. Small adjustments to existing routines tend to stick better than dramatic overhauls, and they build momentum quickly.",
    "It also helps to learn from others. Communities, local groups and trusted resources can shorten the learning curve and keep you motivated when progress feels slow.",
    "Remember that there is no single perfect path. What works for one person may not suit another, so treat every idea as an experiment and keep what genuinely improves your day.",
    "Finally, revisit your approach every few months. As your confidence with {t} grows, you will spot new opportunities to go further — and you will have the experience to do it well.",
    "Quality information matters. Look for sources that explain their reasoning, cite evidence where it exists and are honest about uncertainty instead of promising quick fixes.",
    "Costs are often lower than people assume. Many improvements in {t} begin with changing habits rather than buying something new, which makes them accessible to almost everyone.",
]


def _article_body(r: random.Random, topic: str) -> list[str]:
    paras = r.sample(_PARA, 5)
    return [p.format(T=title_case(topic), t=topic) for p in paras]


def content(req: dict, plan_: dict, brand_: dict) -> dict:
    r = rng_for(req["site_name"], req["topic"], "content")
    topic, T = req["topic"], title_case(req["topic"])
    feats = r.sample(_FEATURE_POOL, 4)
    articles = []
    for i, (pat, cat) in enumerate(r.sample(_ARTICLE_PATTERNS, 4)):
        title = pat.format(T=T, n=r.choice([5, 7, 10]))
        body = _article_body(r, topic)
        articles.append({
            "slug": slugify(title),
            "title": title,
            "category": cat,
            "excerpt": body[0][:150].rsplit(" ", 1)[0] + "…",
            "body": body,
            "read_minutes": 3 + i,
            "image_prompt": f"Editorial photograph illustrating {title.lower()}, {brand_['style']} mood, natural light",
        })
    products = []
    if req.get("ecommerce"):
        for i, adj in enumerate(r.sample(["Classic", "Essential", "Premium", "Everyday", "Signature", "Starter"], 6)):
            products.append({
                "slug": slugify(f"{adj} {T} kit {i}"),
                "name": f"{adj} {T} {r.choice(['Kit', 'Set', 'Bundle', 'Edition'])}",
                "price": round(r.uniform(19, 149), 2),
                "description": f"A thoughtfully designed {adj.lower()} option for anyone getting serious about {topic}.",
            })
    return {
        "home": {
            "hero_title": r.choice([f"{T}, made simple.", f"Rethink {topic}.", f"Live better with {topic}.", f"Your journey into {topic} starts here."]),
            "hero_subtitle": f"{brand_['name']} brings together practical guides, honest advice and fresh ideas for {req['audience']}.",
            "cta_primary": "Explore the journal",
            "cta_secondary": "Get in touch",
            "features": [{"title": a, "text": b.format(topic=topic), "icon": _ICONS[i]} for i, (a, b) in enumerate(feats)],
            "cta_title": f"Ready to take the next step with {topic}?",
            "cta_text": "Tell us what you are working on and we will point you to the right resources.",
        },
        "about": {
            "title": f"About {brand_['name']}",
            "intro": f"We started {brand_['name']} because good information about {topic} was scattered, contradictory or hidden behind jargon.",
            "body": [
                f"Our mission is simple: make {topic} accessible to everyone. We research carefully, write plainly and focus on ideas you can actually use.",
                "Every article is reviewed for clarity and accuracy before it is published, and we update older pieces as new evidence and better practices emerge.",
            ],
            "values": [
                {"title": "Clarity", "text": "Plain language over buzzwords, always."},
                {"title": "Integrity", "text": "Honest recommendations with no hidden agenda."},
                {"title": "Progress", "text": "Small, steady steps that add up over time."},
            ],
        },
        "services": {
            "title": "What we offer",
            "intro": f"Everything you need to make confident decisions about {topic}.",
            "items": [
                {"title": "In-depth guides", "text": f"Structured guides that walk you through {topic} from first principles."},
                {"title": "Checklists & tools", "text": "Printable checklists and simple tools to keep you on track."},
                {"title": "Expert Q&A", "text": "Answers to your questions from people with real experience."},
                {"title": "Community updates", "text": "A friendly newsletter with the best new ideas, once a month."},
            ],
        },
        "articles": articles,
        "categories": [{"name": c, "description": f"{c} about {topic}."} for c in sorted({a["category"] for a in articles})],
        "faq": [
            {"q": f"Is {topic} expensive to get started with?", "a": f"Not necessarily. Many first steps in {topic} cost little or nothing — they start with small changes to habits you already have."},
            {"q": f"I'm a complete beginner. Where should I start?", "a": f"Start with our beginner's guide, pick one idea that fits your situation and build from there."},
            {"q": "How often is new content published?", "a": "We publish new articles regularly and review existing ones so they stay accurate."},
            {"q": "Can I suggest a topic?", "a": "Absolutely — use the contact form and tell us what you would like us to cover."},
            {"q": f"How do you make sure information is accurate?", "a": "We check claims against reputable sources and clearly flag anything that is opinion or still debated."},
        ],
        "contact": {"title": "Get in touch", "intro": "Questions, ideas or feedback? We read every message.", "email": f"hello@{slugify(brand_['name'])}.example"},
        "products": products,
    }


# --------------------------------------------------------------------------- SEO

def seo(req: dict, plan_: dict, brand_: dict, content_: dict) -> dict:
    topic = req["topic"]
    pages = {}
    for p in plan_["sitemap"]:
        if p["slug"] == "":
            title = f"{brand_['name']} — {brand_['tagline'].rstrip('.')}"
            if len(title) > 60:
                title = f"{brand_['name']} — {req['topic_title']}"
            desc = content_["home"]["hero_subtitle"]
        else:
            title = f"{p['title']} | {brand_['name']}"
            desc = f"{p['purpose']} — {brand_['name']}, your resource for {topic}."
        pages[p["slug"]] = {"title": clip(title, 62), "description": clip(desc, 158), "keywords": [topic, brand_["name"], p["title"].lower()]}
    for a in content_["articles"]:
        pages[f"blog/{a['slug']}"] = {"title": clip(f"{a['title']} | {brand_['name']}", 62), "description": clip(a["excerpt"], 158), "keywords": [topic, a["category"].lower()]}
    return {
        "pages": pages,
        "keywords": [topic, f"{topic} guide", f"{topic} tips", f"best {topic} advice", f"{topic} for beginners"],
        "organization": {"@context": "https://schema.org", "@type": "Organization", "name": brand_["name"], "description": brand_["tagline"]},
    }

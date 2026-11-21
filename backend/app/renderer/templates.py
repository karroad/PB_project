"""Jinja2 templates for the static build that every stack adapter produces as its preview/deploy artefact."""

BASE = r"""<!doctype html>
<html lang="{{ lang }}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ meta.title }}</title>
<meta name="description" content="{{ meta.description }}">
<meta name="keywords" content="{{ meta.keywords | join(', ') }}">
<link rel="canonical" href="{{ base_url }}{{ path }}">
<meta property="og:type" content="website">
<meta property="og:title" content="{{ meta.title }}">
<meta property="og:description" content="{{ meta.description }}">
<meta property="og:image" content="{{ base_url }}{{ images.hero }}">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="{{ brand.palette.primary }}">
<link rel="icon" href="{{ root }}{{ images.logo }}" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family={{ brand.fonts.heading | replace(' ', '+') }}:wght@500;600;700&family={{ brand.fonts.body | replace(' ', '+') }}:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{{ root }}assets/css/site.css">
<script type="application/ld+json">{{ jsonld | safe }}</script>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="nav">
  <div class="wrap nav-inner">
    <a class="logo" href="{{ root }}"><img src="{{ root }}{{ images.logo }}" alt="" width="36" height="36"><span>{{ brand.name }}</span></a>
    <button class="nav-toggle" aria-label="Open menu" aria-expanded="false">&#9776;</button>
    <nav class="nav-links" aria-label="Main">
      {% for p in nav %}<a href="{{ root }}{{ p.slug }}{{ '/' if p.slug }}" {% if p.slug == current %}aria-current="page"{% endif %}>{{ p.title }}</a>{% endfor %}
    </nav>
  </div>
</header>
<main id="main">
{% block main %}{% endblock %}
</main>
<footer class="footer">
  <div class="wrap footer-inner">
    <div><a class="logo" href="{{ root }}"><img src="{{ root }}{{ images.logo }}" alt="" width="30" height="30"><span>{{ brand.name }}</span></a><p class="muted">{{ brand.tagline }}</p></div>
    <nav aria-label="Footer">{% for p in nav %}<a href="{{ root }}{{ p.slug }}{{ '/' if p.slug }}">{{ p.title }}</a>{% endfor %}</nav>
  </div>
  <div class="wrap fine">© {{ year }} {{ brand.name }}. Generated with SiteForge AI.</div>
</footer>
<script src="{{ root }}assets/js/site.js" defer></script>
</body>
</html>"""

HOME = r"""{% extends "base.html" %}{% block main %}
<section class="hero">
  <div class="wrap hero-grid">
    <div class="reveal">
      <span class="eyebrow">{{ req.topic_title }}</span>
      <h1>{{ c.home.hero_title }}</h1>
      <p class="lead">{{ c.home.hero_subtitle }}</p>
      <div class="actions"><a class="btn" href="{{ root }}blog/">{{ c.home.cta_primary }}</a><a class="btn ghost" href="{{ root }}contact/">{{ c.home.cta_secondary }}</a></div>
    </div>
    <div class="hero-art reveal"><img src="{{ root }}{{ images.hero }}" alt="{{ req.topic_title }} illustration" width="1600" height="900"></div>
  </div>
</section>
<section class="section">
  <div class="wrap">
    <h2 class="center">Why {{ brand.name }}</h2>
    <div class="grid four">{% for f in c.home.features %}
      <article class="card reveal"><div class="icon icon-{{ f.icon }}"></div><h3>{{ f.title }}</h3><p>{{ f.text }}</p></article>{% endfor %}
    </div>
  </div>
</section>
<section class="section alt">
  <div class="wrap">
    <div class="row-head"><h2>From the journal</h2><a href="{{ root }}blog/">All articles →</a></div>
    <div class="grid three">{% for a in c.articles[:3] %}
      <a class="post-card reveal" href="{{ root }}blog/{{ a.slug }}/"><img src="{{ root }}{{ images.articles[a.slug] }}" alt="" loading="lazy" width="1600" height="900"><div><span class="tag">{{ a.category }}</span><h3>{{ a.title }}</h3><p>{{ a.excerpt }}</p></div></a>{% endfor %}
    </div>
  </div>
</section>
<section class="section">
  <div class="wrap narrow">
    <h2 class="center">Questions, answered</h2>
    {% for f in c.faq[:3] %}<details class="faq"><summary>{{ f.q }}</summary><p>{{ f.a }}</p></details>{% endfor %}
    <p class="center"><a href="{{ root }}faq/">See all questions →</a></p>
  </div>
</section>
<section class="cta"><div class="wrap cta-inner reveal"><h2>{{ c.home.cta_title }}</h2><p>{{ c.home.cta_text }}</p><a class="btn light" href="{{ root }}contact/">Contact us</a></div></section>
{% endblock %}"""

ABOUT = r"""{% extends "base.html" %}{% block main %}
<section class="page-head"><div class="wrap"><h1>{{ c.about.title }}</h1><p class="lead">{{ c.about.intro }}</p></div></section>
<section class="section"><div class="wrap split">
  <div>{% for p in c.about.body %}<p>{{ p }}</p>{% endfor %}</div>
  <img class="rounded" src="{{ root }}{{ images.about }}" alt="About {{ brand.name }}" loading="lazy" width="1600" height="900">
</div></section>
<section class="section alt"><div class="wrap"><h2 class="center">Our values</h2><div class="grid three">{% for v in c.about['values'] %}
  <article class="card"><h3>{{ v.title }}</h3><p>{{ v.text }}</p></article>{% endfor %}</div></div></section>
{% endblock %}"""

SERVICES = r"""{% extends "base.html" %}{% block main %}
<section class="page-head"><div class="wrap"><h1>{{ c.services.title }}</h1><p class="lead">{{ c.services.intro }}</p></div></section>
<section class="section"><div class="wrap grid two">{% for s in c.services['items'] %}
  <article class="card big reveal"><span class="num">0{{ loop.index }}</span><h3>{{ s.title }}</h3><p>{{ s.text }}</p></article>{% endfor %}
</div></section>
{% endblock %}"""

SHOP = r"""{% extends "base.html" %}{% block main %}
<section class="page-head"><div class="wrap"><h1>Shop</h1><p class="lead">Carefully selected essentials for {{ req.topic }}.</p></div></section>
<section class="section"><div class="wrap grid three">{% for p in c.products %}
  <article class="card product reveal"><img src="{{ root }}{{ images.products[p.slug] }}" alt="{{ p.name }}" loading="lazy" width="1200" height="1200"><h3>{{ p.name }}</h3><p>{{ p.description }}</p><div class="price">${{ '%.2f' % p.price }}</div><a class="btn small" href="{{ root }}contact/">Enquire</a></article>{% endfor %}
</div></section>
{% endblock %}"""

BLOG = r"""{% extends "base.html" %}{% block main %}
<section class="page-head"><div class="wrap"><h1>Journal</h1><p class="lead">Original articles about {{ req.topic }}.</p>
<div class="chips">{% for cat in c.categories %}<span class="tag">{{ cat.name }}</span>{% endfor %}</div></div></section>
<section class="section"><div class="wrap grid two">{% for a in c.articles %}
  <a class="post-card reveal" href="{{ root }}blog/{{ a.slug }}/"><img src="{{ root }}{{ images.articles[a.slug] }}" alt="" loading="lazy" width="1600" height="900"><div><span class="tag">{{ a.category }} · {{ a.read_minutes }} min read</span><h2 class="h3">{{ a.title }}</h2><p>{{ a.excerpt }}</p></div></a>{% endfor %}
</div></section>
{% endblock %}"""

POST = r"""{% extends "base.html" %}{% block main %}
<article class="post">
  <header class="page-head"><div class="wrap narrow"><a href="{{ root }}blog/">← Journal</a><span class="tag">{{ a.category }} · {{ a.read_minutes }} min read</span><h1>{{ a.title }}</h1></div></header>
  <div class="wrap narrow"><img class="rounded" src="{{ root }}{{ images.articles[a.slug] }}" alt="{{ a.title }}" width="1600" height="900">
  {% for p in a.body %}<p>{{ p }}</p>{% endfor %}
  <div class="callout"><strong>Keep exploring.</strong> <a href="{{ root }}blog/">Read more from the journal</a> or <a href="{{ root }}contact/">send us a question</a>.</div></div>
</article>
{% endblock %}"""

FAQ = r"""{% extends "base.html" %}{% block main %}
<section class="page-head"><div class="wrap narrow"><h1>Frequently asked questions</h1><p class="lead">Straight answers about {{ req.topic }} and {{ brand.name }}.</p></div></section>
<section class="section"><div class="wrap narrow">{% for f in c.faq %}<details class="faq"{% if loop.first %} open{% endif %}><summary>{{ f.q }}</summary><p>{{ f.a }}</p></details>{% endfor %}</div></section>
<script type="application/ld+json">{{ faq_jsonld | safe }}</script>
{% endblock %}"""

CONTACT = r"""{% extends "base.html" %}{% block main %}
<section class="page-head"><div class="wrap narrow"><h1>{{ c.contact.title }}</h1><p class="lead">{{ c.contact.intro }}</p></div></section>
<section class="section"><div class="wrap narrow">
  <form class="form" method="post" action="{{ form_action }}">
    <input type="text" name="_hp" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true">
    <label>Name<input name="name" required maxlength="120" autocomplete="name"></label>
    <label>Email<input type="email" name="email" required maxlength="200" autocomplete="email"></label>
    <label>Message<textarea name="message" rows="6" required maxlength="4000"></textarea></label>
    <button class="btn" type="submit">Send message</button>
  </form>
  <p class="muted center">Or email us at {{ c.contact.email }}</p>
</div></section>
{% endblock %}"""

THANKS = r"""{% extends "base.html" %}{% block main %}
<section class="page-head"><div class="wrap narrow center"><h1>Thank you!</h1><p class="lead">Your message has been received. We'll get back to you soon.</p><a class="btn" href="{{ root }}">Back to home</a></div></section>
{% endblock %}"""

NOT_FOUND = r"""{% extends "base.html" %}{% block main %}
<section class="page-head"><div class="wrap narrow center"><h1>Page not found</h1><p class="lead">The page you are looking for doesn't exist.</p><a class="btn" href="{{ root }}">Go home</a></div></section>
{% endblock %}"""

CSS = r"""
:root{--primary:{{ p.primary }};--secondary:{{ p.secondary }};--accent:{{ p.accent }};--bg:{{ p.background }};--surface:{{ p.surface }};--text:{{ p.text }};--muted:{{ p.muted }};--radius:{{ brand.radius }};--hf:'{{ brand.fonts.heading }}',Georgia,serif;--bf:'{{ brand.fonts.body }}',system-ui,sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:400 17px/1.7 var(--bf);-webkit-font-smoothing:antialiased}
img{max-width:100%;height:auto;display:block}
a{color:var(--primary)}
h1,h2,h3,.h3{font-family:var(--hf);line-height:1.15;margin:0 0 .5em;letter-spacing:-.01em}
h1{font-size:clamp(2.2rem,5vw,3.8rem)}h2{font-size:clamp(1.6rem,3vw,2.4rem)}h3,.h3{font-size:1.25rem}
p{margin:0 0 1em}.muted{color:var(--muted)}.center{text-align:center}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px}.narrow{max-width:760px}
.skip{position:absolute;left:-999px}.skip:focus{left:10px;top:10px;background:#fff;padding:8px;z-index:99}
.nav{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 82%,transparent);backdrop-filter:blur(12px);border-bottom:1px solid color-mix(in srgb,var(--text) 8%,transparent)}
.nav-inner{display:flex;align-items:center;justify-content:space-between;height:70px}
.logo{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--text);font:700 1.15rem var(--hf)}
.nav-links{display:flex;gap:26px}.nav-links a{color:var(--text);text-decoration:none;font-weight:500;opacity:.8}.nav-links a:hover,.nav-links a[aria-current]{opacity:1;color:var(--primary)}
.nav-toggle{display:none;background:none;border:0;font-size:1.6rem;color:var(--text);cursor:pointer}
.hero{padding:80px 0 60px;background:radial-gradient(1200px 500px at 85% -10%,color-mix(in srgb,var(--secondary) 28%,transparent),transparent),radial-gradient(800px 400px at -10% 110%,color-mix(in srgb,var(--accent) 18%,transparent),transparent)}
.hero-grid{display:grid;grid-template-columns:1.05fr 1fr;gap:56px;align-items:center}
.hero-art img{border-radius:calc(var(--radius)*2);box-shadow:0 30px 80px -30px color-mix(in srgb,var(--primary) 60%,transparent)}
.eyebrow,.tag{display:inline-block;font-size:.78rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--primary);background:color-mix(in srgb,var(--primary) 10%,transparent);padding:4px 12px;border-radius:99px;margin-bottom:14px}
.lead{font-size:1.2rem;color:var(--muted);max-width:640px}
.actions{display:flex;gap:14px;flex-wrap:wrap;margin-top:28px}
.btn{display:inline-block;background:var(--primary);color:#fff;padding:13px 26px;border-radius:99px;text-decoration:none;font-weight:600;border:2px solid var(--primary);cursor:pointer;font-size:1rem;transition:transform .2s,box-shadow .2s}
.btn:hover{transform:translateY(-2px);box-shadow:0 12px 30px -10px var(--primary)}
.btn.ghost{background:transparent;color:var(--primary)}.btn.light{background:#fff;color:var(--primary);border-color:#fff}.btn.small{padding:8px 18px;font-size:.9rem}
.section{padding:80px 0}.section.alt{background:color-mix(in srgb,var(--primary) 5%,var(--bg))}
.grid{display:grid;gap:24px}.grid.two{grid-template-columns:repeat(2,1fr)}.grid.three{grid-template-columns:repeat(3,1fr)}.grid.four{grid-template-columns:repeat(4,1fr)}
.card{background:var(--surface);border-radius:var(--radius);padding:28px;border:1px solid color-mix(in srgb,var(--text) 8%,transparent);transition:transform .25s,box-shadow .25s}
.card:hover{transform:translateY(-4px);box-shadow:0 20px 40px -24px color-mix(in srgb,var(--text) 40%,transparent)}
.card.big{padding:36px}.num{font:700 2.4rem var(--hf);color:var(--secondary)}
.icon{width:46px;height:46px;border-radius:14px;background:linear-gradient(135deg,var(--primary),var(--secondary));margin-bottom:16px;position:relative}
.icon::after{content:"";position:absolute;inset:13px;border-radius:50%;border:3px solid #fff}
.row-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:24px}
.post-card{display:flex;flex-direction:column;background:var(--surface);border-radius:var(--radius);overflow:hidden;text-decoration:none;color:var(--text);border:1px solid color-mix(in srgb,var(--text) 8%,transparent);transition:transform .25s}
.post-card:hover{transform:translateY(-4px)}.post-card img{aspect-ratio:16/9;object-fit:cover;width:100%}.post-card>div{padding:22px}.post-card p{color:var(--muted);font-size:.95rem}
.faq{background:var(--surface);border-radius:var(--radius);padding:18px 22px;margin-bottom:12px;border:1px solid color-mix(in srgb,var(--text) 8%,transparent)}
.faq summary{cursor:pointer;font-weight:600}.faq p{margin:12px 0 0;color:var(--muted)}
.cta{padding:30px 0 90px}.cta-inner{background:linear-gradient(135deg,var(--primary),color-mix(in srgb,var(--primary) 60%,var(--secondary)));color:#fff;border-radius:calc(var(--radius)*2);padding:64px 40px;text-align:center}
.cta-inner p{opacity:.9}
.page-head{padding:80px 0 30px}.page-head .tag{margin-left:12px}
.split{display:grid;grid-template-columns:1fr 1fr;gap:48px;align-items:center}.rounded{border-radius:calc(var(--radius)*1.5);margin:24px 0}
.chips{display:flex;gap:8px;flex-wrap:wrap}.post p{font-size:1.08rem}
.callout{border-left:4px solid var(--accent);background:var(--surface);padding:18px 22px;border-radius:8px;margin:36px 0 80px}
.product img{border-radius:calc(var(--radius) - 4px);margin-bottom:16px;aspect-ratio:1;object-fit:cover}.price{font:700 1.3rem var(--hf);margin-bottom:12px;color:var(--primary)}
.form{display:grid;gap:18px;background:var(--surface);padding:32px;border-radius:var(--radius);border:1px solid color-mix(in srgb,var(--text) 8%,transparent)}
.form label{display:grid;gap:6px;font-weight:600;font-size:.95rem}
.form input,.form textarea{font:inherit;padding:12px 14px;border-radius:10px;border:1px solid color-mix(in srgb,var(--text) 18%,transparent);background:var(--bg);color:var(--text)}
.form input:focus,.form textarea:focus{outline:2px solid var(--primary);border-color:transparent}.hp{display:none}
.footer{border-top:1px solid color-mix(in srgb,var(--text) 8%,transparent);padding:48px 0 24px}
.footer-inner{display:flex;justify-content:space-between;gap:24px;flex-wrap:wrap}.footer nav{display:flex;gap:18px;flex-wrap:wrap}.footer nav a{color:var(--muted);text-decoration:none}
.fine{color:var(--muted);font-size:.85rem;margin-top:28px}
.reveal{opacity:0;transform:translateY(18px);transition:opacity .7s ease,transform .7s ease}.reveal.in{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){.reveal{opacity:1;transform:none;transition:none}}
@media (max-width:900px){.hero-grid,.split{grid-template-columns:1fr}.grid.three,.grid.four{grid-template-columns:repeat(2,1fr)}}
@media (max-width:640px){.grid.two,.grid.three,.grid.four{grid-template-columns:1fr}.nav-toggle{display:block}
.nav-links{display:none;position:absolute;top:70px;left:0;right:0;flex-direction:column;gap:0;background:var(--bg);padding:10px 20px;border-bottom:1px solid color-mix(in srgb,var(--text) 10%,transparent)}
.nav-links.open{display:flex}.nav-links a{padding:12px 0}.section{padding:56px 0}.hero{padding:48px 0}}
"""

JS = r"""(function(){var t=document.querySelector('.nav-toggle'),l=document.querySelector('.nav-links');
if(t&&l){t.addEventListener('click',function(){var o=l.classList.toggle('open');t.setAttribute('aria-expanded',o)})}
var els=document.querySelectorAll('.reveal');if(!('IntersectionObserver' in window)){els.forEach(function(e){e.classList.add('in')});return}
var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){e.target.classList.add('in');io.unobserve(e.target)}})},{threshold:.12});
els.forEach(function(e){io.observe(e)})})();"""

TEMPLATES = {
    "base.html": BASE, "home.html": HOME, "about.html": ABOUT, "services.html": SERVICES, "shop.html": SHOP,
    "blog.html": BLOG, "post.html": POST, "faq.html": FAQ, "contact.html": CONTACT, "thanks.html": THANKS,
    "404.html": NOT_FOUND, "site.css": CSS,
}

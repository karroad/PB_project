from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from ...config import settings
from ...renderer.site_renderer import _env
from .base import StackAdapter, StackInfo

LAYOUT = """import type { Metadata } from "next";
import Link from "next/link";
import site from "@/content/site.json";
import "./globals.css";

export const metadata: Metadata = {
  title: site.seo.pages[""].title,
  description: site.seo.pages[""].description,
};

const nav = [{ slug: "", title: "Home" }, ...site.plan.sitemap.filter((p) => p.slug !== "").map((p) => ({ slug: p.slug, title: p.title }))];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang={site.requirements.language}>
      <body>
        <header className="nav">
          <div className="wrap nav-inner">
            <Link className="logo" href="/"><img src={"/" + site.images.logo} alt="" width={36} height={36} /><span>{site.brand.name}</span></Link>
            <nav className="nav-links">{nav.map((p) => <Link key={p.slug} href={"/" + p.slug}>{p.title}</Link>)}</nav>
          </div>
        </header>
        <main id="main">{children}</main>
        <footer className="footer"><div className="wrap fine">© {new Date().getFullYear()} {site.brand.name}</div></footer>
      </body>
    </html>
  );
}
"""

HOME = """import Link from "next/link";
import site from "@/content/site.json";

export default function Home() {
  const c = site.content;
  return (
    <>
      <section className="hero"><div className="wrap hero-grid">
        <div><span className="eyebrow">{site.requirements.topic_title}</span><h1>{c.home.hero_title}</h1><p className="lead">{c.home.hero_subtitle}</p>
          <div className="actions"><Link className="btn" href="/blog">{c.home.cta_primary}</Link><Link className="btn ghost" href="/contact">{c.home.cta_secondary}</Link></div></div>
        <div className="hero-art"><img src={"/" + site.images.hero} alt="" /></div>
      </div></section>
      <section className="section"><div className="wrap grid four">
        {c.home.features.map((f) => <article className="card" key={f.title}><div className="icon" /><h3>{f.title}</h3><p>{f.text}</p></article>)}
      </div></section>
      <section className="section alt"><div className="wrap grid three">
        {c.articles.slice(0, 3).map((a) => (
          <Link className="post-card" key={a.slug} href={`/blog/${a.slug}`}><img src={"/" + (site.images.articles as Record<string, string>)[a.slug]} alt="" /><div><span className="tag">{a.category}</span><h3>{a.title}</h3><p>{a.excerpt}</p></div></Link>
        ))}
      </div></section>
    </>
  );
}
"""

SIMPLE_PAGE = """import site from "@/content/site.json";

export const metadata = { title: site.seo.pages["__KEY__"]?.title, description: site.seo.pages["__KEY__"]?.description };

export default function Page() {
  const c = site.content as any;
  return (
    <section className="section"><div className="wrap narrow">
__BODY__
    </div></section>
  );
}
"""

BODIES = {
    "about": """      <h1>{c.about.title}</h1><p className="lead">{c.about.intro}</p>
      {c.about.body.map((p: string) => <p key={p}>{p}</p>)}""",
    "services": """      <h1>{c.services.title}</h1><p className="lead">{c.services.intro}</p>
      <div className="grid two">{c.services.items.map((s: any) => <article className="card" key={s.title}><h3>{s.title}</h3><p>{s.text}</p></article>)}</div>""",
    "faq": """      <h1>FAQ</h1>
      {c.faq.map((f: any) => <details className="faq" key={f.q}><summary>{f.q}</summary><p>{f.a}</p></details>)}""",
    "contact": """      <h1>{c.contact.title}</h1><p className="lead">{c.contact.intro}</p>
      <form className="form" method="post" action={process.env.NEXT_PUBLIC_FORM_ENDPOINT}>
        <label>Name<input name="name" required /></label><label>Email<input type="email" name="email" required /></label>
        <label>Message<textarea name="message" rows={6} required /></label><button className="btn" type="submit">Send</button>
      </form>""",
    "shop": """      <h1>Shop</h1>
      <div className="grid three">{c.products.map((p: any) => <article className="card product" key={p.slug}><img src={"/" + (site.images as any).products[p.slug]} alt={p.name} /><h3>{p.name}</h3><p>{p.description}</p><div className="price">${p.price.toFixed(2)}</div></article>)}</div>""",
}

BLOG = """import Link from "next/link";
import site from "@/content/site.json";

export const metadata = { title: site.seo.pages["blog"]?.title, description: site.seo.pages["blog"]?.description };

export default function Blog() {
  return (
    <section className="section"><div className="wrap"><h1>Journal</h1><div className="grid two">
      {site.content.articles.map((a) => (
        <Link className="post-card" key={a.slug} href={`/blog/${a.slug}`}><img src={"/" + (site.images.articles as Record<string, string>)[a.slug]} alt="" /><div><span className="tag">{a.category}</span><h2 className="h3">{a.title}</h2><p>{a.excerpt}</p></div></Link>
      ))}
    </div></div></section>
  );
}
"""

POST = """import { notFound } from "next/navigation";
import site from "@/content/site.json";

export function generateStaticParams() {
  return site.content.articles.map((a) => ({ slug: a.slug }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const meta = (site.seo.pages as Record<string, { title: string; description: string }>)[`blog/${slug}`];
  return { title: meta?.title, description: meta?.description };
}

export default async function Post({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const a = site.content.articles.find((x) => x.slug === slug);
  if (!a) notFound();
  return (
    <article className="post"><div className="wrap narrow">
      <span className="tag">{a.category}</span><h1>{a.title}</h1>
      <img className="rounded" src={"/" + (site.images.articles as Record<string, string>)[a.slug]} alt={a.title} />
      {a.body.map((p) => <p key={p}>{p}</p>)}
    </div></article>
  );
}
"""

SITEMAP = """import type { MetadataRoute } from "next";
import site from "@/content/site.json";

export const dynamic = "force-static";
const BASE = process.env.SITE_URL ?? "__BASE__";

export default function sitemap(): MetadataRoute.Sitemap {
  const pages = site.plan.sitemap.map((p) => p.slug).concat(site.content.articles.map((a) => `blog/${a.slug}`));
  return pages.map((p) => ({ url: `${BASE}${p}`, lastModified: new Date() }));
}
"""

ROBOTS = """import type { MetadataRoute } from "next";

export const dynamic = "force-static";

export default function robots(): MetadataRoute.Robots {
  return { rules: { userAgent: "*", allow: "/" }, sitemap: `${process.env.SITE_URL ?? "__BASE__"}sitemap.xml` };
}
"""

DOCKERFILE = """# Multi-stage build: static export served by nginx
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/out /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
"""

NGINX = """server {
  listen 80;
  root /usr/share/nginx/html;
  add_header X-Content-Type-Options nosniff always;
  add_header X-Frame-Options SAMEORIGIN always;
  add_header Referrer-Policy strict-origin-when-cross-origin always;
  location / { try_files $uri $uri/ $uri.html /404.html; }
}
"""


class NextJSAdapter(StackAdapter):
    info = StackInfo(
        key="nextjs", name="Next.js + Node.js", intended_use="Custom websites and applications",
        description="App Router project with static export, typed content model, sitemap/robots routes and an nginx Dockerfile.",
        deploy_model="docker", versions=["15", "16"],
    )

    def scaffold(self, spec: dict, source_dir: Path) -> list[str]:
        slug = spec["slug"]
        files = {
            "package.json": json.dumps({
                "name": slug, "version": "1.0.0", "private": True,
                "scripts": {"dev": "next dev", "build": "next build", "start": "npx serve out"},
                "dependencies": {"next": "^15.1.0", "react": "^19.0.0", "react-dom": "^19.0.0"},
                "devDependencies": {"typescript": "^5.6.0", "@types/react": "^19.0.0", "@types/node": "^22.0.0"},
            }, indent=2),
            "next.config.mjs": "/** @type {import('next').NextConfig} */\nexport default { output: 'export', trailingSlash: true, images: { unoptimized: true } };\n",
            "tsconfig.json": json.dumps({
                "compilerOptions": {"target": "ES2020", "lib": ["dom", "dom.iterable", "esnext"], "allowJs": True, "strict": True, "noEmit": True,
                                    "module": "esnext", "moduleResolution": "bundler", "jsx": "preserve", "resolveJsonModule": True,
                                    "esModuleInterop": True, "skipLibCheck": True, "incremental": True, "isolatedModules": True,
                                    "plugins": [{"name": "next"}], "paths": {"@/*": ["./*"]}},
                "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"], "exclude": ["node_modules"],
            }, indent=2),
            "content/site.json": self.site_json(spec),
            "app/layout.tsx": LAYOUT,
            "app/page.tsx": HOME,
            "app/blog/page.tsx": BLOG,
            "app/blog/[slug]/page.tsx": POST,
            "app/sitemap.ts": SITEMAP.replace("__BASE__", spec["base_url"]),
            "app/robots.ts": ROBOTS.replace("__BASE__", spec["base_url"]),
            "app/globals.css": _env.get_template("site.css").render(p=spec["brand"]["palette"], brand=spec["brand"]),
            "Dockerfile": DOCKERFILE,
            "nginx.conf": NGINX,
            ".env.example": f"SITE_URL={spec['base_url']}\nNEXT_PUBLIC_FORM_ENDPOINT={spec['form_action']}\n",
            ".gitignore": "node_modules\n.next\nout\n.env\n",
            "README.md": f"# {spec['brand']['name']}\n\nGenerated by SiteForge AI.\n\n```bash\nnpm install\nnpm run dev\nnpm run build   # static export in ./out\n```\n",
        }
        slugs = {p["slug"] for p in spec["plan"]["sitemap"]}
        for key, body in BODIES.items():
            if key in slugs and (key != "shop" or spec["content"].get("products")):
                files[f"app/{key}/page.tsx"] = SIMPLE_PAGE.replace("__KEY__", key).replace("__BODY__", body)
        written = self.write_files(source_dir, files)
        media = Path(spec["media_dir"])
        if media.exists():
            shutil.copytree(media, source_dir / "public" / "assets" / "media", dirs_exist_ok=True)
        return written

    async def build(self, spec, source_dir, build_dir, media_dir, base_url, slug, log):
        if not settings.BUILD_NEXTJS or not shutil.which("npm"):
            return await super().build(spec, source_dir, build_dir, media_dir, base_url, slug, log)
        await log("npm install (this can take a minute)")
        for cmd in (["npm", "install", "--no-audit", "--no-fund"], ["npm", "run", "build"]):
            proc = await asyncio.create_subprocess_exec(*cmd, cwd=source_dir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, shell=False)
            out, _ = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"{' '.join(cmd)} failed: {out.decode(errors='ignore')[-800:]}")
            await log(f"{' '.join(cmd)} ✓")
        if build_dir.exists():
            shutil.rmtree(build_dir)
        shutil.copytree(source_dir / "out", build_dir)
        return [str(p.relative_to(build_dir)).replace("\\", "/") for p in build_dir.rglob("*") if p.is_file()]

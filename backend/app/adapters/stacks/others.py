"""WordPress, Laravel and plain static adapters."""
from __future__ import annotations

import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ...renderer.site_renderer import _env
from .base import StackAdapter, StackInfo


def _css(spec: dict) -> str:
    return _env.get_template("site.css").render(p=spec["brand"]["palette"], brand=spec["brand"])


def _copy_media(spec: dict, dest: Path) -> None:
    media = Path(spec["media_dir"])
    if media.exists():
        shutil.copytree(media, dest, dirs_exist_ok=True)


# ============================================================================ static
class StaticAdapter(StackAdapter):
    info = StackInfo(
        key="static", name="Static HTML", intended_use="Landing pages and brochure sites",
        description="Framework-free HTML/CSS/JS. Smallest footprint, deploys anywhere.", deploy_model="static",
    )

    def scaffold(self, spec, source_dir):
        return self.write_files(source_dir, {
            "README.md": f"# {spec['brand']['name']}\n\nThe static build in `../build` is the source of truth for this stack.\n",
            "site.json": self.site_json(spec),
        })


# ============================================================================ WordPress
WP_COMPOSE = """services:
  db:
    image: mariadb:11
    restart: unless-stopped
    environment:
      MARIADB_DATABASE: wordpress
      MARIADB_USER: wordpress
      MARIADB_PASSWORD: ${DB_PASSWORD}
      MARIADB_RANDOM_ROOT_PASSWORD: "1"
    volumes: [db:/var/lib/mysql]
  wordpress:
    image: wordpress:6-php8.3-apache
    restart: unless-stopped
    depends_on: [db]
    environment:
      WORDPRESS_DB_HOST: db
      WORDPRESS_DB_USER: wordpress
      WORDPRESS_DB_PASSWORD: ${DB_PASSWORD}
      WORDPRESS_DB_NAME: wordpress
    volumes:
      - wp:/var/www/html
      - ./wp-content/themes/__SLUG__:/var/www/html/wp-content/themes/__SLUG__
      - ./import:/import
    labels:
      - traefik.enable=true
      - traefik.http.routers.__SLUG__.rule=Host(`__DOMAIN__`)
      - traefik.http.routers.__SLUG__.tls.certresolver=letsencrypt
volumes: { db: {}, wp: {} }
"""

WP_SETUP = """#!/bin/sh
# Provision WordPress with WP-CLI after `docker compose up -d`
set -e
docker compose run --rm wordpress sh -c '
  curl -sO https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar && chmod +x wp-cli.phar
  ./wp-cli.phar core install --url="$SITE_URL" --title="__NAME__" --admin_user=admin --admin_email="$ADMIN_EMAIL" --admin_password="$ADMIN_PASSWORD" --skip-email --allow-root
  ./wp-cli.phar theme activate __SLUG__ --allow-root
  ./wp-cli.phar plugin install wordpress-importer --activate --allow-root
  ./wp-cli.phar import /import/content.xml --authors=create --allow-root
  ./wp-cli.phar rewrite structure "/%postname%/" --allow-root
'
"""


class WordPressAdapter(StackAdapter):
    info = StackInfo(
        key="wordpress", name="WordPress", intended_use="Blogs, publications and CMS websites",
        description="Custom block-free theme, WXR content import, MariaDB + WordPress docker-compose and WP-CLI provisioning.",
        deploy_model="docker", versions=["6.x"],
    )

    def scaffold(self, spec, source_dir):
        slug, b, c = spec["slug"], spec["brand"], spec["content"]
        theme = f"wp-content/themes/{slug}"
        e = html.escape
        items = []
        now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        for i, a in enumerate(c["articles"], start=1):
            body = "".join(f"<p>{e(p)}</p>" for p in a["body"])
            items.append(f"""<item><title>{e(a['title'])}</title><pubDate>{now}</pubDate><dc:creator>admin</dc:creator>
<content:encoded><![CDATA[{body}]]></content:encoded><excerpt:encoded><![CDATA[{a['excerpt']}]]></excerpt:encoded>
<wp:post_id>{i}</wp:post_id><wp:post_name>{a['slug']}</wp:post_name><wp:status>publish</wp:status><wp:post_type>post</wp:post_type>
<category domain="category" nicename="{a['category'].lower()}"><![CDATA[{a['category']}]]></category></item>""")
        pages = [("About", "about", "".join(f"<p>{e(p)}</p>" for p in [c["about"]["intro"], *c["about"]["body"]])),
                 ("FAQ", "faq", "".join(f"<h3>{e(f['q'])}</h3><p>{e(f['a'])}</p>" for f in c["faq"]))]
        for j, (t, s, body) in enumerate(pages, start=100):
            items.append(f"""<item><title>{t}</title><content:encoded><![CDATA[{body}]]></content:encoded>
<wp:post_id>{j}</wp:post_id><wp:post_name>{s}</wp:post_name><wp:status>publish</wp:status><wp:post_type>page</wp:post_type></item>""")
        wxr = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:excerpt="http://wordpress.org/export/1.2/excerpt/" xmlns:content="http://purl.org/rss/1.0/modules/content/"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:wp="http://wordpress.org/export/1.2/">
<channel><title>{e(b['name'])}</title><description>{e(b['tagline'])}</description><wp:wxr_version>1.2</wp:wxr_version>
{''.join(items)}
</channel></rss>"""
        files = {
            f"{theme}/style.css": f"/*\nTheme Name: {b['name']}\nAuthor: SiteForge AI\nVersion: 1.0.0\n*/\n" + _css(spec),
            f"{theme}/functions.php": """<?php
add_action('after_setup_theme', function () {
  add_theme_support('title-tag'); add_theme_support('post-thumbnails'); add_theme_support('html5', ['search-form','gallery','caption']);
  register_nav_menus(['primary' => 'Primary']);
});
add_action('wp_enqueue_scripts', function () { wp_enqueue_style('theme', get_stylesheet_uri(), [], '1.0.0'); });
""",
            f"{theme}/header.php": """<!doctype html><html <?php language_attributes(); ?>><head><meta charset="<?php bloginfo('charset'); ?>"><meta name="viewport" content="width=device-width, initial-scale=1"><?php wp_head(); ?></head>
<body <?php body_class(); ?>><header class="nav"><div class="wrap nav-inner"><a class="logo" href="<?php echo esc_url(home_url('/')); ?>"><img src="<?php echo get_template_directory_uri(); ?>/assets/media/logo.svg" width="36" height="36" alt=""><span><?php bloginfo('name'); ?></span></a>
<?php wp_nav_menu(['theme_location' => 'primary', 'container' => 'nav', 'container_class' => 'nav-links', 'fallback_cb' => false]); ?></div></header><main id="main">""",
            f"{theme}/footer.php": """</main><footer class="footer"><div class="wrap fine">&copy; <?php echo date('Y'); ?> <?php bloginfo('name'); ?></div></footer><?php wp_footer(); ?></body></html>""",
            f"{theme}/index.php": """<?php get_header(); ?><section class="section"><div class="wrap grid two"><?php while (have_posts()) : the_post(); ?>
<a class="post-card" href="<?php the_permalink(); ?>"><div><h2 class="h3"><?php the_title(); ?></h2><p><?php echo esc_html(get_the_excerpt()); ?></p></div></a><?php endwhile; ?></div></section><?php get_footer(); ?>""",
            f"{theme}/single.php": """<?php get_header(); the_post(); ?><article class="post"><div class="wrap narrow"><h1><?php the_title(); ?></h1><?php the_content(); ?></div></article><?php get_footer(); ?>""",
            f"{theme}/page.php": """<?php get_header(); the_post(); ?><section class="section"><div class="wrap narrow"><h1><?php the_title(); ?></h1><?php the_content(); ?></div></section><?php get_footer(); ?>""",
            "import/content.xml": wxr,
            "docker-compose.yml": WP_COMPOSE.replace("__SLUG__", slug).replace("__DOMAIN__", spec.get("domain") or f"{slug}.localhost"),
            "setup.sh": WP_SETUP.replace("__SLUG__", slug).replace("__NAME__", b["name"].replace("'", "")),
            ".env.example": "DB_PASSWORD=change-me\nSITE_URL=https://example.com\nADMIN_EMAIL=admin@example.com\nADMIN_PASSWORD=change-me\n",
            "README.md": f"# {b['name']} (WordPress)\n\n1. `cp .env.example .env` and set secrets\n2. `docker compose up -d`\n3. `sh setup.sh`\n",
        }
        written = self.write_files(source_dir, files)
        _copy_media(spec, source_dir / theme / "assets" / "media")
        return written


# ============================================================================ Laravel
class LaravelAdapter(StackAdapter):
    info = StackInfo(
        key="laravel", name="Laravel", intended_use="Custom business applications",
        description="Overlay for a fresh Laravel 11 app: routes, controller, Blade views, JSON content store and Dockerfile.",
        deploy_model="docker", versions=["11.x", "12.x"],
    )

    def scaffold(self, spec, source_dir):
        files = {
            "overlay/storage/app/site.json": self.site_json(spec),
            "overlay/routes/web.php": """<?php
use App\\Http\\Controllers\\SiteController;
use Illuminate\\Support\\Facades\\Route;

Route::get('/', [SiteController::class, 'home']);
Route::get('/blog', [SiteController::class, 'blog']);
Route::get('/blog/{slug}', [SiteController::class, 'post']);
Route::post('/contact', [SiteController::class, 'contact'])->middleware('throttle:10,1');
Route::get('/{page}', [SiteController::class, 'page'])->whereIn('page', ['about', 'services', 'faq', 'contact', 'shop']);
""",
            "overlay/app/Http/Controllers/SiteController.php": """<?php
namespace App\\Http\\Controllers;

use Illuminate\\Http\\Request;
use Illuminate\\Support\\Facades\\Storage;

class SiteController extends Controller
{
    private function site(): array { return json_decode(Storage::get('site.json'), true); }
    public function home() { return view('home', ['site' => $this->site()]); }
    public function blog() { return view('blog', ['site' => $this->site()]); }
    public function post(string $slug) {
        $site = $this->site();
        $post = collect($site['content']['articles'])->firstWhere('slug', $slug) ?? abort(404);
        return view('post', ['site' => $site, 'post' => $post]);
    }
    public function page(string $page) { return view('page', ['site' => $this->site(), 'page' => $page]); }
    public function contact(Request $request) {
        $data = $request->validate(['name' => 'required|max:120', 'email' => 'required|email', 'message' => 'required|max:4000']);
        logger()->info('contact form', $data);
        return redirect('/contact')->with('status', 'Thanks! We will be in touch.');
    }
}
""",
            "overlay/resources/views/layouts/app.blade.php": """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ $title ?? $site['brand']['name'] }}</title><link rel="stylesheet" href="/css/site.css"></head><body>
<header class="nav"><div class="wrap nav-inner"><a class="logo" href="/"><span>{{ $site['brand']['name'] }}</span></a><nav class="nav-links">
@foreach ($site['plan']['sitemap'] as $p)<a href="/{{ $p['slug'] }}">{{ $p['title'] }}</a>@endforeach</nav></div></header>
<main id="main">@yield('content')</main><footer class="footer"><div class="wrap fine">&copy; {{ date('Y') }} {{ $site['brand']['name'] }}</div></footer></body></html>""",
            "overlay/resources/views/home.blade.php": """@extends('layouts.app')
@section('content')<section class="hero"><div class="wrap"><h1>{{ $site['content']['home']['hero_title'] }}</h1><p class="lead">{{ $site['content']['home']['hero_subtitle'] }}</p></div></section>
<section class="section"><div class="wrap grid four">@foreach ($site['content']['home']['features'] as $f)<article class="card"><h3>{{ $f['title'] }}</h3><p>{{ $f['text'] }}</p></article>@endforeach</div></section>@endsection""",
            "overlay/resources/views/blog.blade.php": """@extends('layouts.app')
@section('content')<section class="section"><div class="wrap grid two">@foreach ($site['content']['articles'] as $a)<a class="post-card" href="/blog/{{ $a['slug'] }}"><div><h2 class="h3">{{ $a['title'] }}</h2><p>{{ $a['excerpt'] }}</p></div></a>@endforeach</div></section>@endsection""",
            "overlay/resources/views/post.blade.php": """@extends('layouts.app', ['title' => $post['title']])
@section('content')<article class="post"><div class="wrap narrow"><h1>{{ $post['title'] }}</h1>@foreach ($post['body'] as $p)<p>{{ $p }}</p>@endforeach</div></article>@endsection""",
            "overlay/resources/views/page.blade.php": """@extends('layouts.app')
@section('content')<section class="section"><div class="wrap narrow">
@if ($page === 'faq') @foreach ($site['content']['faq'] as $f)<details class="faq"><summary>{{ $f['q'] }}</summary><p>{{ $f['a'] }}</p></details>@endforeach
@elseif ($page === 'contact')<form class="form" method="post" action="/contact">@csrf<label>Name<input name="name" required></label><label>Email<input type="email" name="email" required></label><label>Message<textarea name="message" required></textarea></label><button class="btn">Send</button></form>
@else <h1>{{ ucfirst($page) }}</h1> @foreach (($site['content'][$page]['body'] ?? [$site['content'][$page]['intro'] ?? '']) as $p)<p>{{ $p }}</p>@endforeach @endif
</div></section>@endsection""",
            "overlay/public/css/site.css": _css(spec),
            "Dockerfile": """FROM composer:2 AS vendor
WORKDIR /app
RUN composer create-project laravel/laravel . --no-interaction --prefer-dist
COPY overlay/ /app/

FROM php:8.3-apache
RUN a2enmod rewrite && sed -i 's#/var/www/html#/var/www/html/public#' /etc/apache2/sites-available/000-default.conf
COPY --from=vendor /app /var/www/html
RUN chown -R www-data:www-data /var/www/html/storage /var/www/html/bootstrap/cache
EXPOSE 80
""",
            "README.md": f"# {spec['brand']['name']} (Laravel)\n\n`docker build -t {spec['slug']} . && docker run -p 8080:80 {spec['slug']}`\n\nOr apply `overlay/` on top of `composer create-project laravel/laravel`.\n",
        }
        written = self.write_files(source_dir, files)
        _copy_media(spec, source_dir / "overlay" / "public" / "assets" / "media")
        return written

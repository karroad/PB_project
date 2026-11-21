"""Image generation: Fal.ai when a key is configured, otherwise generated SVG artwork."""
from __future__ import annotations

import logging
import math
from pathlib import Path

import httpx

from ..config import settings
from .offline import rng_for

log = logging.getLogger("siteforge.images")


def fal_key(override: str | None = None) -> str:
    return override or settings.FAL_KEY


async def fal_generate(prompt: str, dest: Path, key: str, size: str = "landscape_16_9") -> Path:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"https://fal.run/{settings.FAL_MODEL}",
            headers={"Authorization": f"Key {key}", "Content-Type": "application/json"},
            json={"prompt": prompt, "image_size": size, "num_images": 1, "enable_safety_checker": True},
        )
        resp.raise_for_status()
        url = resp.json()["images"][0]["url"]
        img = await client.get(url)
        img.raise_for_status()
    ext = ".png" if "png" in img.headers.get("content-type", "") else ".jpg"
    out = dest.with_suffix(ext)
    out.write_bytes(img.content)
    return out


def svg_artwork(seed: str, palette: dict, width: int = 1600, height: int = 900, label: str = "") -> str:
    r = rng_for(seed, "art")
    p = [palette["primary"], palette["secondary"], palette["accent"]]
    bg1, bg2 = r.sample(p, 2)
    blobs = []
    for i in range(7):
        cx, cy = r.randint(0, width), r.randint(0, height)
        rad = r.randint(height // 6, height // 2)
        blobs.append(f'<circle cx="{cx}" cy="{cy}" r="{rad}" fill="{r.choice(p)}" opacity="{r.uniform(0.25, 0.6):.2f}"/>')
    waves = []
    for i in range(4):
        amp, y0, ph = r.randint(20, 70), height * (0.55 + i * 0.1), r.uniform(0, math.pi)
        pts = " ".join(f"L{x},{y0 + amp * math.sin(x / width * math.pi * 2.2 + ph):.1f}" for x in range(0, width + 40, 40))
        waves.append(f'<path d="M0,{height} {pts} L{width},{height} Z" fill="{palette["surface"]}" opacity="{0.08 + i * 0.05:.2f}"/>')
    rings = "".join(
        f'<circle cx="{width * 0.78:.0f}" cy="{height * 0.3:.0f}" r="{60 + k * 38}" fill="none" stroke="{palette["surface"]}" stroke-opacity="{0.25 - k * 0.04:.2f}" stroke-width="2"/>'
        for k in range(5)
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{label}">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{bg1}"/><stop offset="1" stop-color="{bg2}"/></linearGradient>
<filter id="b"><feGaussianBlur stdDeviation="60"/></filter></defs>
<rect width="100%" height="100%" fill="url(#g)"/><g filter="url(#b)">{"".join(blobs)}</g>{rings}{"".join(waves)}
</svg>'''


def svg_logo(name: str, palette: dict) -> str:
    initials = "".join(w[0] for w in name.split()[:2]).upper() or "S"
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="{name} logo">
<defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{palette["primary"]}"/><stop offset="1" stop-color="{palette["secondary"]}"/></linearGradient></defs>
<rect width="64" height="64" rx="16" fill="url(#lg)"/>
<circle cx="50" cy="14" r="6" fill="{palette["accent"]}"/>
<text x="32" y="42" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="{26 if len(initials) > 1 else 32}" font-weight="700" fill="#ffffff">{initials}</text>
</svg>'''


async def generate_image(prompt: str, dest_no_ext: Path, palette: dict, key: str | None = None, size: str = "landscape_16_9") -> tuple[Path, str]:
    """Returns (path, source) where source is 'fal' or 'svg'."""
    dest_no_ext.parent.mkdir(parents=True, exist_ok=True)
    k = fal_key(key)
    if k:
        try:
            return await fal_generate(prompt, dest_no_ext, k, size), "fal"
        except (httpx.HTTPError, KeyError, IndexError) as e:
            log.warning("Fal.ai generation failed (%s), falling back to SVG", e)
    w, h = (1600, 900) if "landscape" in size else (1200, 1200)
    out = dest_no_ext.with_suffix(".svg")
    out.write_text(svg_artwork(str(dest_no_ext.name) + prompt, palette, w, h, label=prompt[:120]), encoding="utf-8")
    return out, "svg"

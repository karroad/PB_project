"""UI journey for the Servers manager (sandbox): SSH key → server → prepare → publish a site to it."""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "e2e-screenshots"); OUT.mkdir(exist_ok=True)
BASE, API = "http://localhost:3000", "http://localhost:8100"
problems, steps = [], []


def ok(msg):
    steps.append(msg); print("OK", msg, flush=True)


def wait_path(pg, pred_js, timeout=60000):
    pg.wait_for_function(f"(() => {{ const p = location.pathname; return {pred_js}; }})()", timeout=timeout)


for _ in range(60):
    try:
        if json.load(urllib.request.urlopen(API + "/api/health")).get("sandbox"):
            break
    except Exception:
        pass
    time.sleep(1)

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.set_default_timeout(30000)
    pg.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    pg.on("console", lambda m: problems.append(f"console.error: {m.text[:200]}") if m.type == "error" else None)
    pg.on("dialog", lambda d: d.accept())
    shot = lambda n, full=False: pg.screenshot(path=str(OUT / f"srv-{n}.png"), full_page=full)

    for _ in range(60):
        try:
            pg.goto(BASE + "/login"); break
        except Exception:
            time.sleep(2)
    pg.fill("#pw", "admin123"); pg.click("button[type=submit]"); wait_path(pg, "p === '/'")

    # --- SSH key: generate in-app, public key shown once
    pg.goto(BASE + "/servers"); expect(pg.get_by_text("No servers yet")).to_be_visible(); ok("servers page (empty state)")
    pg.get_by_role("tab", name=re.compile("SSH keys")).click()
    pg.get_by_role("button", name="Add SSH key").first.click()
    dlg = pg.get_by_role("dialog"); dlg.get_by_label("Name").fill("Deploy key"); dlg.get_by_role("button", name="Generate key").click()
    expect(dlg.get_by_text("ssh-ed25519", exact=False).first).to_be_visible(); time.sleep(0.4); shot("01-key-created")
    dlg.get_by_role("button", name="Done").click()
    expect(pg.get_by_text("SHA256:", exact=False).first).to_be_visible(); ok("SSH key generated; only public key + fingerprint shown")

    # --- add a (simulated) server and prepare it
    pg.get_by_role("tab", name=re.compile("Servers")).click()
    pg.get_by_role("button", name="Add server").first.click()
    dlg = pg.get_by_role("dialog"); dlg.get_by_label("Name", exact=True).fill("Hetzner FSN1 #1")
    dlg.get_by_text("Simulated server", exact=False).click()
    dlg.get_by_role("button", name="Connect & save").click()
    expect(pg.get_by_text("Hetzner FSN1 #1")).to_be_visible(); expect(pg.get_by_text("Connected").first).to_be_visible(); ok("server added and connection verified")
    pg.get_by_role("button", name="Prepare server").click()
    expect(pg.get_by_text("Ready", exact=True).first).to_be_visible(timeout=60000); ok("server prepared (web server installed)")
    pg.get_by_role("button", name="Health").click(); time.sleep(1.2); shot("02-server-ready"); ok("live health metrics")

    # --- build a site and publish it to the server
    pg.goto(BASE + "/new")
    pg.get_by_label("Website instruction").fill("A website about alpine hiking huts and mountain trails")
    pg.get_by_role("button", name=re.compile(r"^Static HTML")).click()
    pg.get_by_role("button", name="Build preview").click(); wait_path(pg, "p.startsWith('/sites/')")
    pg.get_by_text("Your preview is ready").wait_for(timeout=120000); ok("preview built")
    pg.get_by_role("button", name="Publish", exact=True).first.click()
    dlg = pg.get_by_role("dialog")
    dlg.get_by_role("button", name=re.compile("Your servers")).click()
    expect(dlg.get_by_label("Server")).to_have_value(re.compile(".+"))
    dlg.get_by_role("button", name=re.compile("Platform URL only")).click(); time.sleep(0.4); shot("03-publish-to-server")
    dlg.get_by_role("button", name="Publish website").click()
    pg.get_by_text("Your website is live").wait_for(timeout=120000); time.sleep(1.2); shot("04-live-on-server")
    ok("published to the server, verified on the server")
    live = pg.get_by_role("link", name=re.compile("Live:")).first.get_attribute("href")
    pg.goto(live); expect(pg.locator("h1").first).to_be_visible(); shot("05-site-from-server"); ok("site served from the server's release folder")

    pg.goto(BASE + "/servers"); expect(pg.get_by_role("link", name=re.compile("Alpine|Huts|Trails|Collective|Journal|Lab|Atlas|Commons|Studio|Hub|Co\\.", re.I)).first).to_be_visible()
    time.sleep(0.8); shot("06-server-with-site"); ok("server card lists its website")
    b.close()

print("\nSTEPS PASSED:", len(steps))
print("PROBLEMS:", ("\n".join(dict.fromkeys(problems)) or "none").encode("ascii", "replace").decode())

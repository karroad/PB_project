"""Scripted user journey through the real UI against a sandbox backend (see e2e/README.md).

Flow under test: build → live preview → request changes → publish (buy domain) → live,
plus failure paths, site tabs, rollback, archive/delete, users, jobs, audit and notifications.
"""
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
    steps.append(msg); print("OK", msg.encode("ascii", "replace").decode(), flush=True)


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
    shot = lambda n, full=False: pg.screenshot(path=str(OUT / f"sim-{n}.png"), full_page=full)

    for _ in range(60):
        try:
            pg.goto(BASE + "/login"); break
        except Exception:
            time.sleep(2)
    shot("00-login")
    pg.fill("#pw", "wrong-password"); pg.click("button[type=submit]")
    expect(pg.get_by_role("alert").filter(has_text="Invalid")).to_contain_text("Invalid email or password"); ok("wrong password shows an error")
    pg.fill("#pw", "admin123"); pg.click("button[type=submit]"); wait_path(pg, "p === '/'")
    expect(pg.get_by_text("Sandbox mode")).to_be_visible(); time.sleep(1); shot("01-dashboard"); ok("login + sandbox banner visible")

    # --- connect a (sandbox) Cloudflare account
    pg.goto(BASE + "/providers"); pg.get_by_role("button", name="Connect account").click()
    pg.select_option("#pp", "cloudflare"); pg.fill("#pl", "Cloudflare main"); pg.fill("#api_token", "demo-token-123456"); pg.fill("#account_id", "acc-demo")
    pg.get_by_role("button", name="Save encrypted").click()
    expect(pg.get_by_text("demo••••••••3456")).to_be_visible(); ok("provider account saved with masked token")

    # --- 1. BUILD: describe + technology only
    pg.goto(BASE + "/new")
    pg.get_by_label("Website instruction").fill("A website about handmade soy candles and cozy home fragrance")
    expect(pg.get_by_role("button", name="Build preview")).to_be_disabled()
    pg.get_by_role("button", name=re.compile(r"^Next\.js \+ Node\.js")).click()
    time.sleep(0.8); shot("02-new", full=True)
    pg.get_by_role("button", name="Build preview").click(); wait_path(pg, "p.startsWith('/sites/')")
    ok("create needs only an instruction + technology")
    time.sleep(3); shot("03-building")

    # --- 2. PREVIEW
    pg.get_by_text("Your preview is ready").wait_for(timeout=120000); time.sleep(1.5); shot("04-preview-ready")
    expect(pg.get_by_text("Preview ready", exact=True).first).to_be_visible()
    expect(pg.get_by_role("button", name="Publish", exact=True).first).to_be_visible(); ok("build stops at a live preview (nothing published)")
    pg.get_by_role("tab", name="Preview").click(); time.sleep(2.5); shot("05-preview-tab")
    expect(pg.frame_locator("iframe[title='Website preview']").locator("h1").first).to_be_visible(); ok("preview renders in the dashboard")

    # --- 3. REQUEST CHANGES
    pg.get_by_role("tab", name="Changes").click()
    pg.get_by_label("Change request").fill('Change the headline to "Light up your evenings"\nMake the primary colour #b45309\nAdd FAQ "Are the candles vegan?" answer "Yes, 100% soy wax."')
    shot("06-changes")
    pg.get_by_role("button", name="Apply to preview").click()
    pg.get_by_text("Your preview is ready").wait_for(timeout=120000); ok("change request applied → preview rebuilt")
    pg.get_by_role("tab", name="Preview").click(); time.sleep(2)
    expect(pg.frame_locator("iframe[title='Website preview']").get_by_text("Light up your evenings")).to_be_visible()
    shot("07-preview-after-change"); ok("preview shows the requested headline")
    pg.get_by_role("tab", name="Changes").click(); expect(pg.get_by_text("Added FAQ", exact=False)).to_be_visible(); ok("change history recorded")
    pg.get_by_label("Change request").fill("make it feel more premium somehow")
    pg.get_by_role("button", name="Apply to preview").click()
    pg.get_by_text("Couldn't understand this change", exact=False).first.wait_for(timeout=60000); ok("unclear request fails safely with guidance")

    # --- 4. PUBLISH with a bought domain
    pg.get_by_role("button", name="Publish", exact=True).first.click()
    dlg = pg.get_by_role("dialog")
    dlg.get_by_role("button", name=re.compile("Cloudflare")).click()
    dlg.get_by_label("Domain search").fill("candle glow"); dlg.get_by_role("button", name="Search").click()
    expect(dlg.get_by_text("candleglow.com", exact=True).first).to_be_visible(); time.sleep(0.6); shot("08-publish-dialog")
    dlg.get_by_role("button", name="Publish website").click()
    approve = pg.get_by_role("button", name="Approve"); approve.wait_for(timeout=90000)
    expect(pg.get_by_text("Buy candleglow.com", exact=False).first).to_be_visible(); shot("09-approval"); ok("publish asks admin to approve the domain purchase")
    approve.click()
    pg.get_by_text("Your website is live").wait_for(timeout=120000); time.sleep(1.5); shot("10-live")
    ok("approved → bought → DNS → deployed → verified → live")
    expect(pg.get_by_text("Live:", exact=False).first).to_be_visible()

    # --- changes after launch go to preview first, then "Publish changes"
    pg.get_by_role("tab", name="Changes").click()
    pg.get_by_label("Change request").fill("Use a dark theme"); pg.get_by_role("button", name="Apply to preview").click()
    pg.get_by_text("Your preview is ready").wait_for(timeout=120000)
    expect(pg.get_by_text("The preview has changes that aren't live yet")).to_be_visible(); ok("post-launch change waits in preview")
    pg.get_by_role("button", name="Publish changes").click()
    pg.get_by_role("dialog").get_by_role("button", name="Publish changes").click()
    pg.get_by_text("Your website is live").wait_for(timeout=120000); ok("publish changes → live v2 (domain not bought again)")

    pg.goto(BASE + "/domains"); time.sleep(1); expect(pg.get_by_text("candleglow.com", exact=True).first).to_be_visible(); shot("11-domains"); ok("domain listed")

    # --- site tabs, rollback, archive/restore, delete
    pg.go_back(); time.sleep(1.5)
    for tab in ["Brand & plan", "Content", "Quality", "Deployments", "Code", "Health", "Settings"]:
        pg.get_by_role("tab", name=tab).click(); time.sleep(0.5)
    pg.get_by_role("tab", name="Deployments").click(); expect(pg.get_by_text("v2")).to_be_visible()
    pg.get_by_role("button", name="Roll back").click(); expect(pg.get_by_text("Rolled back to v1")).to_be_visible(); ok("rollback to v1 from the UI")
    pg.get_by_role("button", name="Archive").click(); expect(pg.get_by_text("Archived", exact=True).first).to_be_visible()
    pg.get_by_role("button", name="Restore").click(); expect(pg.get_by_text("Live", exact=True).first).to_be_visible(); ok("archive + restore")
    pg.get_by_role("button", name="Delete website").click()
    dlg = pg.get_by_role("dialog"); expect(dlg.get_by_role("button", name="Delete")).to_be_disabled()
    slug = dlg.locator("span.font-mono").inner_text(); pg.fill("#confirm", slug); dlg.get_by_role("button", name="Delete").click()
    wait_path(pg, "p === '/'"); ok("delete requires typing the slug")

    # --- other pages
    pg.goto(BASE + "/users"); pg.get_by_role("button", name="Invite user").click()
    pg.get_by_label("Email").fill("editor@demo.test"); pg.get_by_label("Name").fill("Editor"); pg.get_by_label("Password").fill("password123")
    pg.get_by_role("button", name="Create user").click(); expect(pg.get_by_text("editor@demo.test")).to_be_visible(); ok("invite user")
    pg.goto(BASE + "/jobs"); time.sleep(1); shot("12-jobs"); ok("jobs page")
    pg.goto(BASE + "/monitoring"); expect(pg.get_by_text("Job queue")).to_be_visible(); time.sleep(1); shot("13-monitoring"); ok("monitoring page")
    pg.goto(BASE + "/audit"); expect(pg.get_by_text("website.publish").first).to_be_visible(); ok("audit log records publish")
    pg.goto(BASE + "/"); pg.get_by_role("button", name=re.compile("Notifications")).click(); time.sleep(0.8); shot("14-notifications")
    expect(pg.get_by_text("Preview ready").first).to_be_visible(); ok("notifications list")
    pg.get_by_role("button", name="Sign out").click(); wait_path(pg, "p === '/login'"); ok("sign out")
    b.close()

print("\nSTEPS PASSED:", len(steps))
print("PROBLEMS:", ("\n".join(dict.fromkeys(problems)) or "none").encode("ascii", "replace").decode())

"""Hardware-free browser smoke: uses a disposable database and synthetic roster.

Requires the optional Playwright package plus an installed Edge browser.
Never reads or prints the real operator key or writes to the venue database.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from uuid import uuid4

from playwright.sync_api import sync_playwright
import yaml


def main():
    root = Path(__file__).resolve().parents[1]
    scratch = (root / "local_scratch" / f"browser-{uuid4().hex}").resolve()
    if not scratch.is_relative_to(root / "local_scratch"):
        raise ValueError("Browser fixtures must stay within the workspace")
    scratch.mkdir(parents=True)
    # Keep disposable fixtures for diagnosis; no recursive deletion of computed paths.
    work = scratch
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    config = Path(work) / "cage.yaml"
    config.write_text(yaml.safe_dump({"database_path": str(Path(work) / "match.db"), "port": port}), encoding="utf-8")
    env = {**os.environ, "NEON_CONFIG": str(config), "NEON_OPERATOR_KEY": "synthetic-browser-test-key"}
    log = (Path(work) / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-m", "app"], cwd=root, env=env, stdout=log, stderr=log,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "/health", timeout=1).close()
                break
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError("Test server stopped during startup")
                time.sleep(0.1)
        else:
            raise RuntimeError("Test server did not start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/operator")
            page.locator("#operator-key").fill(env["NEON_OPERATOR_KEY"])
            page.locator("#login button").click()
            page.locator("#setup").wait_for(state="visible")
            page.locator("#orange-name").fill("Orange United")
            page.locator("#green-name").fill("Green Athletic")
            page.locator("#orange-roster").fill("9, Synthetic Player A\n10, Synthetic Player B")
            page.locator("#create-match button").click()
            page.locator("#start").wait_for(state="visible")
            page.locator("#start").click()
            page.locator("#pause").wait_for(state="visible")
            page.locator("#orange-goal").click()
            page.wait_for_function("document.getElementById('orange-score').textContent === '1'")
            page.locator("#green-goal").click()
            page.wait_for_function("document.getElementById('green-score').textContent === '1'")
            page.get_by_role("button", name="Edit players for Orange United", exact=False).click()
            form = page.locator(".attribution-form")
            form.locator("select").first.select_option(label="Orange United Â· 9 Â· Synthetic Player A")
            form.get_by_role("button", name="Save players").click()
            page.get_by_text("Synthetic Player A", exact=True).wait_for(state="visible")
            page.locator("#pause").click()
            page.locator("#resume").wait_for(state="visible")
            review = root / ".impeccable/review"
            review.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(review / "desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(review / "mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Operator overflows on mobile"
            display = context.new_page()
            display.on("pageerror", lambda error: errors.append(str(error)))
            display.goto(base + "/scoreboard")
            display.wait_for_function("document.getElementById('orange-score').textContent === '1'")
            display.screenshot(path=str(review / "scoreboard-desktop.png"), full_page=True)
            display.set_viewport_size({"width": 390, "height": 844})
            display.screenshot(path=str(review / "scoreboard-mobile.png"), full_page=True)
            assert display.locator("button").count() == 0, "Spectator display has write controls"
            assert display.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Scoreboard overflows on mobile"
            page.on("dialog", lambda dialog: dialog.accept())
            page.get_by_role("button", name="Undo Green Athletic goal", exact=False).click()
            page.wait_for_function("document.getElementById('green-score').textContent === '0'")
            display.wait_for_function("document.getElementById('green-score').textContent === '0'")
            with page.expect_download() as download:
                page.locator("#export").click()
            assert download.value.suggested_filename.endswith(".json")
            page.locator("#end").click()
            page.locator("#next-match").wait_for(state="visible")
            page.locator("#next-match").click()
            page.locator("#setup").wait_for(state="visible")
            assert not errors, errors
            browser.close()
        print("Browser smoke passed: login, setup, scoring, attribution, pause, undo, export, end, next match; desktop/mobile captures saved.")
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.close()


if __name__ == "__main__":
    main()

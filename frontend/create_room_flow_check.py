import re

from playwright.sync_api import sync_playwright


OVERLAY_SCREENSHOT = r"C:\Users\64294\AppData\Local\Temp\majority-create-room-overlay.png"
ROOM_SCREENSHOT = r"C:\Users\64294\AppData\Local\Temp\majority-create-room-entered.png"


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    browser_errors: list[str] = []
    failed_responses: list[str] = []
    page.on("console", lambda message: browser_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: browser_errors.append(str(error)))
    page.on("response", lambda response: failed_responses.append(f"{response.status} {response.url}") if response.status >= 400 else None)

    identity_response = page.request.post(
        "http://localhost:8000/api/players/identity",
        data={"username": "OwnerTest"},
    )
    assert identity_response.ok
    identity_seed = identity_response.json()

    page.goto("http://localhost:3000")
    page.evaluate("identity => localStorage.setItem('party-quiz-player', JSON.stringify(identity))", identity_seed)
    page.reload()
    page.wait_for_load_state("networkidle")
    page.locator(".create-room-button").wait_for()

    page.evaluate(
        """
        const realFetch = window.fetch.bind(window);
        window.fetch = async (...args) => {
          const request = new Request(...args);
          if (request.method === "POST" && request.url.endsWith("/api/rooms")) {
            await new Promise(resolve => setTimeout(resolve, 1200));
          }
          return realFetch(...args);
        };
        """
    )

    page.locator(".create-room-button").click()
    overlay = page.get_by_role("dialog")
    overlay.wait_for(state="visible")
    assert "専用ルームを作成しています" in overlay.inner_text()
    assert page.locator("main").get_attribute("inert") is not None
    assert page.locator(".refresh-room-button").is_disabled()
    page.wait_for_timeout(350)
    page.screenshot(path=OVERLAY_SCREENSHOT, full_page=True)

    page.wait_for_url(re.compile(r"/room/[A-Z0-9]{4}$"), timeout=15_000)
    page.locator(".waiting-card h2").wait_for(timeout=15_000)
    assert page.locator(".ready-list article").count() == 1
    assert "OwnerTest" in page.locator(".ready-list article").inner_text()
    assert "様" in page.locator(".ready-list article").inner_text()

    room_id = page.url.rsplit("/", 1)[-1]
    identity = page.evaluate("JSON.parse(localStorage.getItem('party-quiz-player'))")
    room_response = page.request.get(f"http://localhost:8000/api/rooms/{room_id}")
    assert room_response.ok
    players = room_response.json()["players"]
    assert len(players) == 1
    assert players[0]["id"] == identity["player_id"]
    page.screenshot(path=ROOM_SCREENSHOT, full_page=True)

    ignored_failures = [failure for failure in failed_responses if "favicon.ico" in failure]
    unexpected_failures = [failure for failure in failed_responses if failure not in ignored_failures]
    generic_resource_errors = [error for error in browser_errors if error.startswith("Failed to load resource")]
    unexpected_errors = [error for error in browser_errors if error not in generic_resource_errors]
    assert not unexpected_failures, unexpected_failures
    assert not unexpected_errors, unexpected_errors
    print(f"PASS room={room_id} players={len(players)} overlay_blocked=true")
    browser.close()

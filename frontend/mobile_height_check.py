from playwright.sync_api import Page, sync_playwright


VIEWPORTS = ((390, 844), (375, 667))


def assert_no_vertical_scroll(page: Page, label: str) -> None:
    metrics = page.evaluate(
        """() => ({
            viewport: window.innerHeight,
            document: document.documentElement.scrollHeight,
            body: document.body.scrollHeight,
        })"""
    )
    assert metrics["document"] <= metrics["viewport"] and metrics["body"] <= metrics["viewport"], (
        f"{label} overflows vertically: {metrics}"
    )


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    for width, height in VIEWPORTS:
        first_visit = browser.new_page(viewport={"width": width, "height": height})
        first_visit.goto("http://localhost:3000", wait_until="domcontentloaded")
        first_visit.locator(".identity-card").wait_for()
        assert_no_vertical_scroll(first_visit, f"first visit {width}x{height}")
        first_visit.close()

        admin_login = browser.new_page(viewport={"width": width, "height": height})
        admin_login.goto("http://localhost:3000/admin", wait_until="domcontentloaded")
        admin_login.locator(".admin-login .identity-card").wait_for()
        assert_no_vertical_scroll(admin_login, f"admin login {width}x{height}")
        admin_login.close()

        lobby = browser.new_page(viewport={"width": width, "height": height})
        lobby.route("**/api/rooms", lambda route: route.fulfill(json=[]))
        lobby.route(
            "**/api/room-options",
            lambda route: route.fulfill(json={"available_question_count": 10}),
        )
        lobby.add_init_script(
            """
            localStorage.setItem('party-quiz-player', JSON.stringify({
              player_id: 'mobile-height-check',
              session_id: 'mobile-height-session',
              username: '高さ確認'
            }));
            """
        )
        lobby.goto("http://localhost:3000", wait_until="domcontentloaded")
        lobby.locator(".lobby-banner").wait_for()
        assert_no_vertical_scroll(lobby, f"empty lobby {width}x{height}")
        lobby.close()

    browser.close()
    print("PASS mobile page heights")

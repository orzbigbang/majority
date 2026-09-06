from playwright.sync_api import sync_playwright


def snapshot(page):
    return page.evaluate(
        """
        () => {
          const banner = document.querySelector('.lobby-banner');
          const main = document.querySelector('main');
          const rect = banner?.getBoundingClientRect();
          return {
            bodyOverflow: document.body.style.overflow,
            mainInert: main?.hasAttribute('inert'),
            scrollX: window.scrollX,
            scrollY: window.scrollY,
            focus: document.activeElement?.className || document.activeElement?.tagName,
            banner: rect && { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
          };
        }
        """
    )


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    for width, height in ((1280, 900), (390, 844)):
        page = browser.new_page(viewport={"width": width, "height": height})
        page.add_init_script(
            """
            localStorage.setItem('party-quiz-player', JSON.stringify({
              player_id: 'cancel-ui-check',
              session_id: 'cancel-ui-session',
              username: 'UI確認'
            }));
            """
        )
        page.goto("http://localhost:3000", wait_until="domcontentloaded")
        page.locator(".create-room-button").wait_for()
        before = snapshot(page)

        for _ in range(2):
            page.locator(".create-room-button").click()
            page.locator(".room-setup-sheet").wait_for(state="visible")
            assert page.locator("main").get_attribute("inert") is not None
            assert page.evaluate("document.body.style.overflow") == "hidden"
            page.locator(".bottom-sheet-close").click()
            page.locator(".room-setup-sheet").wait_for(state="detached")

        after = snapshot(page)
        assert after["bodyOverflow"] == "", after
        assert after["mainInert"] is False, after
        assert after["scrollX"] == before["scrollX"], (before, after)
        assert after["scrollY"] == before["scrollY"], (before, after)
        assert after["banner"] == before["banner"], (before, after)
        assert "create-room-button" in after["focus"], after
        page.screenshot(
            path=f"room-setup-cancel-{width}x{height}.png",
            full_page=True,
        )
        print(width, height, before, after)
        page.close()
    browser.close()

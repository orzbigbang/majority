from playwright.sync_api import sync_playwright


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    for width, height in ((1280, 900), (390, 844)):
        page = browser.new_page(viewport={"width": width, "height": height})
        page.add_init_script(
            """
            localStorage.setItem('party-quiz-player', JSON.stringify({
              player_id: 'lobby-actions-check',
              session_id: 'lobby-actions-session',
              username: 'ロビー確認'
            }));
            Object.defineProperty(navigator, 'share', {
              configurable: true,
              value: async data => { window.__sharedGame = data; }
            });
            """
        )
        page.goto("http://localhost:3000", wait_until="domcontentloaded")
        rules_button = page.get_by_role("button", name="ルール")
        share_button = page.get_by_role("button", name="共有")
        rules_button.wait_for()
        assert rules_button.is_visible()
        assert share_button.is_visible()

        share_button.click()
        shared = page.evaluate("window.__sharedGame")
        assert shared["title"] == "マジョリティ", shared
        assert shared["url"] == "http://localhost:3000", shared

        rules_button.click()
        sheet = page.locator(".rules-sheet")
        sheet.wait_for(state="visible")
        assert page.get_by_role("heading", name="遊び方は4つだけ").is_visible()
        assert page.locator("main").get_attribute("inert") is not None
        page.locator(".bottom-sheet-close").click()
        sheet.wait_for(state="detached")

        header_box = page.locator(".lobby-heading").bounding_box()
        actions_box = page.locator(".lobby-header-actions").bounding_box()
        assert header_box and actions_box
        assert actions_box["x"] + actions_box["width"] <= width, (header_box, actions_box)
        print(width, height, shared, header_box, actions_box)
        page.close()
    browser.close()

import json
import time

from playwright.sync_api import sync_playwright


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 390, "height": 667},
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
    )
    context.add_init_script(
        """localStorage.setItem('party-quiz-player', JSON.stringify({
          player_id: 'ui-refinement-check',
          username: 'UI確認'
        }));"""
    )
    page = context.new_page()
    room_requests = 0

    def api_route(route):
        global room_requests
        url = route.request.url
        if url.endswith("/api/rooms"):
            room_requests += 1
            if room_requests > 1:
                time.sleep(0.15)
            route.fulfill(status=200, content_type="application/json", body="[]")
        elif url.endswith("/api/room-options"):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "available_question_count": 10,
                    "defaults": {
                        "max_players": 12,
                        "round_count": 1,
                        "selection_duration": 15,
                        "question_duration": 20,
                        "between_question_duration": 5,
                    },
                }),
            )
        elif url.endswith("/api/players/identity"):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"player_id": "ui-refinement-check", "username": "UI確認"}),
            )
        else:
            route.continue_()

    page.route("**/api/**", api_route)
    page.goto("http://localhost:3013", wait_until="domcontentloaded")
    page.get_by_role("button", name="遊び方を見る").wait_for(state="visible")
    assert page.evaluate("document.documentElement.scrollWidth === document.documentElement.clientWidth")

    refresh = page.get_by_role("button", name="更新", exact=True)
    refresh.tap()
    page.wait_for_function("!document.querySelector('.refresh-room-button').disabled")
    refresh_style = refresh.evaluate(
        """button => ({
          background: getComputedStyle(button).backgroundColor,
          hoverNone: matchMedia('(hover: none)').matches,
          hovered: button.matches(':hover')
        })"""
    )
    assert refresh_style["hoverNone"] is True
    assert refresh_style["hovered"] is True
    assert refresh_style["background"] == "rgba(0, 0, 0, 0)"

    page.get_by_role("button", name="ルームを作成").tap()
    page.get_by_role("button", name="標準", exact=True).wait_for(state="visible")
    assert page.get_by_role("button", name="標準", exact=True).get_attribute("aria-pressed") == "true"
    page.get_by_role("button", name="テンポよく", exact=True).tap()
    assert page.get_by_label("問題を選ぶ時間").get_attribute("value") == "10"
    assert page.get_by_label("回答時間").get_attribute("value") == "10"
    assert page.get_by_label("問題間の待ち時間").get_attribute("value") == "5"

    page.get_by_text("秒数を細かく設定", exact=True).click()
    stepper_sizes = page.locator(".number-stepper-button").evaluate_all(
        "buttons => buttons.map(button => ({ width: button.getBoundingClientRect().width, height: button.getBoundingClientRect().height }))"
    )
    assert len(stepper_sizes) == 10
    assert all(size["width"] >= 44 and size["height"] >= 44 for size in stepper_sizes)
    assert page.get_by_role("button", name="この設定で作成").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth === document.documentElement.clientWidth")

    print(json.dumps({"refresh": refresh_style, "stepperSizes": stepper_sizes[:2]}, ensure_ascii=False))
    browser.close()

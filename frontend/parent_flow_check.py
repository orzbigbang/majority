import json
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


def seed_identity(context, identity):
    encoded = json.dumps(json.dumps(identity))
    context.add_init_script(script=f"window.localStorage.setItem('party-quiz-player', {encoded});")


def assert_no_vertical_scroll(page, phase):
    metrics = page.evaluate("""() => ({
        viewport: window.innerHeight,
        document: document.documentElement.scrollHeight,
        body: document.body.scrollHeight,
    })""")
    assert metrics["document"] <= metrics["viewport"] and metrics["body"] <= metrics["viewport"], \
        f"{phase} overflows vertically: {metrics}"


def wait_for_progress_to_nearly_finish(page, selector):
    page.wait_for_function(
        """selector => {
            const track = document.querySelector(selector);
            const fill = track?.querySelector('i');
            if (!track || !fill) return false;
            const trackWidth = track.getBoundingClientRect().width;
            return trackWidth > 0 && fill.getBoundingClientRect().width / trackWidth <= 0.2;
        }""",
        arg=selector,
        timeout=5_000,
    )


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=["--no-proxy-server"])
    mobile_viewport = {
        "width": int(os.getenv("MOBILE_VIEWPORT_WIDTH", "390")),
        "height": int(os.getenv("MOBILE_VIEWPORT_HEIGHT", "844")),
    }
    owner_context = browser.new_context(viewport={"width": 1120, "height": 900})
    guest_context = browser.new_context(viewport=mobile_viewport)
    owner = owner_context.new_page()
    guest = guest_context.new_page()
    errors = []
    for page in (owner, guest):
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)

    api_base = os.getenv("API_URL", "http://127.0.0.1:8012")
    frontend_base = os.getenv("FRONTEND_URL", "http://127.0.0.1:3012")
    api = playwright.request.new_context(base_url=api_base)
    created = api.post("/api/rooms", data={
        "username": "ParentCheck",
        "player_id": "parent-check",
        "max_players": 6,
        "round_count": 1,
        "selection_duration": 15,
        "question_duration": 20,
        "between_question_duration": 10,
    })
    assert created.ok
    created_data = created.json()
    room_id = created_data["room"]["room_id"]
    guest_identity = api.post("/api/players/identity", data={"username": "GuestCheck", "player_id": "guest-check"}).json()

    seed_identity(owner_context, {"player_id": created_data["player_id"], "username": "ParentCheck", "session_id": created_data["session_id"]})
    seed_identity(guest_context, guest_identity)
    # Room pages keep a WebSocket open, so networkidle is intentionally never reached.
    owner.goto(f"{frontend_base}/room/{room_id}", wait_until="domcontentloaded", timeout=60_000)
    guest.goto(f"{frontend_base}/room/{room_id}", wait_until="domcontentloaded", timeout=60_000)
    try:
        owner.locator(".waiting-card").wait_for(timeout=15_000)
        guest.locator(".waiting-card").wait_for(timeout=15_000)
    except Exception:
        print(json.dumps({"owner_url": owner.url, "owner_body": owner.locator("body").inner_text(), "guest_url": guest.url, "guest_body": guest.locator("body").inner_text(), "errors": errors}, ensure_ascii=False))
        raise
    guest.locator(".ready-toggle").click()
    owner.get_by_role("button", name="ゲームを開始！").click()

    owner.locator(".intro-round-start").wait_for(timeout=15_000)
    assert "最初の親は" in guest.locator(".intro-round-start").inner_text()
    owner.locator(".intro-round-start").wait_for(state="hidden", timeout=5_000)
    owner.locator(".intro-parent-select").wait_for(timeout=5_000)
    assert "あなたが親です！" in owner.locator(".intro-parent-select").inner_text()
    assert "問題を選んでください。" in owner.locator(".intro-parent-select").inner_text()
    wait_for_progress_to_nearly_finish(owner, ".intro-parent-select .turn-intro-progress")
    owner.locator(".intro-parent-select").wait_for(state="hidden", timeout=5_000)
    owner.locator(".question-deck").wait_for(timeout=15_000)
    guest.locator(".wait-selecting").wait_for(timeout=15_000)
    assert_no_vertical_scroll(guest, "guest selecting wait")
    assert owner.locator(".question-deck-card").count() == 3
    assert owner.locator(".parent-selection-card .timer").is_visible()
    assert guest.locator(".parent-selection-card .timer").is_visible()
    assert owner.locator(".question-deck-card.is-active").count() == 1
    owner.get_by_role("button", name="次の問題").click()
    owner.wait_for_timeout(700)
    assert owner.locator(".question-deck-card.is-active").count() == 1
    owner.locator(".question-deck-card.is-active").get_by_role("button", name="この問題を選ぶ").click()

    owner.locator(".intro-parent-answer").wait_for(timeout=5_000)
    assert "あなたの回答を選んでください。" in owner.locator(".intro-parent-answer").inner_text()
    owner.locator(".intro-parent-answer").wait_for(state="hidden", timeout=5_000)
    owner.locator(".parent-first-answer").wait_for(timeout=5_000)
    guest.locator(".wait-answering").wait_for(timeout=5_000)
    assert_no_vertical_scroll(guest, "guest parent-answer wait")
    owner.get_by_role("button", name="押す", exact=True).click()
    owner.get_by_role("button", name="誰にも見せず「押す」で確定").click()

    owner.locator(".intro-players-answer").wait_for(timeout=5_000)
    assert "ここからは、みんなの回答タイムです。" in owner.locator(".intro-players-answer").inner_text()
    assert "あなたの番です！" in guest.locator(".intro-players-answer").inner_text()
    owner.locator(".intro-players-answer").wait_for(state="hidden", timeout=5_000)
    guest.locator(".question-card").wait_for(timeout=5_000)
    assert_no_vertical_scroll(guest, "guest question")
    owner.locator(".parent-answer-locked-status", has_text="みんなが回答しています").wait_for(timeout=5_000)
    assert "1 / 2 人が回答済み" in owner.locator(".parent-answer-locked-status").inner_text()
    owner.get_by_role("button", name="あなたの回答は確定済みです").wait_for(timeout=5_000)
    assert owner.locator(".choices .choice.a").is_disabled()
    guest.get_by_role("button", name="押す", exact=True).click()
    guest.get_by_role("button", name="「押す」で確定").click()
    guest.get_by_text("「押す」で確定しました").wait_for(timeout=5_000)
    guest.get_by_role("button", name="押さない", exact=True).click()
    confirmed_choice = guest.locator(".choices .choice.a")
    pending_choice = guest.locator(".choices .choice.b")
    assert "confirmed-choice" in (confirmed_choice.get_attribute("class") or "")
    assert "unselected-choice" not in (confirmed_choice.get_attribute("class") or "")
    assert "回答済み" in confirmed_choice.inner_text()
    assert "selected-choice" in (pending_choice.get_attribute("class") or "")
    assert "選択中" in pending_choice.inner_text()
    guest.wait_for_timeout(1_000)
    assert guest.locator(".question-card").is_visible(), "All answers must not skip the remaining question countdown"
    assert guest.locator(".intro-result-reveal").count() == 0
    guest.locator(".intro-result-reveal").wait_for(timeout=25_000)
    assert "結果発表！" in guest.locator(".intro-result-reveal").inner_text()
    assert_no_vertical_scroll(guest, "result reveal intro")
    wait_for_progress_to_nearly_finish(guest, ".intro-result-reveal .turn-intro-progress")
    owner.locator(".result-card").wait_for(timeout=5_000)
    guest.locator(".result-card").wait_for(timeout=5_000)
    guest.screenshot(path=str(Path(tempfile.gettempdir()) / "majority-parent-flow-mobile.png"), full_page=True)
    assert_no_vertical_scroll(guest, "result")

    output = Path(tempfile.gettempdir()) / "majority-parent-flow.png"
    owner.screenshot(path=str(output), full_page=True)

    guest.locator(".intro-parent-select").wait_for(timeout=15_000)
    assert "あなたが親です！" in guest.locator(".intro-parent-select").inner_text()
    assert "問題を選んでください。" in guest.locator(".intro-parent-select").inner_text()

    auto_created = api.post("/api/rooms", data={
        "username": "AutoParentCheck",
        "player_id": "auto-parent-check",
        "max_players": 6,
        "round_count": 1,
        "selection_duration": 5,
        "question_duration": 10,
        "between_question_duration": 10,
    }).json()
    auto_guest_identity = api.post("/api/players/identity", data={"username": "AutoGuestCheck", "player_id": "auto-guest-check"}).json()
    auto_owner_context = browser.new_context(viewport={"width": 1120, "height": 900})
    auto_guest_context = browser.new_context(viewport=mobile_viewport)
    seed_identity(auto_owner_context, {"player_id": auto_created["player_id"], "username": "AutoParentCheck", "session_id": auto_created["session_id"]})
    seed_identity(auto_guest_context, auto_guest_identity)
    auto_owner = auto_owner_context.new_page()
    auto_guest = auto_guest_context.new_page()
    for page in (auto_owner, auto_guest):
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    auto_room_id = auto_created["room"]["room_id"]
    auto_owner.goto(f"{frontend_base}/room/{auto_room_id}", wait_until="domcontentloaded", timeout=60_000)
    auto_guest.goto(f"{frontend_base}/room/{auto_room_id}", wait_until="domcontentloaded", timeout=60_000)
    auto_owner.locator(".waiting-card").wait_for(timeout=15_000)
    auto_guest.locator(".waiting-card").wait_for(timeout=15_000)
    auto_guest.locator(".ready-toggle").click()
    auto_owner.get_by_role("button", name="ゲームを開始！").click()
    auto_owner.locator(".question-deck-card").first.wait_for(timeout=15_000)
    assert auto_owner.locator(".question-deck-card").count() == 3
    auto_guest.locator(".intro-parent-answer", has_text="問題が自動で選ばれました").wait_for(timeout=15_000)
    auto_owner.locator(".intro-parent-answer", has_text="問題が自動で選ばれました").wait_for(timeout=5_000)
    auto_owner.locator(".parent-first-answer").wait_for(timeout=15_000)
    auto_guest.locator(".wait-answering").wait_for(timeout=5_000)
    auto_owner.get_by_role("button", name="あなたの回答は確定済みです").wait_for(timeout=15_000)
    auto_owner.locator(".parent-answer-locked-status", has_text="みんなが回答しています").wait_for(timeout=5_000)
    assert auto_owner.locator(".choices .choice.a").is_disabled()
    assert auto_owner.locator(".choices .choice.b").is_disabled()
    assert auto_owner.locator(".choices .selected-choice").count() == 1
    assert auto_owner.locator(".choices .selected-choice .choice-state").inner_text() == "回答済み"
    auto_owner.locator(".answer-notice", has_text="時間切れのため").wait_for(timeout=5_000)

    assert not errors, errors
    print(json.dumps({"room_id": room_id, "auto_room_id": auto_room_id, "screenshot": str(output), "auto_selected": True, "mobile_viewport": mobile_viewport}))
    api.dispose()
    browser.close()

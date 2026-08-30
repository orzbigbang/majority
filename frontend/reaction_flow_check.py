import json
import os
import tempfile

from playwright.sync_api import sync_playwright


def seed_identity(page, identity):
    encoded = json.dumps(json.dumps(identity))
    page.context.add_init_script(script=f"window.localStorage.setItem('party-quiz-player', {encoded});")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    owner_context = browser.new_context(viewport={"width": 1100, "height": 900})
    guest_context = browser.new_context(viewport={"width": 390, "height": 844})
    owner = owner_context.new_page()
    guest = guest_context.new_page()
    errors = []
    owner.on("pageerror", lambda error: errors.append(str(error)))
    guest.on("pageerror", lambda error: errors.append(str(error)))
    owner.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    guest.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)

    api = playwright.request.new_context(base_url="http://127.0.0.1:8011")
    created = api.post("/api/rooms", data={
        "username": "OwnerCheck", "player_id": "owner-check",
        "max_players": 6, "question_count": 1,
        "question_duration": 10, "between_question_duration": 10,
    })
    assert created.ok
    created_data = created.json()
    room_id = created_data["room"]["room_id"]
    guest_identity = api.post("/api/players/identity", data={"username": "GuestCheck", "player_id": "guest-check"}).json()

    seed_identity(owner, {"player_id": created_data["player_id"], "username": "OwnerCheck", "session_id": created_data["session_id"]})
    seed_identity(guest, guest_identity)
    owner.goto(f"http://127.0.0.1:3011/room/{room_id}", wait_until="domcontentloaded", timeout=60_000)
    guest.goto(f"http://127.0.0.1:3011/room/{room_id}", wait_until="domcontentloaded", timeout=60_000)
    try:
        guest.locator(".waiting-card").wait_for(timeout=15_000)
    except Exception:
        print(json.dumps({"guest_url": guest.url, "guest_body": guest.locator("body").inner_text(), "errors": errors}, ensure_ascii=False))
        raise
    guest.locator(".ready-toggle").click()
    guest.locator(".ready-list article").filter(has_text="OwnerCheck").locator(".reaction-avatar-trigger").click()
    guest.locator(".reaction-picker").wait_for()
    guest.wait_for_timeout(300)
    mobile_picker = os.path.join(tempfile.gettempdir(), "majority-reaction-mobile-picker.png")
    guest.screenshot(path=mobile_picker, full_page=True)
    guest.keyboard.press("Escape")
    owner.locator(".ready-list article").filter(has_text="GuestCheck").wait_for(timeout=15_000)

    owner.locator(".ready-list article").filter(has_text="GuestCheck").locator(".reaction-avatar-trigger").click()
    owner.locator(".reaction-picker").wait_for()
    assert owner.locator(".reaction-option").count() == 5
    owner.wait_for_timeout(300)
    waiting_picker = os.path.join(tempfile.gettempdir(), "majority-reaction-waiting-picker.png")
    owner.screenshot(path=waiting_picker, full_page=True)
    owner.get_by_role("button", name="拍手").click()
    owner.wait_for_timeout(520)
    assert owner.locator(".reaction-flight").count() > 0
    waiting_burst = os.path.join(tempfile.gettempdir(), "majority-reaction-waiting-burst.png")
    owner.screenshot(path=waiting_burst, full_page=True)

    owner.locator(".waiting-primary-action").wait_for(state="visible")
    owner.locator(".waiting-primary-action").click()
    owner.locator(".question-card").wait_for(timeout=15_000)
    guest.locator(".question-card").wait_for(timeout=15_000)
    owner.locator(".choice.a").click()
    owner.locator(".confirm-answer").click()
    guest.locator(".choice.b").click()
    guest.locator(".confirm-answer").click()

    admin_login = api.post("/api/admin/login", data={"password": "change-me"})
    assert admin_login.ok
    locked = api.post(f"/api/admin/rooms/{room_id}/lock", headers={"Authorization": f"Bearer {admin_login.json()['token']}"})
    assert locked.ok
    owner.locator(".result-card").wait_for(timeout=10_000)
    owner.locator(".result-choice-players article").filter(has_text="GuestCheck").locator(".reaction-avatar-trigger").click()
    owner.locator(".reaction-picker").wait_for()
    owner.wait_for_timeout(300)
    result_picker = os.path.join(tempfile.gettempdir(), "majority-reaction-result-picker.png")
    owner.screenshot(path=result_picker, full_page=True)
    owner.get_by_role("button", name="照れ笑い").click()
    owner.wait_for_timeout(520)
    result_burst = os.path.join(tempfile.gettempdir(), "majority-reaction-result-burst.png")
    owner.screenshot(path=result_burst, full_page=True)

    assert not errors, errors
    print(json.dumps({"room": room_id, "screenshots": [mobile_picker, waiting_picker, waiting_burst, result_picker, result_burst]}, ensure_ascii=False))
    api.dispose()
    owner_context.close()
    guest_context.close()
    browser.close()

import json
import os
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright


def seed_identity(context, identity):
    encoded = json.dumps(json.dumps(identity))
    context.add_init_script(script=f"window.localStorage.setItem('party-quiz-player', {encoded});")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=["--no-proxy-server"])
    owner_context = browser.new_context(viewport={"width": 1120, "height": 900})
    guest_context = browser.new_context(viewport={"width": 390, "height": 844})
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
    owner.goto(f"{frontend_base}/room/{room_id}", wait_until="domcontentloaded", timeout=30_000)
    guest.goto(f"{frontend_base}/room/{room_id}", wait_until="domcontentloaded", timeout=30_000)
    try:
        owner.locator(".waiting-card").wait_for(timeout=15_000)
        guest.locator(".waiting-card").wait_for(timeout=15_000)
    except Exception:
        print(json.dumps({"owner_url": owner.url, "owner_body": owner.locator("body").inner_text(), "guest_url": guest.url, "guest_body": guest.locator("body").inner_text(), "errors": errors}, ensure_ascii=False))
        raise
    guest.locator(".ready-toggle").click()
    owner.get_by_role("button", name="ゲームを開始！").click()

    owner.locator(".question-deck").wait_for(timeout=15_000)
    guest.locator(".wait-selecting").wait_for(timeout=15_000)
    assert owner.locator(".question-deck-card").count() == 3
    assert owner.locator(".parent-selection-card .timer").is_visible()
    assert guest.locator(".parent-selection-card .timer").is_visible()
    assert owner.locator(".question-deck-card.is-active").count() == 1
    owner.get_by_role("button", name="次の問題").click()
    owner.wait_for_timeout(700)
    assert owner.locator(".question-deck-card.is-active").count() == 1
    owner.locator(".question-deck-card.is-active").get_by_role("button", name="この問題を選ぶ").click()

    owner.locator(".parent-first-answer").wait_for(timeout=5_000)
    guest.locator(".wait-answering").wait_for(timeout=5_000)
    owner.get_by_role("button", name="押す", exact=True).click()
    owner.get_by_role("button", name="誰にも見せず「押す」で確定").click()

    guest.locator(".question-card").wait_for(timeout=5_000)
    owner.get_by_role("button", name="親の回答は確定済みです").wait_for(timeout=5_000)
    assert owner.get_by_role("button", name="押す", exact=True).is_disabled()
    guest.get_by_role("button", name="押さない", exact=True).click()
    guest.get_by_role("button", name="「押さない」で確定").click()
    guest.get_by_text("「押さない」で確定しました").wait_for(timeout=5_000)

    output = Path(tempfile.gettempdir()) / "majority-parent-flow.png"
    owner.screenshot(path=str(output), full_page=True)

    auto_created = api.post("/api/rooms", data={
        "username": "AutoParentCheck",
        "player_id": "auto-parent-check",
        "max_players": 6,
        "round_count": 1,
        "selection_duration": 5,
        "question_duration": 20,
        "between_question_duration": 10,
    }).json()
    auto_guest_identity = api.post("/api/players/identity", data={"username": "AutoGuestCheck", "player_id": "auto-guest-check"}).json()
    auto_owner_context = browser.new_context(viewport={"width": 1120, "height": 900})
    auto_guest_context = browser.new_context(viewport={"width": 390, "height": 844})
    seed_identity(auto_owner_context, {"player_id": auto_created["player_id"], "username": "AutoParentCheck", "session_id": auto_created["session_id"]})
    seed_identity(auto_guest_context, auto_guest_identity)
    auto_owner = auto_owner_context.new_page()
    auto_guest = auto_guest_context.new_page()
    for page in (auto_owner, auto_guest):
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    auto_room_id = auto_created["room"]["room_id"]
    auto_owner.goto(f"{frontend_base}/room/{auto_room_id}", wait_until="commit", timeout=15_000)
    auto_guest.goto(f"{frontend_base}/room/{auto_room_id}", wait_until="commit", timeout=15_000)
    auto_owner.locator(".waiting-card").wait_for(timeout=15_000)
    auto_guest.locator(".waiting-card").wait_for(timeout=15_000)
    auto_guest.locator(".ready-toggle").click()
    auto_owner.get_by_role("button", name="ゲームを開始！").click()
    auto_owner.locator(".question-deck-card").first.wait_for(timeout=15_000)
    assert auto_owner.locator(".question-deck-card").count() == 3
    auto_owner.locator(".parent-first-answer").wait_for(timeout=15_000)
    auto_guest.locator(".wait-answering").wait_for(timeout=5_000)

    assert not errors, errors
    print(json.dumps({"room_id": room_id, "auto_room_id": auto_room_id, "screenshot": str(output), "auto_selected": True}))
    api.dispose()
    browser.close()

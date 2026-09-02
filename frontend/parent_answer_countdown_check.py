import json
import re

from playwright.sync_api import sync_playwright


API = "http://localhost:8000"
WEB = "http://localhost:3000"


def post(request, path: str, body: dict) -> dict:
    response = request.post(f"{API}{path}", data=body)
    assert response.ok, f"{path}: {response.status} {response.text()}"
    return response.json()


with sync_playwright() as playwright:
    request = playwright.request.new_context(extra_http_headers={"Content-Type": "application/json"})
    owner_profile = post(request, "/api/players/identity", {"username": "親タイマー確認"})
    guest_profile = post(request, "/api/players/identity", {"username": "待機タイマー確認"})
    created = post(request, "/api/rooms", {
        "username": owner_profile["username"],
        "player_id": owner_profile["player_id"],
        "max_players": 4,
        "round_count": 1,
        "selection_duration": 5,
        "question_duration": 10,
        "between_question_duration": 5,
    })
    room_id = created["room"]["room_id"]
    owner_identity = {**owner_profile, "player_id": created["player_id"], "session_id": created["session_id"]}
    joined = post(request, f"/api/rooms/{room_id}/join", {
        "username": guest_profile["username"],
        "player_id": guest_profile["player_id"],
    })
    guest_identity = {**guest_profile, "player_id": joined["player_id"], "session_id": joined["session_id"]}

    browser = playwright.chromium.launch(headless=True)
    owner_context = browser.new_context(viewport={"width": 390, "height": 844})
    guest_context = browser.new_context(viewport={"width": 390, "height": 844})
    owner_context.add_init_script(f"localStorage.setItem('party-quiz-player', {json.dumps(json.dumps(owner_identity))})")
    guest_context.add_init_script(f"localStorage.setItem('party-quiz-player', {json.dumps(json.dumps(guest_identity))})")
    owner = owner_context.new_page()
    guest = guest_context.new_page()
    owner.goto(f"{WEB}/room/{room_id}")
    guest.goto(f"{WEB}/room/{room_id}")
    owner.wait_for_load_state("networkidle")
    guest.wait_for_load_state("networkidle")

    if guest.locator("button.ready-toggle").count() == 0:
        print("owner_url", owner.url)
        print("guest_url", guest.url)
        print("guest_body", guest.locator("body").inner_text()[:2000])
    guest.locator("button.ready-toggle").click()
    owner.locator("button.waiting-primary-action").click()
    owner.locator("[data-question-card] button").first.wait_for(timeout=12_000)
    owner.locator("[data-question-card] button").first.click()

    owner_timer = owner.locator(".parent-first-answer [role=timer]")
    guest_timer = guest.locator(".parent-answer-wait [role=timer]")
    owner_timer.wait_for(timeout=5_000)
    guest_timer.wait_for(timeout=5_000)
    owner_seconds = int(re.search(r"\d+", owner_timer.inner_text()).group())
    guest_seconds = int(re.search(r"\d+", guest_timer.inner_text()).group())
    assert 1 <= owner_seconds <= 10
    assert abs(owner_seconds - guest_seconds) <= 1
    assert owner.locator(".parent-first-answer .time-track").count() == 1
    assert guest.locator(".parent-answer-wait .time-track").count() == 1
    print(f"room={room_id} owner={owner_seconds}s guest={guest_seconds}s synchronized")

    browser.close()
    request.dispose()

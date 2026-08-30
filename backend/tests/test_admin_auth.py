from fastapi.testclient import TestClient

from app.main import app, create_admin_token, verify_admin_token


def test_admin_token_is_stateless_signed_and_rejects_tampering() -> None:
    token = create_admin_token()

    assert verify_admin_token(token)
    assert not verify_admin_token(token + "tampered")
    assert not verify_admin_token(create_admin_token(ttl_seconds=-1))


def test_login_token_authorizes_a_later_request() -> None:
    with TestClient(app) as client:
        login = client.post("/api/admin/login", json={"password": "change-me"})
        token = login.json()["token"]

        response = client.get("/api/admin/rooms", headers={"Authorization": f"Bearer {token}"})

    assert login.status_code == 200
    assert response.status_code == 200

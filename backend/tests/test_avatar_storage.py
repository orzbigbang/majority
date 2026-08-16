from app.avatar_storage import AvatarStorage


def test_party_token_svg_is_deterministic_and_has_game_token_features() -> None:
    first = AvatarStorage.svg("74c2d5fe-89ca-49b6-b5e6-cfd60a16bb90")
    second = AvatarStorage.svg("74c2d5fe-89ca-49b6-b5e6-cfd60a16bb90")

    assert first == second
    assert 'aria-labelledby="title"' in first
    assert '<circle cx="80" cy="80" r="43"' in first
    assert first.count('<circle') >= 4


def test_party_tokens_vary_by_user_id() -> None:
    assert AvatarStorage.svg("player-one") != AvatarStorage.svg("player-two")

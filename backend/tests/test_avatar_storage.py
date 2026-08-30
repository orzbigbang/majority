from app.avatar_storage import AvatarStorage
from app.cute_animal_svg import ANIMALS, animal_kind


def test_cute_animal_svg_is_deterministic_and_accessible() -> None:
    first = AvatarStorage.svg("74c2d5fe-89ca-49b6-b5e6-cfd60a16bb90")
    second = AvatarStorage.svg("74c2d5fe-89ca-49b6-b5e6-cfd60a16bb90")

    assert first == second
    assert 'aria-labelledby="title"' in first
    assert 'data-animal="' in first
    assert "プレイヤーアイコン" in first


def test_cute_animals_vary_by_user_id() -> None:
    assert AvatarStorage.svg("player-one") != AvatarStorage.svg("player-two")
    assert 'id="background-' in AvatarStorage.svg("player-one")


def test_all_cute_animal_templates_are_reachable() -> None:
    expected = {kind for kind, _ in ANIMALS}
    actual = {animal_kind(f"player-{index}")[0] for index in range(500)}
    assert actual == expected


def test_cute_animal_is_the_default_style_version(monkeypatch) -> None:
    monkeypatch.delenv("AVATAR_STYLE_VERSION", raising=False)
    storage = AvatarStorage.__new__(AvatarStorage)
    assert storage.style_version == "cute-animal-v1"

from amane.api.routes.theporndb_scenes import _scene_cover_image


def test_scene_cover_image_prefers_landscape_image_over_poster() -> None:
    assert (
        _scene_cover_image(
            {
                "poster": "https://example.com/portrait-poster.jpg",
                "image": "https://example.com/landscape-image.jpg",
            }
        )
        == "https://example.com/landscape-image.jpg"
    )


def test_scene_cover_image_uses_background_when_front_image_is_missing() -> None:
    assert (
        _scene_cover_image(
            {
                "poster": "https://example.com/portrait-poster.jpg",
                "background": {"large": "https://example.com/landscape-background.jpg"},
            }
        )
        == "https://example.com/landscape-background.jpg"
    )


def test_scene_cover_image_uses_poster_only_as_last_resort() -> None:
    assert _scene_cover_image({"poster": "https://example.com/poster.jpg"}) == "https://example.com/poster.jpg"


def test_scene_cover_image_returns_none_when_no_image_is_available() -> None:
    assert _scene_cover_image({"image": None, "background": None, "poster": None}) is None

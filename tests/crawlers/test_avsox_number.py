from amane.crawlers.sites.avsox import _pick_movie_id


def test_pick_movie_id_rejects_different_dash_layout() -> None:
    movies = [
        {"movieFanHao": "0712250-01", "movieId": "wrong"},
        {"movieFanHao": "071225-001", "movieId": "right"},
    ]
    assert _pick_movie_id(movies, "071225-001") == "right"


def test_pick_movie_id_keeps_undashed_compatibility() -> None:
    movies = [{"movieFanHao": "ABF355", "movieId": "same"}]
    assert _pick_movie_id(movies, "ABF-355") == "same"

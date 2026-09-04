"""Pure policy tests for the Agent provider catalog seam."""

from __future__ import annotations

from src.tools.agent_catalog import (
    CATALOG,
    extract_items,
    normalize_item,
    recommendation_keys,
    safe_value,
)


def test_catalog_resolves_current_and_rejects_unknown_provider() -> None:
    assert CATALOG.resolve_query_provider("current", lambda: "spotify") == ("spotify", None)
    assert CATALOG.resolve_query_provider("unknown", lambda: "spotify") == (None, "PROVIDER_UNSUPPORTED")
    assert CATALOG.resolve_query_provider("current", lambda: None) == (None, "CONNECTION_REQUIRED")
    assert CATALOG.is_connected("local", lambda _provider: False)
    assert not CATALOG.is_connected("spotify", lambda _provider: False)


def test_catalog_maps_spotify_resources_and_decodes_refs() -> None:
    tool, args = CATALOG.query_tool_and_args(
        "spotify",
        "playlist_tracks",
        query=None,
        ref="spotify:id:playlist-1",
        limit=5,
        cursor="10",
    )
    assert tool == "spotify_playlist_tracks"
    assert args == {"playlist_id": "playlist-1", "limit": 5, "offset": 10}


def test_catalog_normalizes_safe_items_and_deduplication_keys() -> None:
    refs: list[tuple[str, dict[str, object]]] = []

    def remember(provider: str, item: dict[str, object]) -> str:
        refs.append((provider, dict(item)))
        return f"{provider}:metadata:1"

    item = normalize_item(
        "spotify",
        {"name": "Song", "token": "secret", "url": "https://temporary"},
        remember,
    )
    assert item == {"name": "Song", "provider": "spotify", "ref": "spotify:metadata:1"}
    assert refs and refs[0][1] == {"name": "Song", "provider": "spotify"}
    assert recommendation_keys({"name": "Song", "artist": "Artist"}) == {
        "text:song|artist",
    }


def test_catalog_extracts_bounded_items() -> None:
    assert extract_items({"tracks": [{"id": 1}, {"id": 2}]}, 1) == [{"id": 1}]
    assert safe_value({"token": "hidden", "nested": {"url": "temporary", "ok": 1}}) == {
        "nested": {"ok": 1},
    }


def test_catalog_paginates_from_existing_cursor() -> None:
    assert CATALOG.page("4", 3, 3) == {"cursor": "7", "has_more": True}
    assert CATALOG.page(None, 0, 3) == {"cursor": None, "has_more": False}


def test_catalog_merges_recommendations_in_provider_order() -> None:
    tracks = CATALOG.merge_recommendations(
        {
            "spotify": [
                {"uri": "spotify:track:1", "name": "One"},
                {"uri": "spotify:track:1", "name": "Duplicate"},
            ],
            "jamendo": [{"uri": "jamendo:track:2", "name": "Two"}],
        },
        ("jamendo", "spotify"),
        2,
        lambda provider, item: {"provider": provider, "name": item["name"]},
    )
    assert tracks == [
        {"provider": "jamendo", "name": "Two"},
        {"provider": "spotify", "name": "One"},
    ]

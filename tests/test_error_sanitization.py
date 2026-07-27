from src.llm.transport import sanitize_error_message
from src.api.ws_runner import _format_args, _friendly_runtime_error_message


def test_error_sanitization_redacts_secrets_and_url_private_suffixes() -> None:
    message = sanitize_error_message(
        "request failed at https://example.test/callback?code=secret&state=private#session=value "
        "api_key=super-secret"
    )

    assert "code=secret" not in message
    assert "session=value" not in message
    assert "super-secret" not in message
    assert "https://example.test/callback?[redacted]" in message
    assert "api_key=[redacted]" in message


def test_activity_arguments_redact_credentials() -> None:
    detail = _format_args({
        "query": "Blue in Green",
        "api_key": "secret-key",
        "access_token": "secret-token",
    })

    assert "query=Blue in Green" in detail
    assert "api_key=[redacted]" in detail
    assert "access_token=[redacted]" in detail
    assert "secret-key" not in detail
    assert "secret-token" not in detail


def test_runtime_error_leads_with_sonex_summary() -> None:
    message = _friendly_runtime_error_message(
        {
            "status": "fail",
            "message": "upstream failed at https://example.test/request?token=secret",
            "error_code": "UPSTREAM_ERROR",
        },
        fallback="Spotify search failed. Try again.",
    )

    assert message.startswith("Spotify search failed. Try again.")
    assert "Technical detail: upstream failed" in message
    assert "token=secret" not in message

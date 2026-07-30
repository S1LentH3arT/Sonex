"""Deployable stateless Apple developer-token broker application."""

from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException
import uvicorn

from src.apple_mode.token_provider import APPLE_DEVELOPER_TOKEN_TTL_SECONDS
from src.auth.apple_music import AppleMusicAuthError, apple_music_credentials, generate_developer_token


def create_broker_app() -> FastAPI:
    app = FastAPI(title="Sonex Apple Developer Token Broker")

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/apple-music/developer-token")
    async def developer_token() -> dict[str, str | int]:
        issued_at = int(time.time())
        try:
            token = generate_developer_token(apple_music_credentials(), issued_at)
        except AppleMusicAuthError as exc:
            raise HTTPException(status_code=503, detail="Apple token signer is not configured.") from exc
        return {
            "token": token,
            "expires_at": issued_at + APPLE_DEVELOPER_TOKEN_TTL_SECONDS,
        }

    return app


app = create_broker_app()


def main() -> None:
    uvicorn.run("src.apple_mode.broker:app", host="127.0.0.1", port=8766)

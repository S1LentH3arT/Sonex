from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AuthMethod = Literal["auto", "oauth", "api_key", "none"]


@dataclass(slots=True)
class OAuthToken:
    access_token: str
    refresh_token: str | None = None
    expires_at: str | None = None
    scopes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OAuthToken | None":
        if not data:
            return None
        access_token = str(data.get("access_token") or "")
        if not access_token:
            return None
        scopes = data.get("scopes") or []
        return cls(
            access_token=access_token,
            refresh_token=data.get("refresh_token"),
            expires_at=data.get("expires_at"),
            scopes=[str(scope) for scope in scopes],
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"access_token": self.access_token}
        if self.refresh_token:
            data["refresh_token"] = self.refresh_token
        if self.expires_at:
            data["expires_at"] = self.expires_at
        if self.scopes:
            data["scopes"] = self.scopes
        return data


@dataclass(slots=True)
class ApiKeyCredential:
    api_key: str

    @classmethod
    def from_value(cls, value: str | None) -> "ApiKeyCredential | None":
        if not value:
            return None
        return cls(api_key=value)


@dataclass(slots=True)
class ProviderAuth:
    name: str
    auth_method: AuthMethod = "auto"
    api_key: str | None = None
    oauth: OAuthToken | None = None
    model: str | None = None
    base_url: str | None = None
    custom_llm_provider: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any] | None) -> "ProviderAuth":
        data = data or {}
        method = str(data.get("auth_method") or "auto")
        if method not in {"auto", "oauth", "api_key", "none"}:
            method = "auto"
        return cls(
            name=name,
            auth_method=method,  # type: ignore[arg-type]
            api_key=data.get("api_key"),
            oauth=OAuthToken.from_dict(data.get("oauth")),
            model=data.get("model"),
            base_url=data.get("base_url"),
            custom_llm_provider=data.get("custom_llm_provider"),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"auth_method": self.auth_method}
        if self.api_key:
            data["api_key"] = self.api_key
        if self.oauth:
            data["oauth"] = self.oauth.to_dict()
        if self.model:
            data["model"] = self.model
        if self.base_url:
            data["base_url"] = self.base_url
        if self.custom_llm_provider:
            data["custom_llm_provider"] = self.custom_llm_provider
        if self.updated_at:
            data["updated_at"] = self.updated_at
        return data


@dataclass(slots=True)
class AuthStore:
    version: int = 1
    default_provider: str | None = None
    default_model: str | None = None
    providers: dict[str, ProviderAuth] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AuthStore":
        data = data or {}
        providers = {
            str(name): ProviderAuth.from_dict(str(name), provider_data)
            for name, provider_data in (data.get("providers") or {}).items()
        }
        return cls(
            version=int(data.get("version") or 1),
            default_provider=data.get("default_provider"),
            default_model=data.get("default_model"),
            providers=providers,
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "version": self.version,
            "providers": {
                name: provider.to_dict()
                for name, provider in sorted(self.providers.items())
            },
        }
        if self.default_provider:
            data["default_provider"] = self.default_provider
        if self.default_model:
            data["default_model"] = self.default_model
        return data

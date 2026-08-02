"""Models support for provider authentication and credential persistence.

Implements the models module responsibilities used by Sonex runtime flows.
Key public entry points include OAuthToken, ApiKeyCredential, ProviderAuth, AuthStore.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


AuthMethod = Literal["auto", "oauth", "api_key", "none"]


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class OAuthToken:
    """Represents oauth token.

    Encapsulates oauth token data and behavior used by Sonex runtime flows.
    """
    access_token: str
    refresh_token: str | None = None
    refresh_token_ref: str | None = None
    expires_at: str | None = None
    scopes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OAuthToken | None":
        """Coordinates from dict for the current Sonex flow.

        Typical use: Use this function when runtime code needs from dict as part of a Sonex command, playback, auth, llm, or ui path.

        Example: from_dict(data=...) -> returns the value used by the surrounding Sonex flow.
        """
        if not data:
            return None
        access_token = str(data.get("access_token") or "")
        refresh_token_ref = str(data.get("refresh_token_ref") or "") or None
        if not access_token and not refresh_token_ref:
            return None
        scopes = data.get("scopes") or []
        return cls(
            access_token=access_token,
            refresh_token=data.get("refresh_token"),
            refresh_token_ref=refresh_token_ref,
            expires_at=data.get("expires_at"),
            scopes=[str(scope) for scope in scopes],
        )

    def to_dict(self) -> dict[str, Any]:
        """Coordinates to dict for the current Sonex flow.

        Typical use: Use this function when runtime code needs to dict as part of a Sonex command, playback, auth, llm, or ui path.

        Example: to_dict() -> returns the value used by the surrounding Sonex flow.
        """
        data: dict[str, Any] = {}
        if self.access_token and not self.refresh_token_ref:
            data["access_token"] = self.access_token
        if self.refresh_token and not self.refresh_token_ref:
            data["refresh_token"] = self.refresh_token
        if self.refresh_token_ref:
            data["refresh_token_ref"] = self.refresh_token_ref
        if self.expires_at:
            data["expires_at"] = self.expires_at
        if self.scopes:
            data["scopes"] = self.scopes
        return data


@dataclass(slots=True)
class ApiKeyCredential:
    """Represents api key credential.

    Encapsulates api key credential data and behavior used by Sonex runtime flows.
    """
    api_key: str

    @classmethod
    def from_value(cls, value: str | None) -> "ApiKeyCredential | None":
        """Coordinates from value for the current Sonex flow.

        Typical use: Use this function when runtime code needs from value as part of a Sonex command, playback, auth, llm, or ui path.

        Example: from_value(value=...) -> returns the value used by the surrounding Sonex flow.
        """
        if not value:
            return None
        return cls(api_key=value)


@dataclass(slots=True)
class ProviderAuth:
    """Represents provider auth.

    Encapsulates provider auth data and behavior used by Sonex runtime flows.
    """
    name: str
    auth_method: AuthMethod = "auto"
    api_key: str | None = None
    oauth: OAuthToken | None = None
    managed_auth: str | None = None
    model: str | None = None
    base_url: str | None = None
    custom_llm_provider: str | None = None
    project_id: str | None = None
    display_name: str | None = None
    model_ids: list[str] = field(default_factory=list)
    needs_review: bool = False
    allow_insecure_http: bool = False
    experimental_confirmed: bool = False
    timeout: float | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any] | None) -> "ProviderAuth":
        """Coordinates from dict for the current Sonex flow.

        Typical use: Use this function when runtime code needs from dict as part of a Sonex command, playback, auth, llm, or ui path.

        Example: from_dict(name=..., data=...) -> returns the value used by the surrounding Sonex flow.
        """
        data = data or {}
        method = str(data.get("auth_method") or "auto")
        if method not in {"auto", "oauth", "api_key", "none"}:
            method = "auto"
        return cls(
            name=name,
            auth_method=method,  # type: ignore[arg-type]
            api_key=data.get("api_key"),
            oauth=OAuthToken.from_dict(data.get("oauth")),
            managed_auth=data.get("managed_auth"),
            model=data.get("model"),
            base_url=data.get("base_url"),
            custom_llm_provider=data.get("custom_llm_provider"),
            project_id=data.get("project_id"),
            display_name=data.get("display_name"),
            model_ids=[
                str(item).strip()
                for item in (data.get("model_ids") or [])
                if str(item).strip()
            ],
            needs_review=bool(data.get("needs_review", False)),
            allow_insecure_http=bool(data.get("allow_insecure_http", False)),
            experimental_confirmed=bool(data.get("experimental_confirmed", False)),
            timeout=_optional_float(data.get("timeout")),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Coordinates to dict for the current Sonex flow.

        Typical use: Use this function when runtime code needs to dict as part of a Sonex command, playback, auth, llm, or ui path.

        Example: to_dict() -> returns the value used by the surrounding Sonex flow.
        """
        data: dict[str, Any] = {"auth_method": self.auth_method}
        if self.api_key:
            data["api_key"] = self.api_key
        if self.oauth:
            data["oauth"] = self.oauth.to_dict()
        if self.managed_auth:
            data["managed_auth"] = self.managed_auth
        if self.model:
            data["model"] = self.model
        if self.base_url:
            data["base_url"] = self.base_url
        if self.custom_llm_provider:
            data["custom_llm_provider"] = self.custom_llm_provider
        if self.project_id:
            data["project_id"] = self.project_id
        if self.display_name:
            data["display_name"] = self.display_name
        if self.model_ids:
            data["model_ids"] = self.model_ids
        if self.needs_review:
            data["needs_review"] = True
        if self.allow_insecure_http:
            data["allow_insecure_http"] = True
        if self.experimental_confirmed:
            data["experimental_confirmed"] = True
        if self.timeout is not None:
            data["timeout"] = self.timeout
        if self.updated_at:
            data["updated_at"] = self.updated_at
        return data


@dataclass(slots=True)
class AuthStore:
    """Represents auth store.

    Encapsulates auth store data and behavior used by Sonex runtime flows.
    """
    version: int = 1
    default_provider: str | None = None
    default_model: str | None = None
    providers: dict[str, ProviderAuth] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AuthStore":
        """Coordinates from dict for the current Sonex flow.

        Typical use: Use this function when runtime code needs from dict as part of a Sonex command, playback, auth, llm, or ui path.

        Example: from_dict(data=...) -> returns the value used by the surrounding Sonex flow.
        """
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
        """Coordinates to dict for the current Sonex flow.

        Typical use: Use this function when runtime code needs to dict as part of a Sonex command, playback, auth, llm, or ui path.

        Example: to_dict() -> returns the value used by the surrounding Sonex flow.
        """
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

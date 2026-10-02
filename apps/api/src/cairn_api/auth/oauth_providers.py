"""Fixed-endpoint OAuth adapters. Remote tokens never leave the exchange call."""

import base64
import hashlib
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.parse import urlencode

import httpx

from cairn_api.auth.oauth_schemas import ProviderName
from cairn_api.settings import Settings


@dataclass(frozen=True)
class ProviderIdentity:
    subject: str
    display_name: str | None


class ProviderFailure(Exception):
    """Intentionally excludes upstream bodies, codes and credentials."""


class OAuthProvider(Protocol):
    @property
    def client_id(self) -> str: ...

    def authorization_url(self, *, state: str, verifier: str, redirect_uri: str) -> str: ...

    def exchange(self, *, code: str, verifier: str, redirect_uri: str) -> ProviderIdentity: ...


class HttpOAuthProvider:
    def __init__(
        self,
        provider: ProviderName,
        client_id: str,
        client_secret: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.provider = provider
        self.client_id = client_id
        self._secret = client_secret
        self._transport = transport

    def authorization_url(self, *, state: str, verifier: str, redirect_uri: str) -> str:
        params = {"client_id": self.client_id, "redirect_uri": redirect_uri, "state": state}
        if self.provider == "github":
            params["code_challenge"] = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
                .rstrip(b"=")
                .decode("ascii")
            )
            params["code_challenge_method"] = "S256"
            endpoint = "https://github.com/login/oauth/authorize"
        else:
            # Feishu's documented confidential-client flow does not specify PKCE.
            params["response_type"] = "code"
            endpoint = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
        # No repository, document, email or offline scope is requested for sign-in.
        return endpoint + "?" + urlencode(params)

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, object]:
        response.raise_for_status()
        if len(response.content) > 1_000_000:
            raise ProviderFailure()
        data: object = response.json()
        if not isinstance(data, dict):
            raise ProviderFailure()
        return cast(dict[str, object], data)

    def exchange(self, *, code: str, verifier: str, redirect_uri: str) -> ProviderIdentity:
        try:
            with httpx.Client(
                transport=self._transport, timeout=10, follow_redirects=False, trust_env=False
            ) as client:
                params = {
                    "client_id": self.client_id,
                    "client_secret": self._secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                }
                if self.provider == "github":
                    params["code_verifier"] = verifier
                    token_data = self._json(
                        client.post(
                            "https://github.com/login/oauth/access_token",
                            data=params,
                            headers={"Accept": "application/json"},
                        )
                    )
                else:
                    token_data = self._json(
                        client.post(
                            "https://open.feishu.cn/open-apis/authen/v2/oauth/token", json=params
                        )
                    )
                    if token_data.get("code") != 0:
                        raise ProviderFailure()
                token = token_data.get("access_token")
                if (
                    not isinstance(token, str)
                    or not token
                    or not token.isascii()
                    or len(token) > 4096
                ):
                    raise ProviderFailure()
                endpoint = (
                    "https://api.github.com/user"
                    if self.provider == "github"
                    else "https://open.feishu.cn/open-apis/authen/v1/user_info"
                )
                data = self._json(
                    client.get(
                        endpoint,
                        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    )
                )
                if self.provider == "github":
                    subject = data.get("id")
                    if type(subject) is not int or subject <= 0:
                        raise ProviderFailure()
                    stable_id = str(subject)
                    name = data.get("name") or data.get("login")
                else:
                    if data.get("code") != 0 or not isinstance(data.get("data"), dict):
                        raise ProviderFailure()
                    user = cast(dict[str, object], data["data"])
                    subject = user.get("open_id")
                    if not isinstance(subject, str) or not subject or len(subject) > 256:
                        raise ProviderFailure()
                    stable_id = subject
                    name = user.get("name")
                return ProviderIdentity(stable_id, name[:120] if isinstance(name, str) else None)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ProviderFailure() from None


def configured_providers(settings: Settings) -> dict[ProviderName, OAuthProvider]:
    providers: dict[ProviderName, OAuthProvider] = {}
    for name, client_id, secret in (
        ("github", settings.oauth_github_client_id, settings.oauth_github_client_secret),
        ("feishu", settings.oauth_feishu_client_id, settings.oauth_feishu_client_secret),
    ):
        if client_id is not None and secret is not None:
            providers[cast(ProviderName, name)] = HttpOAuthProvider(
                cast(ProviderName, name), client_id, secret.get_secret_value()
            )
    return providers

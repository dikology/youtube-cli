from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

import keyring
from keyring.errors import PasswordDeleteError

KEYCHAIN_SERVICE = "youtube-cli"
KEYCHAIN_ACCOUNT = "oauth-tokens"


@dataclass(frozen=True)
class Tokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None


class CredentialStore(Protocol):
    def load(self) -> Tokens | None: ...

    def save(self, tokens: Tokens) -> None: ...

    def delete(self) -> None: ...


class InMemoryCredentialStore:
    def __init__(self, tokens: Tokens | None = None) -> None:
        self._tokens = tokens

    def load(self) -> Tokens | None:
        return self._tokens

    def save(self, tokens: Tokens) -> None:
        self._tokens = tokens

    def delete(self) -> None:
        self._tokens = None


class KeychainCredentialStore:
    def load(self) -> Tokens | None:
        raw = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
        if raw is None:
            return None
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return None
        data = cast(dict[str, object], parsed)
        access_token = data.get("access_token")
        if not isinstance(access_token, str):
            return None
        refresh_token = data.get("refresh_token")
        expires_at = data.get("expires_at")
        return Tokens(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            expires_at=datetime.fromisoformat(expires_at) if isinstance(expires_at, str) else None,
        )

    def save(self, tokens: Tokens) -> None:
        payload = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": tokens.expires_at.isoformat() if tokens.expires_at else None,
        }
        keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, json.dumps(payload))

    def delete(self) -> None:
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
        except PasswordDeleteError:
            return

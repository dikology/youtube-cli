from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, Thread
from typing import cast
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from youtube_cli.credentials import Tokens

YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
LOGIN_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class ClientCredentials:
    client_id: str
    client_secret: str


class ClientSecretError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LoginError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def load_client_credentials(*, config_dir: Path) -> ClientCredentials:
    env_file = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE")
    if env_file:
        return _from_secret_file(Path(env_file))
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if client_id and client_secret:
        return ClientCredentials(client_id=client_id, client_secret=client_secret)
    return _from_secret_file(config_dir / "client_secret.json")


def login_via_loopback(
    client: ClientCredentials,
    *,
    open_browser: Callable[[str], object],
    exchange_code: Callable[[str, str, ClientCredentials], Tokens],
) -> Tokens:
    server = _LoopbackServer(("127.0.0.1", 0), _LoopbackHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        redirect_uri = f"http://127.0.0.1:{server.server_port}"
        open_browser(_authorization_url(client, redirect_uri))
        if not server.finished.wait(timeout=LOGIN_TIMEOUT_SECONDS):
            raise LoginError("login timed out waiting for the browser")
        if not server.authorization_code:
            raise LoginError("login did not receive an authorization code")
        return exchange_code(server.authorization_code, redirect_uri, client)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def refresh_google_tokens(tokens: Tokens, client: ClientCredentials) -> Tokens:
    if not tokens.refresh_token:
        raise LoginError("no refresh token")
    try:
        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "refresh_token": tokens.refresh_token,
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "grant_type": "refresh_token",
            },
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LoginError("failed to refresh access token") from exc
    refreshed = _tokens_from_payload(_object_map(response.json()))
    return Tokens(
        access_token=refreshed.access_token,
        refresh_token=refreshed.refresh_token or tokens.refresh_token,
        expires_at=refreshed.expires_at,
    )


def exchange_google_code(
    code: str, redirect_uri: str, client: ClientCredentials
) -> Tokens:
    try:
        response = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client.client_id,
                "client_secret": client.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LoginError("failed to exchange authorization code") from exc
    try:
        return _tokens_from_payload(_object_map(response.json()))
    except LoginError as exc:
        raise LoginError("failed to exchange authorization code") from exc


def _tokens_from_payload(payload: dict[str, object]) -> Tokens:
    access_token = payload.get("access_token")
    if not isinstance(access_token, str):
        raise LoginError("token response missing access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=expires_in)
        if isinstance(expires_in, int) and not isinstance(expires_in, bool)
        else None
    )
    return Tokens(
        access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        expires_at=expires_at,
    )


def _authorization_url(client: ClientCredentials, redirect_uri: str) -> str:
    return (
        f"{GOOGLE_AUTH_URL}?"
        + urlencode(
            {
                "client_id": client.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": YOUTUBE_READONLY_SCOPE,
                "access_type": "offline",
                "prompt": "consent",
            }
        )
    )


def _from_secret_file(path: Path) -> ClientCredentials:
    if not path.is_file():
        raise ClientSecretError(
            f"missing client secret file: {path}; "
            "set YOUTUBE_CLIENT_SECRET_FILE or GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET"
        )
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClientSecretError(f"invalid client secret file: {path}") from exc
    data = _object_map(parsed)
    installed = _object_map(data.get("installed"))
    web = _object_map(data.get("web"))
    section = installed or web or data
    client_id = section.get("client_id")
    client_secret = section.get("client_secret")
    if not isinstance(client_id, str) or not isinstance(client_secret, str):
        raise ClientSecretError(f"invalid client secret file: {path}")
    return ClientCredentials(client_id=client_id, client_secret=client_secret)


class _LoopbackServer(HTTPServer):
    authorization_code: str | None
    finished: Event

    def __init__(self, server_address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> None:
        self.authorization_code = None
        self.finished = Event()
        super().__init__(server_address, handler)


class _LoopbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        server = cast(_LoopbackServer, self.server)
        query = parse_qs(urlparse(self.path).query)
        codes = query.get("code")
        errors = query.get("error")
        if not codes and not errors:
            self.send_response(404)
            self.end_headers()
            return
        server.authorization_code = codes[0] if codes else None
        body = b"Signed in. You can close this window."
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        server.finished.set()

    def log_message(self, format: str, *args: object) -> None:
        return


def _object_map(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    typed = cast(dict[object, object], value)
    return {str(key): item for key, item in typed.items()}

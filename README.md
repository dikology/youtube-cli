# youtube-cli

Personal local-first YouTube CLI. The console script is `youtube`.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this-repo>
cd youtube-cli
uv sync
```

`uv sync` installs the `youtube` script into `.venv`. Use `uv run youtube …`, or put `.venv/bin` on your `PATH`.

### 1. Google Cloud project

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create a project (or pick an existing one).
2. Enable **YouTube Data API v3** for that project: [API library](https://console.cloud.google.com/apis/library/youtube.googleapis.com).

### 2. OAuth consent screen

1. Go to [APIs & Services → OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent).
2. User type: **External**.
3. Leave the app in **Testing**. Do not publish it.
4. Add your Google account under **Test users**. Only listed accounts can sign in.
5. Scopes: you do not need to pre-register them; `youtube auth login` requests `youtube.readonly` at runtime.

A Testing client expires the refresh token about weekly. That is expected — see [Weekly Testing-app re-login](#weekly-testing-app-re-login).

### 3. Desktop OAuth client

1. Go to [APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials).
2. **Create credentials → OAuth client ID**.
3. Application type: **Desktop app**.
4. Download the JSON. Google names it something like `client_secret_….apps.googleusercontent.com.json`.

Do not commit this file. It is a client secret for an installed app, not a token, but it still stays off git.

### 4. Put the client secret on disk

Default path:

```bash
mkdir -p ~/.config/youtube-cli
mv ~/Downloads/client_secret_*.json ~/.config/youtube-cli/client_secret.json
```

Or point at the downloaded file / paste the values:

| Source | How |
| --- | --- |
| `~/.config/youtube-cli/client_secret.json` | Default. GCP “Desktop app” JSON (`installed.client_id` / `installed.client_secret`). |
| `YOUTUBE_CLIENT_SECRET_FILE` | Absolute path to that same JSON. |
| `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` | The two string values from the JSON, no file. |

The CLI checks them in that order: env file, then env vars, then the default path.

### 5. Log in

```bash
uv run youtube auth login
```

This opens the system browser, listens on `http://127.0.0.1:<port>`, and completes Google's desktop loopback. Sign in with the test user you added. No other command opens a browser.

Tokens are stored in the macOS Keychain under service `youtube-cli`. Confirm with:

```bash
uv run youtube auth status
```

`auth status` prints channel title, `token_ok`, and `expires_at`. It never prints the token.

## Auth

```
youtube auth login
youtube auth status
youtube auth logout
youtube auth logout --wipe
```

`auth logout` deletes Keychain tokens only. `auth logout --wipe` also deletes the SQLite cache. Neither removes `client_secret.json`.

### Weekly Testing-app re-login

Access tokens expire in about an hour and are refreshed automatically from the Keychain refresh token. This project stays on a GCP OAuth client in **Testing**, so Google expires that refresh token about weekly. `auth status` reporting `token_ok: false` after a week is expected — run `youtube auth login` again. That is not a product bug.

## Cache

Library cache: `~/.cache/youtube-cli/library.sqlite` (override with `YOUTUBE_CACHE_DIR`).

```
youtube cache status
youtube cache clear
```

`cache clear` deletes the SQLite file only. `auth logout --wipe` deletes tokens and the cache. Neither removes `client_secret.json`.

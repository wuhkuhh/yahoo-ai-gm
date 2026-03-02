from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import requests

YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "bearer"
    saved_at: int = 0  # unix seconds when saved

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "OAuthTokens":
        return OAuthTokens(
            access_token=d["access_token"],
            refresh_token=d["refresh_token"],
            expires_in=int(d["expires_in"]),
            token_type=d.get("token_type", "bearer"),
            saved_at=int(d.get("_saved_at", d.get("saved_at", 0)) or 0),
        )

    def to_json(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_in": int(self.expires_in),
            "token_type": self.token_type,
            "_saved_at": int(self.saved_at),
        }

    def is_expired(self, skew_seconds: int = 60) -> bool:
        if not self.saved_at:
            return True
        return int(time.time()) >= (self.saved_at + self.expires_in - skew_seconds)


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    b64 = base64.b64encode(raw).decode("utf-8")
    return f"Basic {b64}"


def load_tokens(token_path: Path) -> OAuthTokens:
    if not token_path.exists():
        raise FileNotFoundError(f"Token file not found: {token_path}")
    with token_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return OAuthTokens.from_json(data)


def save_tokens(token_path: Path, tokens: OAuthTokens) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = token_path.with_suffix(token_path.suffix + ".tmp")

    with tmp.open("w", encoding="utf-8") as f:
        json.dump(tokens.to_json(), f, indent=2, sort_keys=True)

    tmp.replace(token_path)
    try:
        token_path.chmod(0o600)
    except PermissionError:
        pass


def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    timeout: int = 30,
) -> Dict[str, Any]:
    headers = {
        "Authorization": _basic_auth_header(client_id, client_secret),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    resp = requests.post(YAHOO_TOKEN_URL, headers=headers, data=data, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def get_valid_access_token(
    *,
    client_id: str,
    client_secret: str,
    token_path: Path,
) -> str:
    tokens = load_tokens(token_path)

    if not tokens.is_expired():
        return tokens.access_token

    payload = refresh_access_token(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=tokens.refresh_token,
    )

    new_tokens = OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token", tokens.refresh_token),
        expires_in=int(payload["expires_in"]),
        token_type=payload.get("token_type", "bearer"),
        saved_at=int(time.time()),
    )
    save_tokens(token_path, new_tokens)
    return new_tokens.access_token

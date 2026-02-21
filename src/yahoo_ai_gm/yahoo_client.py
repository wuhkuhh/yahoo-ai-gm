from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests

from yahoo_ai_gm.settings import Settings
from yahoo_ai_gm.auth import get_valid_access_token


YAHOO_FANTASY_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2/"


@dataclass
class YahooClient:
    settings: Settings
    session: requests.Session

    @classmethod
    def from_local_config(cls) -> "YahooClient":
        settings = Settings.from_local_config()
        session = requests.Session()
        session.headers.update({"Accept": "application/xml"})
        return cls(settings=settings, session=session)

    def _auth_headers(self) -> dict:
        token = get_valid_access_token(
            client_id=self.settings.client_id,
            client_secret=self.settings.client_secret,
            token_path=self.settings.token_path,
        )
        return {"Authorization": f"Bearer {token}"}

    def get(self, path: str, *, params: Optional[dict] = None, timeout: int = 30) -> str:
        url = YAHOO_FANTASY_API_BASE + path.lstrip("/")
        resp = self.session.get(
            url,
            headers=self._auth_headers(),
            params=params,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.text

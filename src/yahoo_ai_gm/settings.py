from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    redirect_uri: str

    token_path: Path
    env_path: Path

    league_id: str

    team_id: str

    @staticmethod
    def from_local_config() -> "Settings":
        """
        Loads config/local/.env by default (gitignored).
        You can override with environment variables.
        """
        repo_root = Path(__file__).resolve().parents[2]  # .../src/yahoo_ai_gm -> repo root
        default_env_path = repo_root / "config" / "local" / ".env"
        default_token_path = repo_root / "config" / "local" / "oauth.json"

        # Load .env (if present). Environment variables already set will not be overwritten.
        if default_env_path.exists():
            load_dotenv(default_env_path, override=False)

        env_path = Path(os.getenv("YAHOO_ENV_PATH", str(default_env_path))).expanduser().resolve()
        token_path = Path(os.getenv("YAHOO_TOKEN_PATH", str(default_token_path))).expanduser().resolve()

        # Load again from YAHOO_ENV_PATH if different
        if env_path.exists():
            load_dotenv(env_path, override=False)

        client_id = os.getenv("YAHOO_CLIENT_ID", "").strip()
        client_secret = os.getenv("YAHOO_CLIENT_SECRET", "").strip()
        redirect_uri = os.getenv("YAHOO_REDIRECT_URI", "").strip()

        league_id = os.getenv("YAHOO_LEAGUE_ID", "40206").strip()

        team_id = os.getenv("YAHOO_TEAM_ID", "6").strip()

        missing = [k for k, v in {
            "YAHOO_CLIENT_ID": client_id,
            "YAHOO_CLIENT_SECRET": client_secret,
            "YAHOO_REDIRECT_URI": redirect_uri,
        }.items() if not v]

        if missing:
            raise RuntimeError(
                "Missing required settings: "
                + ", ".join(missing)
                + ". Check config/local/.env (gitignored)."
            )

        return Settings(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            token_path=token_path,
            env_path=env_path,
            league_id=league_id,
            team_id=team_id,
        )

    @property
    def league_key(self) -> str:
        # Yahoo MLB game key is typically 469
        return f"469.l.{self.league_id}"

    @property
    def team_key(self) -> str:
        return f"{self.league_key}.t.{self.team_id}"

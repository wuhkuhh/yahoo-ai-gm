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
    game_key: str
    league_key: str
    team_key: str

    @staticmethod
    def from_local_config() -> "Settings":
        repo_root = Path(__file__).resolve().parents[2]

        default_env_path = repo_root / "config" / "local" / ".env"
        default_token_path = repo_root / "config" / "local" / "oauth.json"

        # Load default .env if present
        if default_env_path.exists():
            load_dotenv(default_env_path, override=False)

        env_path = Path(os.getenv("YAHOO_ENV_PATH", str(default_env_path))).expanduser().resolve()
        token_path = Path(os.getenv("YAHOO_TOKEN_PATH", str(default_token_path))).expanduser().resolve()

        if env_path.exists():
            load_dotenv(env_path, override=False)

        client_id = os.getenv("YAHOO_CLIENT_ID", "").strip()
        client_secret = os.getenv("YAHOO_CLIENT_SECRET", "").strip()
        redirect_uri = os.getenv("YAHOO_REDIRECT_URI", "").strip()

        league_id = os.getenv("YAHOO_LEAGUE_ID", "").strip()
        game_key = os.getenv("YAHOO_GAME_KEY", "").strip()
        league_key = os.getenv("YAHOO_LEAGUE_KEY", "").strip()
        team_key = os.getenv("YAHOO_TEAM_KEY", "").strip()

        missing = [
            k for k, v in {
                "YAHOO_CLIENT_ID": client_id,
                "YAHOO_CLIENT_SECRET": client_secret,
                "YAHOO_REDIRECT_URI": redirect_uri,
                "YAHOO_LEAGUE_ID": league_id,
                "YAHOO_GAME_KEY": game_key,
                "YAHOO_LEAGUE_KEY": league_key,
                "YAHOO_TEAM_KEY": team_key,
            }.items()
            if not v
        ]

        if missing:
            raise RuntimeError(
                "Missing required settings: " + ", ".join(missing)
            )

        return Settings(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            token_path=token_path,
            env_path=env_path,
            league_id=league_id,
            game_key=game_key,
            league_key=league_key,
            team_key=team_key,
        )

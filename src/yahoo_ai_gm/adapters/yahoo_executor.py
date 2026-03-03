"""
src/yahoo_ai_gm/adapters/yahoo_executor.py

Layer 5 — External I/O adapter for Yahoo Fantasy write operations.

Handles transaction construction and submission.
GATED by YAHOO_AUTO_EXECUTE env var — will never execute unless explicitly enabled.

Yahoo Fantasy transaction XML format for add/drop:
  POST /fantasy/v2/league/{league_key}/transactions
  Content-Type: application/xml

  <fantasy_content>
    <transaction>
      <type>add/drop</type>
      <players>
        <player>
          <player_key>{add_player_key}</player_key>
          <transaction_data>
            <type>add</type>
            <destination_team_key>{my_team_key}</destination_team_key>
          </transaction_data>
        </player>
        <player>
          <player_key>{drop_player_key}</player_key>
          <transaction_data>
            <type>drop</type>
            <source_team_key>{my_team_key}</source_team_key>
          </transaction_data>
        </player>
      </players>
    </transaction>
  </fantasy_content>
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


EXECUTION_LOG = Path("data/execution_log.jsonl")


@dataclass
class TransactionResult:
    move_number: int
    add_name: str
    add_player_key: str
    drop_name: str
    drop_player_key: str
    dry_run: bool
    success: bool
    response_xml: Optional[str] = None
    error: Optional[str] = None
    executed_at: Optional[str] = None


def _build_adddrop_xml(
    add_player_key: str,
    drop_player_key: str,
    my_team_key: str,
) -> str:
    return f"""<fantasy_content>
  <transaction>
    <type>add/drop</type>
    <players>
      <player>
        <player_key>{add_player_key}</player_key>
        <transaction_data>
          <type>add</type>
          <destination_team_key>{my_team_key}</destination_team_key>
        </transaction_data>
      </player>
      <player>
        <player_key>{drop_player_key}</player_key>
        <transaction_data>
          <type>drop</type>
          <source_team_key>{my_team_key}</source_team_key>
        </transaction_data>
      </player>
    </players>
  </transaction>
</fantasy_content>"""


def _log_result(result: TransactionResult) -> None:
    EXECUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "move_number": result.move_number,
        "add": {"name": result.add_name, "key": result.add_player_key},
        "drop": {"name": result.drop_name, "key": result.drop_player_key},
        "dry_run": result.dry_run,
        "success": result.success,
        "error": result.error,
    }
    with EXECUTION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def execute_adddrop_plan(
    moves: list[dict],
    league_key: str,
    my_team_key: str,
    dry_run: bool = True,
    delay_seconds: float = 2.0,
) -> list[TransactionResult]:
    """
    Execute or dry-run an ordered list of add/drop moves.

    Args:
        moves: list of move dicts from adddrop_plan_to_dict()
        league_key: e.g. "469.l.40206"
        my_team_key: e.g. "469.l.40206.t.6"
        dry_run: if True, log but never POST to Yahoo API
        delay_seconds: seconds between transactions (avoid rate limiting)

    Returns:
        list of TransactionResult
    """
    # Hard gate — YAHOO_AUTO_EXECUTE must be explicitly "true"
    auto_execute = os.environ.get("YAHOO_AUTO_EXECUTE", "false").strip().lower()
    if auto_execute != "true":
        dry_run = True  # Force dry run regardless of parameter

    results = []

    for move in moves:
        move_num   = move.get("move_number", 0)
        add_name   = move.get("add", {}).get("name", "")
        add_key    = move.get("add", {}).get("key", "")
        drop_name  = move.get("drop", {}).get("name", "")
        drop_key   = move.get("drop", {}).get("key", "")

        if not add_key or not drop_key:
            result = TransactionResult(
                move_number=move_num,
                add_name=add_name,
                add_player_key=add_key,
                drop_name=drop_name,
                drop_player_key=drop_key,
                dry_run=dry_run,
                success=False,
                error="Missing player key — cannot execute",
            )
            _log_result(result)
            results.append(result)
            continue

        xml_body = _build_adddrop_xml(add_key, drop_key, my_team_key)

        if dry_run:
            result = TransactionResult(
                move_number=move_num,
                add_name=add_name,
                add_player_key=add_key,
                drop_name=drop_name,
                drop_player_key=drop_key,
                dry_run=True,
                success=True,
                response_xml=f"[DRY RUN] Would POST:\n{xml_body}",
                executed_at=datetime.now(tz=timezone.utc).isoformat(),
            )
            _log_result(result)
            results.append(result)
            continue

        # Live execution
        try:
            from yahoo_ai_gm.yahoo_client import YahooClient
            client = YahooClient.from_local_config()
            path = f"league/{league_key}/transactions"
            response_xml = client.post(path, body=xml_body)

            result = TransactionResult(
                move_number=move_num,
                add_name=add_name,
                add_player_key=add_key,
                drop_name=drop_name,
                drop_player_key=drop_key,
                dry_run=False,
                success=True,
                response_xml=response_xml,
                executed_at=datetime.now(tz=timezone.utc).isoformat(),
            )
        except Exception as e:
            result = TransactionResult(
                move_number=move_num,
                add_name=add_name,
                add_player_key=add_key,
                drop_name=drop_name,
                drop_player_key=drop_key,
                dry_run=False,
                success=False,
                error=str(e),
                executed_at=datetime.now(tz=timezone.utc).isoformat(),
            )

        _log_result(result)
        results.append(result)

        if delay_seconds > 0:
            time.sleep(delay_seconds)

    return results

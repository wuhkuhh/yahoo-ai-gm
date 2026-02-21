from yahoo_ai_gm.yahoo_client import YahooClient
import xml.etree.ElementTree as ET

NS = {"y": "http://fantasysports.yahooapis.com/fantasy/v2/base.rng"}

def text(node, path, default=""):
    el = node.find(path, NS)
    return el.text if el is not None and el.text is not None else default

def main():
    client = YahooClient.from_local_config()

    team_key = client.settings.team_key("team_key") if hasattr(client.settings, "__dict__") else None
    # fallback: just hardcode for now if you haven't added env var yet
    team_key = team_key or "469.l.40206.t.6"

    xml = client.get(f"team/{team_key}/roster")
    root = ET.fromstring(xml)

    players = root.findall(".//y:player", NS)
    print(f"Found {len(players)} players on roster\n")

    for p in players:
        name = text(p, "y:name/y:full")
        player_key = text(p, "y:player_key")
        pos = text(p, "y:display_position")
        status = text(p, "y:status")
        editorial_team = text(p, "y:editorial_team_abbr")
        print(f"- {name} ({editorial_team}) | {pos} | status={status or 'OK'} | {player_key}")

if __name__ == "__main__":
    main()

from yahoo_ai_gm.yahoo_client import YahooClient
import xml.etree.ElementTree as ET

NS = {"y": "http://fantasysports.yahooapis.com/fantasy/v2/base.rng"}

def text(node, path, default=""):
    el = node.find(path, NS)
    return el.text if el is not None and el.text is not None else default

def main():
    client = YahooClient.from_local_config()
    team_key = client.settings.team_key

    xml = client.get(f"team/{team_key}/matchups")
    root = ET.fromstring(xml)

    matchups = root.findall(".//y:matchup", NS)
    print(f"Found {len(matchups)} matchup(s)\n")

    for m in matchups:
        week = text(m, "y:week")
        status = text(m, "y:status")
        print(f"=== Week {week} | status={status} ===")

        teams = m.findall(".//y:teams/y:team", NS)
        for t in teams:
            name = text(t, "y:name")
            tkey = text(t, "y:team_key")
            print(f"- {name} ({tkey})")

        # If Yahoo includes stat_winners / stats in this response, we’ll see it here
        # (Some leagues require a different endpoint for full scoreboard stats.)
        print()

if __name__ == "__main__":
    main()

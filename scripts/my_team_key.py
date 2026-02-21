from yahoo_ai_gm.yahoo_client import YahooClient
import xml.etree.ElementTree as ET

NS = {"y": "http://fantasysports.yahooapis.com/fantasy/v2/base.rng"}

def text(node, path, default=""):
    el = node.find(path, NS)
    return el.text if el is not None and el.text is not None else default

def main():
    client = YahooClient.from_local_config()
    league_id = client.settings.league_id

    # Pull all teams in the league
    xml = client.get(f"league/mlb.l.{league_id}/teams")
    root = ET.fromstring(xml)

    teams = root.findall(".//y:team", NS)
    if not teams:
        raise SystemExit("No teams found. Check league id / permissions.")

    print(f"Found {len(teams)} teams in mlb.l.{league_id}\n")

    my_team = None
    for t in teams:
        team_key = text(t, "y:team_key")
        name = text(t, "y:name")
        team_id = text(t, "y:team_id")
        is_owned = text(t, "y:is_owned_by_current_login")  # "1" if you
        print(f"- {name} | team_id={team_id} | team_key={team_key} | owned={is_owned}")
        if is_owned == "1":
            my_team = (name, team_id, team_key)

    print("\n---- RESULT ----")
    if my_team:
        name, team_id, team_key = my_team
        print(f"Your team: {name}")
        print(f"team_id: {team_id}")
        print(f"team_key: {team_key}")
    else:
        print("Could not find your team via is_owned_by_current_login=1.")
        print("If this happens, we’ll match by your Yahoo nickname/user teams endpoint.")

if __name__ == "__main__":
    main()

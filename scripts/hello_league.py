from yahoo_ai_gm.yahoo_client import YahooClient

def main():
    client = YahooClient.from_local_config()
    league_id = client.settings.league_id
    xml = client.get(f"league/mlb.l.{league_id}")
    print(xml[:2000])

if __name__ == "__main__":
    main()

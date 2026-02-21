from yahoo_ai_gm.yahoo_client import YahooClient
import xml.etree.ElementTree as ET


def main():
    client = YahooClient.from_local_config()

    # Get current user
    xml = client.get("users;use_login=1/games")
    root = ET.fromstring(xml)

    print("---- USER INFO ----")
    print(xml[:1500])  # print first chunk for inspection


if __name__ == "__main__":
    main()

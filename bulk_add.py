import sys
import re

from db import RSSFeedDB
from lemmy import LemmyCommunicator
from feed_manager import add_feed

def parse_stdin():
    # Read all lines from stdin and join into a single string
    input_data = sys.stdin.read()
    # Split the input into tokens based on any amount of whitespace
    tokens = re.split(r'\s+', input_data.strip())

    # Pattern to match RSS feed URLs and extract parts for community naming
    url_pattern = re.compile(r'https?://([^/]*?)([a-zA-Z0-9_\-]+)\.([a-zA-Z0-9_\-]+)/.*')
    lemmy_api = LemmyCommunicator()
    db = RSSFeedDB()

    i = 0
    while i < len(tokens):
        token = tokens[i]
        match = url_pattern.match(token)
        if match:
            # Default community name from the URL
            default_community_name = match.group(2)
            community_name = default_community_name

            # Check if the next token is a valid community name following the pattern
            if i + 1 < len(tokens):
                next_token = tokens[i + 1]
                if '_' in next_token and next_token.split('_')[0] in token:
                    community_name = next_token
                    i += 1  # Skip the next token as it's used as the community name

            print(f"Feed URL: {token}, Community Name: {community_name}")
            add_feed(db, token, community_name, lemmy_api)

        i += 1

if __name__ == "__main__":
    parse_stdin()

import getpass
import requests
import os
import pickle
import time
from datetime import datetime, timezone, timedelta

from config import Config

def parse_datetime(date_str):
    """Parse datetime string into a datetime object."""
    for fmt in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S.%f%z'):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"time data {date_str!r} does not match any known format")

class LemmyCommunicator:
    TOKEN_FILE_TEMPLATE = "{server}_{user}_token.pkl"

    def __init__(self, username=None):
        self.server = Config.LEMMY_SERVER
        self.username = username if username else Config.LEMMY_USERNAME
        self.token = self.get_token()
        if not self.token:
            if Config.LEMMY_PASSWORD and not username:
                password = Config.LEMMY_PASSWORD
            else:
                password = getpass.getpass(f"Enter password for {self.username} on {self.server}: ")
            self.token = self.login(password)

    def get_token(self):
        token_file = self.TOKEN_FILE_TEMPLATE.format(server=self.server, user=self.username)
        if os.path.exists(token_file):
            with open(token_file, 'rb') as f:
                token_data = pickle.load(f)
                return token_data.get('jwt')
        return None

    def save_token(self, token):
        token_file = self.TOKEN_FILE_TEMPLATE.format(server=self.server, user=self.username)
        with open(token_file, 'wb') as f:
            pickle.dump({'jwt': token}, f)
        os.chmod(token_file, 0o600)

    def login(self, password):
        url = f'https://{self.server}/api/v3/user/login'
        headers = {'Content-Type': 'application/json'}
        data = {'username_or_email': self.username, 'password': password}
        response = self._make_request('post', url, headers=headers, json=data)
        token = response.json()['jwt']
        self.save_token(token)
        return token

    def fetch_user_id(self, actor_id):
        url = f'https://{self.server}/api/v3/user'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        params = {'username': self.url_to_username(actor_id)}
        response = self._make_request('get', url, headers=headers, params=params)
        user = response.json().get('person_view')
        if user:
            return user['person']['id']
        else:
            raise ValueError(f"User '{actor_id}' not found")

    def fetch_community_id(self, community_name):
        url = f'https://{self.server}/api/v3/community'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        params = {'name': community_name}
        response = self._make_request('get', url, headers=headers, params=params)
        community = response.json().get('community_view')
        if community:
            return community['community']['id']
        else:
            raise ValueError(f"Community '{self.community_name}' not found")

    def url_to_username(self, url):
        try:
            parts = url.split('/')
            instance = parts[2]
            username = parts[4]
            return f"{username}@{instance}"
        except IndexError:
            raise ValueError(f"Invalid URL format: {url}")

    def build_ban_map(self, modlog):
        ban_map = {}
        for entry in modlog:
            ban_event = entry['mod_ban_from_community']
            banned_person = entry['banned_person']['actor_id']
            if banned_person not in ban_map or ban_event['when_'] > ban_map[banned_person]['mod_ban_from_community']['when_']:
                ban_map[banned_person] = entry
        return ban_map

    def read_banlist(self, banlist_file):
        with open(banlist_file, 'r') as f:
            return {line.strip() for line in f}

    def delete_comment(self, comment_id):
        url = f'https://{self.server}/api/v3/comment/remove'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'comment_id': comment_id,
            'removed': True,
            'reason': Config.DELETE_REASON.format(server=Config.LEMMY_SERVER)
        }
        self._make_request('post', url, headers=headers, json=data)

    def delete_post(self, post_id):
        url = f'https://{self.server}/api/v3/post/remove'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'post_id': post_id,
            'removed': True,
            'reason': Config.DELETE_REASON.format(server=Config.LEMMY_SERVER)
        }
        self._make_request('post', url, headers=headers, json=data)

    def send_message(self, user_id, subject, message):
        url = f'https://{self.server}/api/v3/private_message'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'recipient_id': user_id,
            'subject': subject,
            'content': message
        }
        self._make_request('post', url, headers=headers, json=data)

    def create_post(self, community_id, name, **kwargs):
        """Create a post in a specified community."""
        url = f'https://{self.server}/api/v3/post'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'community_id': community_id,
            'name': name
        }
        # Adding optional parameters
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value

        response = self._make_request('post', url, headers=headers, json=data)
        return response.json()['post_view']['post']

    def create_community(self, name, title, **kwargs):
        """Create a new community."""
        url = f'https://{self.server}/api/v3/community'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'name': name,
            'title': title
        }
        # Adding optional parameters
        for key, value in kwargs.items():
            if value is not None:
                data[key] = value
        print(data)

        response = self._make_request('post', url, headers=headers, json=data)
        return response.json()['community_view']['community']

    def appoint_mod(self, community_id, person_id, mod_status=True):
        """Create a new community."""
        url = f'https://{self.server}/api/v3/community/mod'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'community_id': community_id,
            'person_id': person_id,
            'added': mod_status
        }
        print(data)

        self._make_request('post', url, headers=headers, json=data)

    def create_comment(self, post_id, content):
        url = f'https://{self.server}/api/v3/comment'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'post_id': post_id,
            'content': content
        }
        response = self._make_request('post', url, headers=headers, json=data)
        return response.json()['comment_view']['comment']

    def _make_request(self, method, url, **kwargs):
        time.sleep(Config.REQUEST_DELAY)
        while True:
            response = requests.request(method, url, **kwargs)
            if response.status_code == 429 or response.status_code == 503:
                print("Rate limited. Sleeping for 60 seconds.")
                time.sleep(60)
                continue
            elif not response.ok:
                response.raise_for_status()
            return response

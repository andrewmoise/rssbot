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
        self.community_name = Config.LEMMY_COMMUNITY
        self.token = self.get_token()
        if not self.token:
            if Config.LEMMY_PASSWORD and not username:
                password = Config.LEMMY_PASSWORD
            else:
                password = getpass.getpass(f"Enter password for {self.username} on {self.server}: ")
            self.token = self.login(password)
        self.community_id = self.fetch_community_id()

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

    def fetch_community_id(self):
        url = f'https://{self.server}/api/v3/community'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        params = {'name': self.community_name}
        response = self._make_request('get', url, headers=headers, params=params)
        community = response.json().get('community_view')
        if community:
            return community['community']['id']
        else:
            raise ValueError(f"Community '{self.community_name}' not found")

    def fetch_modlog(self):
        modlog = []
        page = 1
        while True:
            url = f'https://{self.server}/api/v3/modlog'
            headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
            params = {'community_id': self.community_id, 'type_': 'ModBanFromCommunity', 'page': page, 'limit': 50}
            response = self._make_request('get', url, headers=headers, params=params)
            data = response.json().get('banned_from_community', [])

            if not data:
                break

            modlog.extend(data)
            page += 1

        return modlog

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

    def ban_user(self, user_id, ban=True):
        url = f'https://{self.server}/api/v3/community/ban_user'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        if ban:
            reason = Config.BAN_REASON.format(server=Config.LEMMY_SERVER)
        else:
            reason = Config.UNBAN_REASON.format(server=Config.LEMMY_SERVER)

        data = {
            'community_id': self.community_id,
            'person_id': user_id,
            'ban': ban,
            'reason': reason,
            'remove_data': False
        }

        self._make_request('post', url, headers=headers, json=data)

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

    def create_post(self, title, content):
        url = f'https://{self.server}/api/v3/post'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'community_id': self.community_id,
            'name': title,
            'body': content
        }
        response = self._make_request('post', url, headers=headers, json=data)
        return response.json()['post_view']['post']

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

    def print_recent_content_to_remove(self, banlist, hours=3):
        """
        Print recent content from banned users flagged for content removal.

        Args:
        banlist: Dictionary of users with their ban status and content removal flag.
        hours: The time threshold for removing recent content.
        """
        threshold_time = datetime.now(timezone.utc) - timedelta(hours=hours)

        for comment in self.fetch_recent_comments():
            comment_id = comment['comment']['id']
            comment_time = parse_datetime(comment['comment']['published'])
            user_id = comment['creator']['id']
            if comment_time < threshold_time:
                break
            if banlist.get(user_id) == (True, True, True):
                print(f"Recent comment by banned user {user_id}: {comment_id}")

        for post in self.fetch_recent_posts():
            post_id = post['post']['id']
            post_time = parse_datetime(post['post']['published'])
            user_id = post['creator']['id']
            if post_time < threshold_time:
                break
            if banlist.get(user_id) == (True, True, True):
                print(f"Recent post by banned user {user_id}: {post_id}")

    def fetch_recent_comments(self):
        page = 1
        while True:
            url = f'https://{self.server}/api/v3/comment/list'
            headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
            params = {
                'type_': 'All',
                'community_id': self.community_id,
                'limit': 50,
                'sort': 'New',
                'page': page
            }
            try:
                response = self._make_request('get', url, headers=headers, params=params)
                response.raise_for_status()
                comments = response.json().get('comments', [])
                if not comments:
                    break
                for comment in comments:
                    yield comment
                page += 1
            except requests.exceptions.RequestException as e:
                print(f"Failed to fetch recent comments: {e}")
                break

    def fetch_recent_posts(self):
        page = 1
        while True:
            url = f'https://{self.server}/api/v3/post/list'
            headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
            params = {
                'community_id': self.community_id,
                'limit': 50,
                'sort': 'New',
                'page': page
            }
            try:
                response = self._make_request('get', url, headers=headers, params=params)
                response.raise_for_status()
                posts = response.json().get('posts', [])
                if not posts:
                    break
                for post in posts:
                    yield post
                page += 1
            except requests.exceptions.RequestException as e:
                print(f"Failed to fetch recent posts: {e}")
                break

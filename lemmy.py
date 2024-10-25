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

    def __init__(self, username, server=Config.LEMMY_SERVER, logger=None):
        self.logger = logger
        self.server = server
        self.username = username
        self.token = self.get_token()
        if not self.token:
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

    def resolve_community(self, community_name):
        url = f'https://{self.server}/api/v3/resolve_object'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        short_name, instance = community_name.split('@')
        params = {'q': f"https://{instance}/c/{short_name}"}
        #params = {'q': community_name, 'type_': 'Communities'}
        response = self._make_request('get', url, headers=headers, params=params)
        community = response.json().get('community')
        return community

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

    def fetch_community_moderators(self, community_name):
        url = f'https://{self.server}/api/v3/community'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        params = {'name': community_name}
        response = self._make_request('get', url, headers=headers, params=params)
        moderators = response.json().get('moderators')
        if moderators:
            return moderators
        else:
            raise ValueError(f"Community '{community_name}' not found")

    def subscribe_to_community(self, community_id, follow=True):
        """Subscribe to or unsubscribe from a community."""
        url = f'https://{self.server}/api/v3/community/follow'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'community_id': community_id,
            'follow': follow
        }
        response = self._make_request('post', url, headers=headers, json=data)
        return response.json()['community_view']['subscribed']

    def url_to_username(self, url):
        try:
            parts = url.split('/')
            if len(parts) <= 1:
                return parts[0]
            else:
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

        try:
            self._make_request('post', url, headers=headers, json=data)
        except requests.exceptions.HTTPError:
            print('Got HTTP error')

    def create_comment(self, post_id, content, parent_id=None):
        url = f'https://{self.server}/api/v3/comment'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'post_id': post_id,
            'content': content
        }
        if parent_id is not None:
            data['parent_id'] = parent_id
        response = self._make_request('post', url, headers=headers, json=data)
        return response.json()['comment_view']['comment']

    def get_private_messages(self, unread_only=False, page=1, limit=20):
        """Fetch private messages for the user."""
        url = f'https://{self.server}/api/v3/private_message/list'
        headers = {'Authorization': f'Bearer {self.token}'}
        params = {
            'unread_only': 'true' if unread_only else 'false',
            'page': page,
            'limit': limit
        }
        response = self._make_request('get', url, headers=headers, params=params)
        return response.json()['private_messages']

    def mark_private_message_as_read(self, private_message_id, read=True):
        """Mark a private message as read or unread."""
        url = f'https://{self.server}/api/v3/private_message/mark_as_read'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'private_message_id': private_message_id,
            'read': read
        }
        response = self._make_request('post', url, headers=headers, json=data)
        return response.json()['private_message_view']

    def send_private_message(self, recipient_id, content):
        """Send a private message to a user."""
        url = f'https://{self.server}/api/v3/private_message'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'recipient_id': recipient_id,
            'content': content
        }
        response = self._make_request('post', url, headers=headers, json=data)
        return response.json()['private_message_view']

    def get_mentions(self, sort='New', page=1, limit=20, unread_only=True):
        """Get mentions for the user."""
        url = f'https://{self.server}/api/v3/user/mention'
        headers = {'Authorization': f'Bearer {self.token}'}
        params = {
            'sort': sort,
            'page': page,
            'limit': limit,
            'unread_only': 'true' if unread_only else 'false'
        }
        response = self._make_request('get', url, headers=headers, params=params)
        return response.json()['mentions']

    def mark_mention_as_read(self, person_mention_id, read=True):
        """Mark a mention as read or unread."""
        url = f'https://{self.server}/api/v3/user/mention/mark_as_read'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'person_mention_id': person_mention_id,
            'read': read
        }
        response = self._make_request('post', url, headers=headers, json=data)
        return response.json()

    def reply_to_comment(self, post_id, content, parent_id=None):
        """Create a comment in reply to another comment or post."""
        url = f'https://{self.server}/api/v3/comment'
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        data = {
            'content': content,
            'post_id': post_id,
            'parent_id': parent_id
        }
        response = self._make_request('post', url, headers=headers, json=data)
        return response.json()['comment_view']['comment']

    def handle_messages_and_mentions(self, mark_as_read=False, auto_reply=False):
        """
        Iterate over all mentions and private messages for the user.
        Optionally mark them as read and/or auto-reply.
        """
        # Handle private messages
        private_messages = self.get_private_messages(unread_only=True)
        for pm in private_messages:
            print(f"Private message from {pm['creator']['name']}: {pm['private_message']['content']}")
            
            if mark_as_read:
                self.mark_private_message_as_read(pm['private_message']['id'])
            
            if auto_reply:
                reply_content = f"Thank you for your message, {pm['creator']['name']}. This is an automated response."
                self.send_private_message(pm['creator']['id'], reply_content)

        # Handle mentions
        mentions = self.get_mentions(unread_only=True)
        for mention in mentions:
            print(f"Mention from {mention['creator']['name']} in post '{mention['post']['name']}': {mention['comment']['content']}")
            
            if mark_as_read:
                self.mark_mention_as_read(mention['person_mention']['id'])
            
            if auto_reply:
                reply_content = f"Thank you for mentioning me, {mention['creator']['name']}. This is an automated response."
                self.reply_to_comment(mention['post']['id'], reply_content, parent_id=mention['comment']['id'])

    def _make_request(self, method, url, **kwargs):
        time.sleep(Config.REQUEST_DELAY)
        while True:
            try:
                response = requests.request(method, url, **kwargs)
                
                if response.status_code == 429 or response.status_code == 503:
                    print("Rate limited. Sleeping for 60 seconds.")
                    time.sleep(60)
                    continue
                elif not response.ok:
                    if self.logger is not None:
                        # Log the request details
                        self.logger.error(f"Request failed: {method} {url}")
                        self.logger.error(f"Request headers: {kwargs.get('headers', {})}")
                        self.logger.error(f"Request body: {kwargs.get('json', '')}")
                        
                        # Log the response details
                        self.logger.error(f"Response status code: {response.status_code}")
                        self.logger.error(f"Response headers: {response.headers}")
                        self.logger.error(f"Response content: {response.text}")
                    
                    response.raise_for_status()
                
                return response
            
            except requests.exceptions.RequestException as e:
                # Log any request exceptions
                if self.logger is not None:
                    self.logger.exception(f"Request exception occurred: {str(e)}")
                raise
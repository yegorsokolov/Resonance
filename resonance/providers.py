"""Official API adapters. No passwords, scraping, playback, or audio downloads."""
import time
import requests


class ProviderError(Exception):
    pass


CONFIG = {
    'spotify': {
        'authorize': 'https://accounts.spotify.com/authorize',
        'token': 'https://accounts.spotify.com/api/token',
        'scope': 'playlist-read-private playlist-read-collaborative playlist-modify-private user-library-read user-library-modify user-read-recently-played user-follow-read',
    },
    'youtube': {
        'authorize': 'https://accounts.google.com/o/oauth2/v2/auth',
        'token': 'https://oauth2.googleapis.com/token',
        'scope': 'https://www.googleapis.com/auth/youtube',
    },
}


def exchange(provider, client, secret, data):
    try:
        r = requests.post(CONFIG[provider]['token'], data={
            'client_id': client, 'client_secret': secret, **data}, timeout=30)
        if not r.ok:
            raise ProviderError('Authorization failed. Reconnect your account and check app credentials.')
        token = r.json()
        token['expires_at'] = time.time() + token.get('expires_in', 3600) - 60
        return token
    except requests.RequestException as exc:
        raise ProviderError('Authorization service unavailable.') from exc


def spotify_track(t):
    if not t or not t.get('id') or t.get('is_local') or t.get('type', 'track') != 'track':
        return None
    return {'id': t['id'], 'title': t['name'],
            'artist': ', '.join(a['name'] for a in t.get('artists', [])),
            'album': t.get('album', {}).get('name', ''),
            'isrc': t.get('external_ids', {}).get('isrc', ''),
            'duration_ms': t.get('duration_ms'), 'origin': 'spotify'}


class API:
    def __init__(self, provider, token, refresh):
        self.provider, self.token, self.refresh = provider, token, refresh
        self.base = ('https://api.spotify.com/v1/' if provider == 'spotify'
                     else 'https://www.googleapis.com/youtube/v3/')

    def call(self, method, path, params=None, body=None):
        if time.time() >= self.token.get('expires_at', 0):
            self.refresh()
        # Retry only explicit rate-limit rejections. Never blindly replay a write.
        for attempt in range(3):
            try:
                r = requests.request(method, self.base + path,
                                     headers={'Authorization': 'Bearer ' + self.token['access_token']},
                                     params=params, json=body, timeout=30)
            except requests.RequestException as exc:
                raise ProviderError('Network failure; a pending destination write may have completed. Inspect it before starting a new transfer.') from exc
            if r.status_code == 429 and attempt < 2:
                time.sleep(min(max(int(r.headers.get('Retry-After', 2)), 1), 30))
                continue
            if not r.ok:
                raise ProviderError(f'{self.provider} returned HTTP {r.status_code}. Check permissions, quota and account access. Pending writes require inspection before a new transfer.')
            return r.json() if r.content else {}
        raise ProviderError('Rate limited. Try again later.')

    def pages(self, path, params=None, key='items'):
        params = dict(params or {})
        result = []
        while True:
            page = self.call('GET', path, params)
            result.extend(page.get(key, []))
            if self.provider == 'youtube':
                if not page.get('nextPageToken'):
                    break
                params['pageToken'] = page['nextPageToken']
            else:
                if not page.get('next'):
                    break
                params['offset'] = params.get('offset', 0) + len(page.get(key, []))
                if not page.get(key):
                    break
        return result

    def collections(self):
        if self.provider == 'spotify':
            items = self.pages('me/playlists', {'limit': 50})
            return [{'id': p['id'], 'name': p['name'], 'kind': 'playlist',
                     'readable': 'items' in p or 'tracks' in p} for p in items] + [
                         {'id': '@liked', 'name': 'Liked songs', 'kind': 'library', 'readable': True},
                         {'id': '@albums', 'name': 'Saved albums (tracks)', 'kind': 'library', 'readable': True},
                         {'id': '@history', 'name': 'Recent listening history', 'kind': 'history', 'readable': True}]
        items = self.pages('playlists', {'part': 'snippet', 'mine': 'true', 'maxResults': 50})
        return [{'id': p['id'], 'name': p['snippet']['title'], 'kind': 'playlist', 'readable': True} for p in items] + [
            {'id': '@liked', 'name': 'Liked videos', 'kind': 'library', 'readable': True}]

    def tracks(self, collection):
        if self.provider == 'spotify':
            if collection == '@history':
                raw = self.call('GET', 'me/player/recently-played', {'limit': 50})['items']
            elif collection == '@liked':
                raw = self.pages('me/tracks', {'limit': 50})
            elif collection == '@albums':
                raw = []
                for a in self.pages('me/albums', {'limit': 50}):
                    for t in self.pages(f"albums/{a['album']['id']}/tracks", {'limit': 50}):
                        t['album'] = {'name': a['album']['name']}
                        raw.append({'track': t})
            else:
                raw = self.pages(f'playlists/{collection}/items', {'limit': 50})
            result = []
            for item in raw:
                t = spotify_track(item.get('item') or item.get('track'))
                if t:
                    t['played_at'] = item.get('played_at')
                    result.append(t)
            return result, len(raw) - len(result)
        if collection == '@liked':
            raw = self.pages('videos', {'part': 'snippet,contentDetails', 'myRating': 'like', 'maxResults': 50})
        else:
            raw = self.pages('playlistItems', {'part': 'snippet,contentDetails', 'playlistId': collection, 'maxResults': 50})
        tracks = []
        for p in raw:
            s = p['snippet']
            if s['title'] in ('Deleted video', 'Private video'):
                continue
            tracks.append({'id': p.get('contentDetails', {}).get('videoId', p['id']),
                           'title': s['title'], 'artist': s.get('videoOwnerChannelTitle', s.get('channelTitle', '')),
                           'origin': 'youtube'})
        return tracks, len(raw) - len(tracks)

    def search(self, track):
        if self.provider == 'spotify':
            if track.get('isrc'):
                exact = self.call('GET', 'search', {'q': 'isrc:' + track['isrc'], 'type': 'track', 'limit': 5})
                found = [spotify_track(t) for t in exact.get('tracks', {}).get('items', [])]
                if found:
                    return [t for t in found if t]
            r = self.call('GET', 'search', {'q': track['title'] + ' ' + track.get('artist', ''), 'type': 'track', 'limit': 5})
            return [v for t in r.get('tracks', {}).get('items', []) if (v := spotify_track(t))]
        r = self.call('GET', 'search', {'part': 'snippet', 'q': track['title'] + ' ' + track.get('artist', ''), 'type': 'video', 'maxResults': 5})
        return [{'id': t['id']['videoId'], 'title': t['snippet']['title'],
                 'artist': t['snippet']['channelTitle'], 'origin': 'youtube'} for t in r.get('items', [])]

    def create_playlist(self, name):
        if self.provider == 'spotify':
            return self.call('POST', 'me/playlists', body={'name': name[:100], 'public': False,
                        'description': 'Transferred with Resonance. History timestamps remain in the archive.'})['id']
        return self.call('POST', 'playlists', {'part': 'snippet,status'}, {
            'snippet': {'title': name[:100], 'description': 'Transferred with Resonance'},
            'status': {'privacyStatus': 'private'}})['id']

    def add(self, playlist, track_id, liked=False):
        if self.provider == 'spotify':
            if liked:
                return self.call('PUT', 'me/library', {'uris': 'spotify:track:' + track_id})
            return self.call('POST', f'playlists/{playlist}/items', body={'uris': ['spotify:track:' + track_id]})
        return self.call('POST', 'playlistItems', {'part': 'snippet'}, {'snippet': {
            'playlistId': playlist, 'resourceId': {'kind': 'youtube#video', 'videoId': track_id}}})

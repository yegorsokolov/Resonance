import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from difflib import SequenceMatcher


def normalized(value):
    value = unicodedata.normalize('NFKD', value).casefold()
    return re.sub(r'[^\w\s]', '', value).strip()


def score(source, candidate):
    if source.get('isrc') and source.get('isrc') == candidate.get('isrc'):
        return 1.0
    title = SequenceMatcher(None, normalized(source['title']), normalized(candidate['title'])).ratio()
    artist = SequenceMatcher(None, normalized(source.get('artist', '')), normalized(candidate.get('artist', ''))).ratio()
    result = .7 * title + .3 * artist
    for version in ('live', 'remix', 'karaoke', 'instrumental', 'cover', 'sped up'):
        if (version in source['title'].lower()) != (version in candidate['title'].lower()):
            result -= .25
    if source.get('duration_ms') and candidate.get('duration_ms'):
        if abs(source['duration_ms'] - candidate['duration_ms']) > 10000:
            result -= .2
    return round(max(0, result), 3)


def validate_archive(data):
    if not isinstance(data, dict) or data.get('schema') != 'resonance/1':
        raise ValueError('Expected a resonance/1 JSON archive.')
    collections = data.get('collections')
    if not isinstance(collections, list) or len(collections) > 500:
        raise ValueError('Archive must contain at most 500 collections.')
    count = 0
    for c in collections:
        if not isinstance(c, dict) or not isinstance(c.get('name'), str) or not isinstance(c.get('tracks'), list):
            raise ValueError('Invalid collection.')
        c['name'] = c['name'][:100]
        c['kind'] = c.get('kind', 'playlist')
        for t in c['tracks']:
            if not isinstance(t, dict) or not isinstance(t.get('title'), str) or not t['title'].strip():
                raise ValueError('Each track needs a title.')
            if not isinstance(t.get('artist', ''), str):
                raise ValueError('Artist must be text.')
            # Provenance is never upgraded by import. Spotify data stays AI-ineligible.
            t['origin'] = 'spotify' if data.get('provider') == 'spotify' or t.get('origin') == 'spotify' else 'import'
            count += 1
    if count > 20000:
        raise ValueError('Archive exceeds 20,000 tracks. Split it into smaller archives.')
    return data


def history_archive(raw):
    if not isinstance(raw, list) or len(raw) > 20000:
        raise ValueError('Expected a Spotify streaming-history JSON array, up to 20,000 entries.')
    tracks = []
    for item in raw:
        title = item.get('master_metadata_track_name') or item.get('trackName')
        artist = item.get('master_metadata_album_artist_name') or item.get('artistName')
        if not title:
            continue
        tracks.append({'title': title, 'artist': artist or '', 'origin': 'spotify',
                       'played_at': item.get('ts') or item.get('endTime'),
                       'ms_played': item.get('ms_played', item.get('msPlayed'))})
    return validate_archive({'schema': 'resonance/1', 'provider': 'spotify', 'collections': [
        {'name': 'Listening history', 'kind': 'history', 'tracks': tracks}]})


class Store:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, owner TEXT, data TEXT)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, job, owner):
        with self.connect() as db:
            db.execute('INSERT INTO jobs VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data WHERE owner=excluded.owner',
                       (job['id'], owner, json.dumps(job)))

    def get(self, job_id, owner):
        with self.connect() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=? AND owner=?', (job_id, owner)).fetchone()
        if not row:
            raise KeyError('Transfer not found.')
        return json.loads(row[0])

    def delete(self, owner):
        with self.connect() as db:
            db.execute('DELETE FROM jobs WHERE owner=?', (owner,))

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

from resonance.engine import score, validate_archive, history_archive, Store
from resonance.providers import API, ProviderError
from resonance.web import create_app


class EngineTests(unittest.TestCase):
    def test_recording_versions_are_not_confident_matches(self):
        a = {'title': 'Song', 'artist': 'Artist'}
        self.assertEqual(score(a, a), 1)
        self.assertLess(score(a, {**a, 'title': 'Song live'}), .8)
        self.assertLess(score({**a, 'duration_ms': 100000}, {**a, 'duration_ms': 150000}), .94)

    def test_spotify_import_keeps_provenance_and_timestamps(self):
        a = history_archive([{'trackName': 'Song', 'artistName': 'A', 'endTime': '2020-01-01', 'msPlayed': 400}])
        t = a['collections'][0]['tracks'][0]
        self.assertEqual(t['origin'], 'spotify')
        self.assertEqual(t['played_at'], '2020-01-01')
        self.assertEqual(t['ms_played'], 400)
        self.assertEqual(validate_archive(a)['collections'][0]['tracks'][0]['origin'], 'spotify')

    def test_bad_archive(self):
        for value in ({}, [], {'schema': 'resonance/1', 'collections': [{'name': 'x', 'tracks': [{}]}]}):
            with self.assertRaises(ValueError):
                validate_archive(value)

    def test_store_owner_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            store = Store(str(Path(td) / 'test.sqlite'))
            store.save({'id': 'a', 'value': 1}, 'alice')
            with self.assertRaises(KeyError):
                store.get('a', 'bob')
            store.save({'id': 'a', 'value': 2}, 'bob')
            self.assertEqual(store.get('a', 'alice')['value'], 1)


class ProviderTests(unittest.TestCase):
    def test_youtube_pagination(self):
        api = API('youtube', {}, lambda: None)
        api.call = Mock(side_effect=[{'items': [1], 'nextPageToken': 'next'}, {'items': [2]}])
        self.assertEqual(api.pages('playlists'), [1, 2])
        self.assertEqual(api.call.call_args.args[2]['pageToken'], 'next')

    def test_new_spotify_endpoints(self):
        api = API('spotify', {}, lambda: None)
        api.call = Mock(return_value={'id': 'new'})
        self.assertEqual(api.create_playlist('x'), 'new')
        self.assertEqual(api.call.call_args.args[:2], ('POST', 'me/playlists'))
        api.add('new', 'song')
        self.assertEqual(api.call.call_args.args[:2], ('POST', 'playlists/new/items'))
        api.add(None, 'song', liked=True)
        self.assertEqual(api.call.call_args.args[:2], ('PUT', 'me/library'))

    @patch('resonance.providers.requests.request')
    def test_network_write_is_not_retried(self, call):
        import requests
        call.side_effect = requests.Timeout()
        api = API('spotify', {'access_token': 'x', 'expires_at': time.time()+100}, lambda: None)
        with self.assertRaises(ProviderError):
            api.add('p', 't')
        self.assertEqual(call.call_count, 1)


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'DATA_PATH': str(Path(self.tmp.name)/'db.sqlite')})
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as s:
            self.csrf, self.sid = s['csrf'], s['sid']

    def tearDown(self):
        self.tmp.cleanup()

    def post(self, url, data):
        return self.client.post(url, json=data, headers={'X-CSRF-Token': self.csrf})

    def test_csrf_and_oauth_state(self):
        self.assertEqual(self.client.post('/api/disconnect').status_code, 403)
        self.assertEqual(self.client.get('/auth/spotify/callback?state=bad&code=x').status_code, 400)

    def test_tokens_never_in_browser_cookie(self):
        self.app.extensions['resonance_vault'][self.sid]['tokens']['spotify'] = {'access_token': 'VERY_SECRET'}
        response = self.client.get('/api/status')
        self.assertNotIn('VERY_SECRET', response.get_data(as_text=True))
        self.assertNotIn('VERY_SECRET', str(response.headers))

    def test_ai_rejects_spotify_before_network(self):
        store = self.app.extensions['resonance_store']
        store.save({'id': 'j', 'source': 'import', 'destination': 'youtube', 'rows': [{'source': {'origin': 'spotify'}}]}, self.sid)
        with patch('resonance.web.requests.post') as post:
            r = self.post('/api/jobs/j/ai', {'row': 0, 'key': 'secret', 'consent': True})
            self.assertEqual(r.status_code, 400)
            post.assert_not_called()

    def test_review_transfer_archive_and_no_replay(self):
        track = {'title': 'Song', 'artist': 'Artist', 'origin': 'import'}
        archive = {'schema': 'resonance/1', 'collections': [{'name': 'My music', 'tracks': [track]}]}
        self.assertEqual(self.post('/api/import', archive).status_code, 200)
        self.app.extensions['resonance_vault'][self.sid]['tokens']['youtube'] = {'access_token': 'x'}
        with patch.object(API, 'search', return_value=[{**track, 'id': 'v'}]), patch.object(API, 'create_playlist', return_value='p') as create, patch.object(API, 'add') as add:
            response = self.post('/api/plan', {'source': 'import', 'destination': 'youtube', 'collections': ['0']})
            jid = response.json['id']
            self.wait(jid, 'review')
            self.assertEqual(self.post(f'/api/jobs/{jid}/review', {'choices': [8]}).status_code, 400)
            self.assertEqual(self.post(f'/api/jobs/{jid}/review', {'choices': [0]}).status_code, 200)
            self.assertEqual(self.post(f'/api/jobs/{jid}/execute', {}).status_code, 202)
            self.wait(jid, 'complete')
            self.assertEqual(self.post(f'/api/jobs/{jid}/execute', {}).status_code, 400)
            create.assert_called_once()
            add.assert_called_once_with('p', 'v', False)
            downloaded = self.client.get(f'/api/jobs/{jid}/archive').json
            self.assertEqual(downloaded['collections'][0]['tracks'][0]['title'], 'Song')
        other = self.app.test_client()
        self.assertEqual(other.get(f'/api/jobs/{jid}').status_code, 404)
        self.assertEqual(self.post('/api/disconnect', {}).status_code, 200)
        self.assertEqual(self.client.get(f'/api/jobs/{jid}').status_code, 404)

    def test_ambiguous_write_records_attention(self):
        job = {'id': 'uncertain', 'source': 'import', 'destination': 'youtube', 'status': 'review',
               'collections': [{'name': 'Test', 'kind': 'playlist', 'liked': False, 'playlist': None}],
               'rows': [{'collection': 0, 'choice': 0, 'candidates': [{'id': 'v'}], 'status': 'pending'}]}
        self.app.extensions['resonance_store'].save(job, self.sid)
        self.app.extensions['resonance_vault'][self.sid]['tokens']['youtube'] = {}
        with patch.object(API, 'create_playlist', return_value='p'), patch.object(API, 'add', side_effect=ProviderError('Timeout')):
            self.assertEqual(self.post('/api/jobs/uncertain/execute', {}).status_code, 202)
            j = self.wait('uncertain', 'needs_attention')
            self.assertEqual(j['rows'][0]['status'], 'writing')
            self.assertEqual(self.post('/api/jobs/uncertain/execute', {}).status_code, 400)

    def wait(self, jid, status):
        for _ in range(100):
            job = self.client.get('/api/jobs/'+jid).json
            if job['status'] == status:
                # Worker releases operation lock just after persisting final status.
                time.sleep(.02)
                return job
            time.sleep(.01)
        self.fail(str(job))


if __name__ == '__main__':
    unittest.main()

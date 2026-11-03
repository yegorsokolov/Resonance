# Resonance

**Take your music with you.** Resonance is a personal, self-hosted music library transfer app with official Spotify and YouTube OAuth connections, candidate matching, manual review, private playlist creation, and portable history archives.

## What works

| Source | Read | Destination behavior |
| --- | --- | --- |
| Spotify | Accessible playlists, liked songs, saved album tracks, recent plays | YouTube private playlists |
| YouTube | Playlists and liked videos | Spotify private playlists; liked videos can become saved tracks |
| Resonance JSON | Track collections and preserved play timestamps | Either connected service |
| Spotify data-export JSON | Standard or extended streaming-history files | Either service, as a deduplicated history playlist plus an archive |

Spotify saved albums transfer as a collection of tracks, not native album saves. Artist follows, podcasts, audiobooks, folders, artwork, recommendations, and audio files are not transferred. YouTube is supported through the official **YouTube Data API**, not an unofficial YouTube Music API; no promise is made that every created video playlist appears in YouTube Music.

**Native listening history cannot be imported.** Timestamp and play-duration records remain in the downloadable JSON archive. A destination history playlist represents recordings, not actual plays or reconstructed recommendation profiles. Spotify recent plays are a limited window, not lifetime history. For full history, request your Spotify data export and import the individual JSON files.

## Run locally

Requires Python 3.11+.

```sh
git clone https://github.com/yegorsokolov/Resonance.git
cd Resonance
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`. Set `SECRET_KEY` to a long random value (for example, generate one with `python -c "import secrets; print(secrets.token_hex(32))"`). Never commit `.env`.

1. Create an app in the [Spotify developer dashboard](https://developer.spotify.com/dashboard). Add `http://127.0.0.1:8888/auth/spotify/callback` as its redirect URI. Set `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`.
2. In [Google Cloud Console](https://console.cloud.google.com/), enable **YouTube Data API v3**, configure the OAuth consent screen, and create a **Web application** OAuth client. Register `http://127.0.0.1:8888/auth/youtube/callback`. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. Add yourself as a test user if the app is in testing.
3. Run `python run.py`, then open **http://127.0.0.1:8888**. The exact host matters for OAuth and host validation; do not substitute `localhost`.
4. Connect both accounts, choose source and destination, load the library, select collections, and find matches.
5. Review the candidates. A conservative match may be preselected; unresolved tracks default to Skip. Confirm the transfer only after reviewing the choices. Download the archive/report before clearing data.

Spotify’s [2026 development-mode changes](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide) restrict app access and playlist readability. The app uses `/me/playlists`, `/playlists/{id}/items`, and `/me/library`. App owner Premium, allowlisted users, and any required platform approval are your responsibility. Google testing tokens can expire, and search plus per-track insertions consume quota quickly; start with a small playlist. Quota errors appear in the transfer report.

## Optional AI mismatch assistance

Manual matching works without AI. To request a suggestion for an eligible track, expand the AI panel, enter your API key, give consent, and choose **Ask AI** on that row. The server calls the HTTPS OpenAI-compatible chat-completions URL in `AI_URL` using `AI_MODEL`; the key is not stored. The title, artist and candidate list for that row are sent to the configured service. The response is a suggestion requiring review, never permission to write.

**Spotify data is excluded from AI calls**, including Spotify-origin imports and Spotify destination candidates. The [Spotify developer policy](https://developer.spotify.com/policy) prohibits ingesting Spotify content into AI models. Do not relabel Spotify exports as independent data to bypass this restriction. AI is available for independently supplied imports matched against YouTube candidates. YouTube/Google policies and your AI provider’s data handling terms must also permit your intended use.

## Reliability, privacy and limits

- This is a **single-process personal app**, bound to loopback. Do not expose the Flask development server to the public internet. This is not a hardened multi-tenant SaaS deployment.
- OAuth uses state validation, PKCE, fixed callback URLs, and server-side token storage. Browser cookies contain session identifiers and CSRF material, not provider tokens. No provider passwords are collected.
- Provider tokens and imported source archives stay in process memory until disconnect, session expiry on next access (12 hours), or restart. Transfer snapshots are stored unencrypted in `instance/resonance.sqlite`; protect the local account and disk.
- Jobs are scoped to a browser session. Refreshing the page restores the latest job ID from sessionStorage. Keep the same cookie and `SECRET_KEY` to retrieve records across restart; reconnect provider accounts after restarting.
- A restart stops background work. In-progress records are marked interrupted at startup. There is no automatic resume. Inspect the destination and report before starting another transfer.
- Every destination write is checkpointed before sending. A network error leaves a `writing` record because the provider might have accepted it. No automatic write replay occurs; this avoids silently duplicating playlists/items, but does not guarantee exactly-once writes across network failures.
- A new transfer creates new private playlists; it does not merge or synchronize an existing destination playlist. Re-running a completed transfer can create duplicates. Source collections are never modified.
- Unavailable/local Spotify tracks and private/deleted YouTube videos are omitted and counted. Unmatched tracks remain in the archive and are skipped at the destination. Playlist order is retained for selected matches. History destination playlists are deduplicated while the archive retains individual plays.
- Imports: JSON only, 20 MB, 500 collections, 20,000 tracks. A plan accepts up to 100 selected collections. Large libraries may take a long time and hit provider quotas. Archives are personal data; keep downloads private.
- **Disconnect & clear data** removes the current browser session’s tokens, imported archive and stored jobs. It does not delete destination playlists or revoke grants at providers. Revoke access in your Spotify/Google account settings. Clearing the browser cookie first can orphan local job records; delete `instance/resonance.sqlite` with the server stopped to purge all local records.
- No telemetry, tracking, streaming, or audio downloads. AI requests happen only when explicitly requested. Do not log request bodies or secrets if adding observability.

## Development

```sh
python -m unittest discover -s tests -v
node --check static/resonance.js
```

The mocked automated suite exercises matching/version penalties, pagination, current Spotify write paths, owner isolation, CSRF/state rejection, token privacy, Spotify AI exclusion, review and transfer, archive export, replay rejection, and ambiguous-write handling. It does not prove live OAuth/provider compatibility. Real account transfers require configured credentials, provider approval and quota. Browser preview availability depends on the runtime.

Architecture: `resonance/providers.py` holds official API adapters; `engine.py` validates archives, scores candidates, and stores job snapshots; `web.py` implements the local OAuth, planning and execution lifecycle. `templates/index.html` and `static/resonance.*` implement the responsive, keyboard-accessible interface. `run.py` is the entry point. Legacy Spotify utility modules remain in `app/` as legacy reference and are not started; their old scheduler/cache behavior is not part of Resonance.

## Delivery tranches

1. OAuth provider adapters, matching, archive handling and transfer engine.
2. Resonance account connection, selection, review and transfer interface.
3. Automated checks, setup guide, privacy/limitations and CI.

Repository: [yegorsokolov/Resonance](https://github.com/yegorsokolov/Resonance). If you have an existing checkout, update its remote:\n\n```sh\ngit remote set-url origin https://github.com/yegorsokolov/Resonance.git\n```

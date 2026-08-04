# Shaw-Spell dictionary daemon (`suggestd`)

Long-lived backing service for the Shaw-Spell web UI. Holds every piece of
loaded state that would otherwise be paid for on each CGI invocation:

- Six dictionary indexes (`{direction}-{dialect}-index.json`)
- Six entry caches (`…-entries.json`)
- Six link-preview summary caches (`…-summaries.json`)
- Four Hunspell dictionaries (`shavian-{gb,us}`, `en_{GB,US}`)

The CGIs (`index.cgi`, `card.cgi`) are thin clients: parse the request, one
JSON round trip over a Unix socket, render the page (or the preview card).

## Files

| File | Purpose |
|---|---|
| `suggestd.py` | The daemon itself. Uses stdlib + `cyhunspell`. |
| `shaw-spell-suggestd.service` | systemd unit. |

## Protocol

Line-oriented JSON over `AF_UNIX`. One request, one response, then close.

```json
→ {"op": "lookup", "dict_type": "english-shavian-gb",
   "word": "dog", "suggest_dict": "en_GB"}
← {"entry_html": "<h1>dog</h1>…", "summary": [{…}], "suggestions": []}
```

`summary` holds one link-preview summary per matched entry, in entry order
(shape: see `extract_summary` in `src/site/build_site_index.py`).

On a miss `entry_html` is `null` and `suggestions` contains Hunspell
corrections filtered against the index (so clicking any suggestion lands
on a real entry).

## Install (Linux + systemd)

The site tarball extracts to a directory containing `site/`,
`site/site-daemon/`, `site/hunspell/`, and `site/site-data/`.

```sh
# Python dep (Debian/Ubuntu)
sudo apt install python3-pip libhunspell-dev
sudo pip3 install hunspell   # pyhunspell — provides `hunspell.HunSpell`
# (or, from a checkout: `sudo pip3 install -r requirements.txt`)

# Install the three pieces the daemon needs. Paths match the systemd unit.
sudo mkdir -p /opt/shaw-spell
sudo cp -r site/site-daemon /opt/shaw-spell/
sudo cp -r site/hunspell    /opt/shaw-spell/
sudo cp -r site/site-data   /opt/shaw-spell/

# Install + enable the systemd unit.
sudo cp /opt/shaw-spell/site-daemon/shaw-spell-suggestd.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now shaw-spell-suggestd.service
sudo systemctl status shaw-spell-suggestd.service
```

The CGI expects the socket at `/run/shaw-spell/suggestd.sock`. Override
with the `SHAW_SPELL_SUGGEST_SOCKET` environment variable.

## Quick check

```sh
printf '%s\n' '{"op":"lookup","dict_type":"english-shavian-gb","word":"dog","suggest_dict":"en_GB"}' \
  | nc -U /run/shaw-spell/suggestd.sock
```

## Restart after a data or dictionary rebuild

The daemon loads everything at startup, so any time you redeploy the site
data (`site-data/`) or the Hunspell dictionaries (`hunspell/`), restart it:

```sh
sudo systemctl restart shaw-spell-suggestd.service
```

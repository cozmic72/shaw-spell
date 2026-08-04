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

`make install-site`, run from a checkout on the server, installs the daemon,
its data and the systemd unit. See `build-rules/site.mk` — it is the authority
on paths and ordering, and it installs `python3-pil` for the card renderer.

Hunspell is the one dependency it cannot install for you:

```sh
sudo apt install libhunspell-dev
sudo pip3 install hunspell   # pyhunspell — provides `hunspell.HunSpell`
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

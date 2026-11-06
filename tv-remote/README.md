# Hisense Remote

Control a Hisense **Android TV / Google TV** from any phone or computer on the same network.
No cloud, no account: the app talks the same protocol as Google's own "Android TV Remote" app
(TLS on ports 6467 for one-time pairing and 6466 for commands), so it works with every Hisense
set that runs Android TV or Google TV.

> Hisense sets running **VIDAA** (not Android) use a different protocol and are not supported.

What you get:

- **Web remote** (`hisense-remote serve`): a dark, phone-sized remote you open in the browser.
  D-pad, power, inputs, volume/channel rockers, media keys, numpad, app shortcuts
  (Netflix, YouTube, Prime Video, Disney+ ...), text entry, long-press support, live power /
  app / volume status, discovery and pairing from the browser, keyboard shortcuts on a computer.
- **CLI** for scripts and automations: `send`, `text`, `app`, `status`, `wake`, `discover`, `pair`.
- **JSON + WebSocket API** so you can wire it into Home Assistant, Stream Deck, shell scripts, etc.
- **Wake-on-LAN** so a fully switched-off TV can be woken.

## Requirements

- Python 3.10 or newer on a computer, Raspberry Pi or NAS on the **same network** as the TV.
- The TV's built-in **Android TV Remote Service** must be enabled (it is by default). If it is not,
  on the TV go to Settings › Apps › See all apps › Show system apps › *Android TV Remote Service* › Enable.
- To wake the TV from fully off you also need Settings › Network & Internet › *Wake on LAN / Network standby*
  (names vary by model) turned on.

## Install

```bash
cd tv-remote
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .                   # installs the `hisense-remote` command
```

(Or without installing: `pip install -r requirements.txt` and use `python -m hisense_remote ...`.)

## Use it from your phone

The remote is a web app, so the phone only needs a browser. Something has to run the small
server on the same network as the TV; pick whichever fits:

| Where the server runs | Works with | How |
|-----------------------|------------|-----|
| A computer, Raspberry Pi, NAS or Docker host that stays on | Android and iPhone | `hisense-remote serve`, then scan the QR code it prints (or open the printed URL) on the phone |
| **The Android phone itself** (no computer needed) | Android | Install [Termux](https://termux.dev) from F-Droid, then run `bash termux-install.sh` (see below) |
| iPhone only, nothing else available | iPhone | iOS cannot run the server; a Raspberry Pi Zero or any always-on box next to the TV is the cheapest option |

Once the page is open on the phone, make it an app:

- **Android (Chrome)**: tap *Install as an app* in the settings panel (gear icon), or Chrome menu › *Add to Home screen*.
- **iPhone / iPad (Safari)**: Share button › *Add to Home Screen*.

It then opens full screen with its own icon, remembers the TV and the access token, and starts
instantly even when the server is briefly unreachable (it reconnects on its own).

### Running it on the Android phone itself (Termux)

Install [Termux](https://termux.dev) (from F-Droid or GitHub, not the outdated Play Store build),
open it and paste this one command. It downloads the project, installs Python and the remote:

```bash
curl -sL https://raw.githubusercontent.com/Sai123-dot/leisung-2035/claude/hisense-tv-remote-control-4hv6r3/tv-remote/termux-install.sh | bash
```

Then:

```bash
hisense-remote pair               # one-time: type the code the TV shows
~/.termux/boot/hisense-remote.sh  # start the remote on this phone
```

Open `http://127.0.0.1:8765/` in Chrome and choose *Add to Home screen*. Tap *Acquire wakelock*
in Termux's notification so Android does not stop it in the background. With the Termux:Boot
add-on installed, the same start script runs automatically after every reboot. To let other
phones in the house use it too, start it with `hisense-remote serve --bind 0.0.0.0` instead.

Discovery via mDNS is often blocked on phones, so if `pair` finds nothing, type the TV's IP
address when asked (Settings › Network & Internet on the TV). The installer uses pure-Python
builds of every package so nothing has to be compiled; if a package still fails to build, run
`pkg install clang` and rerun the command. (This path follows Termux's documented packaging but is
not covered by this repository's automated tests.)

## Quick start

```bash
hisense-remote discover            # lists TVs found via mDNS
hisense-remote pair                # pick the TV, type the code the TV shows -> paired
hisense-remote serve               # web remote on http://<this computer>:8765/
```

`serve` prints the address and a QR code; scan it with the phone's camera (same Wi-Fi) and the
remote opens. Pairing is a one-time step; the client certificate is stored in
`~/.config/hisense-remote/` (override with `--config-dir` or `HISENSE_REMOTE_HOME`).

You can also do everything from the browser: `serve` with no TV configured shows a *Set up*
banner that finds TVs, connects and walks through pairing.

### CLI examples

```bash
hisense-remote send home                       # one key
hisense-remote send up up ok --delay 0.4       # a sequence
hisense-remote send vol+ --direction START_LONG; hisense-remote send vol+ --direction END_LONG
hisense-remote send text:hello                 # type into the focused field
hisense-remote text "the matrix"               # same, as a command
hisense-remote app netflix                     # by name, package id or deep link
hisense-remote app https://www.youtube.com/watch?v=dQw4w9WgXcQ
hisense-remote status                          # power, app, volume, device info
hisense-remote status --json
hisense-remote wake                            # Wake-on-LAN (MAC learned while pairing)
hisense-remote keys                            # all key names and aliases
hisense-remote apps                            # known app package ids
hisense-remote --host 192.168.1.23 send power  # target a specific TV
```

Key names are forgiving: `up`, `ok`, `back`, `home`, `menu`, `vol+`, `vol-`, `mute`, `ch+`, `ch-`,
`play`, `pause`, `playpause`, `stop`, `next`, `prev`, `rew`, `ff`, `input`, `hdmi1`..`hdmi4`,
`tv`, `guide`, `info`, `settings`, `search`, `assist`, `captions`, `red/green/yellow/blue`,
`0`..`9`, `power`, `wake`, `sleep`, or any Android `KEYCODE_*` name with or without the prefix.

### Web server options

```bash
hisense-remote serve --port 8765 --bind 0.0.0.0        # defaults
hisense-remote serve --host 192.168.1.23               # which TV (default: last paired)
hisense-remote serve --token mysecret                  # require a token for the API
hisense-remote serve --demo                            # try the UI against a simulated TV
hisense-remote --no-ime serve                          # if the TV keeps showing a "keyboard" popup
```

Anyone who can reach the server can control the TV, exactly like anyone holding the remote.
On a shared network start it with `--token`. The QR code printed by `serve` (and shown in the
settings panel) already contains the token, so a scanned phone is authorised straight away;
otherwise enter it once in the settings panel (gear icon). It is kept in the browser's local storage.

## HTTP / WebSocket API

All responses are JSON: `{"ok": true, ...}` or `{"ok": false, "error": "<code>", "message": "..."}`.
With `--token`, send `X-Auth-Token: <token>` or `?token=<token>`.

| Method | Path                | Body / query                                   | Notes |
|--------|---------------------|------------------------------------------------|-------|
| GET    | `/api/state`        |                                                | status, power, current app, volume, device |
| POST   | `/api/key`          | `{"key": "home"}` or `{"keys": ["up","ok"], "delay": 0.2}`; optional `"direction": "SHORT\|START_LONG\|END_LONG"` | |
| POST   | `/api/text`         | `{"text": "hello"}`                            | types into the focused field |
| POST   | `/api/app`          | `{"app": "com.netflix.ninja"}` or a deep link  | |
| POST   | `/api/wake`         |                                                | Wake-on-LAN; 409 if the MAC is unknown |
| POST   | `/api/connect`      | `{"host": "192.168.1.23"}`                     | switch TV; state may say `needs_pairing` |
| POST   | `/api/pair/start`   | `{"host": "..."}` (optional)                   | TV shows a code |
| POST   | `/api/pair/finish`  | `{"code": "A1B2C3"}`                           | then connects |
| GET    | `/api/discover`     | `?timeout=4`                                   | mDNS scan |
| GET    | `/api/apps`         |                                                | known apps |
| GET    | `/api/keys`         |                                                | key codes and aliases |
| GET    | `/api/info`         |                                                | server version, addresses, whether a token is required |
| GET    | `/api/qr.svg`       |                                                | QR code of the address phones should open |
| WS     | `/ws`               | send `{"type":"key","key":"ok","direction":"SHORT","id":1}`, `{"type":"text",...}`, `{"type":"app",...}` | pushes `{"type":"state",...}` on every change |

Error codes: `unknown_key`, `bad_request` (400), `needs_pairing` (409), `unreachable` (502),
`not_connected` (503), `pairing_failed` (400), `unauthorized` (401).

Example from a shell:

```bash
curl -s -X POST localhost:8765/api/key -H 'Content-Type: application/json' -d '{"key":"mute"}'
```

## Run it permanently

**systemd** (Linux / Raspberry Pi), `/etc/systemd/system/hisense-remote.service`:

```ini
[Unit]
Description=Hisense TV web remote
After=network-online.target

[Service]
User=pi
ExecStart=/home/pi/leisung-2035/tv-remote/.venv/bin/hisense-remote serve
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**Docker** (host networking is required for mDNS discovery and Wake-on-LAN):

```bash
docker build -t hisense-remote .
docker run -d --name hisense-remote --network host -v hisense-remote:/data hisense-remote
# pair once, interactively:
docker run -it --rm --network host -v hisense-remote:/data hisense-remote pair
```

## Troubleshooting

- **No TVs found** – mDNS is blocked on many guest / mesh networks. Find the IP on the TV under
  Settings › Network & Internet and pair by IP: `hisense-remote pair 192.168.1.23`. Give the TV a
  fixed IP (DHCP reservation) so it does not change.
- **"Needs pairing" after it used to work** – the TV forgot the certificate (factory reset, or you
  removed the device under Settings › Remotes & Accessories). Pair again.
- **Pairing fails straight away** – the Android TV Remote Service app is disabled, or something else
  on the network (another remote app) is mid-pairing. Enable the service, back out of any pairing
  dialog on the TV and retry.
- **Power does nothing when the TV is off** – the TV only listens in network standby. Enable
  *Wake on LAN / Wake on Wireless / Network standby* on the TV and use the *Wake on LAN* button
  (or `hisense-remote wake`). The MAC is learned automatically while pairing.
- **A "Use the keyboard on your mobile device" box keeps appearing** – start with `--no-ime`. The
  current app will then not be reported.
- **Works from the computer but not from the phone** – a firewall is blocking port 8765, or the
  phone is on a different Wi-Fi (guest network / AP isolation).
- **The home-screen app shows an old version** – it caches the page for instant start; pull to
  refresh or reopen it once while the server is reachable and it updates itself.

## Development

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m hisense_remote serve --demo       # exercise the UI without a TV
```

The code lives in `hisense_remote/`: `tv.py` (connection, pairing, commands, Wake-on-LAN),
`server.py` (aiohttp API + WebSocket), `cli.py`, `discovery.py` (zeroconf), `keys.py` (key aliases),
`apps.py` (package ids), `fake.py` (simulated TV) and `static/` (the web UI, including the PWA
manifest, service worker and icons).

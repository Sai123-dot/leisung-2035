#!/data/data/com.termux/files/usr/bin/bash
# Run the Hisense remote on an Android phone itself, inside Termux (https://termux.dev),
# so no computer is needed. Usage, from the tv-remote folder in Termux:
#     bash termux-install.sh
# Afterwards:
#     hisense-remote pair               # one-time, type the code the TV shows
#     hisense-remote serve --bind 127.0.0.1
# then open http://127.0.0.1:8765/ in Chrome and use "Add to Home screen".
set -e
cd "$(dirname "$0")"

pkg update -y
# python-cryptography comes prebuilt from the Termux repo; building it with pip needs Rust.
pkg install -y python python-cryptography
# Use the pure-Python builds of these packages instead of compiling C extensions.
export SKIP_CYTHON=1 AIOHTTP_NO_EXTENSIONS=1 MULTIDICT_NO_EXTENSIONS=1 YARL_NO_EXTENSIONS=1 \
       FROZENLIST_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1
python -m pip install --upgrade pip
python -m pip install --prefer-binary -e .

echo
echo "Installed. Next steps:"
echo "  hisense-remote pair                      # one-time pairing with the TV"
echo "  hisense-remote serve --bind 127.0.0.1    # start the remote on this phone"
echo "Then open http://127.0.0.1:8765/ in Chrome and choose 'Add to Home screen'."
echo "Tip: tap 'Acquire wakelock' in the Termux notification so Android keeps it running."

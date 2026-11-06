#!/data/data/com.termux/files/usr/bin/bash
# Installs the Hisense remote on an Android phone inside Termux (https://termux.dev),
# so the phone itself runs it and no computer is needed.
#
# One command, nothing to download first (paste into Termux):
#   curl -sL https://raw.githubusercontent.com/Sai123-dot/leisung-2035/claude/hisense-tv-remote-control-4hv6r3/tv-remote/termux-install.sh | bash
#
# Or from a checkout of the repository:  bash tv-remote/termux-install.sh
set -e

REPO_URL="${HISENSE_REMOTE_REPO:-https://github.com/Sai123-dot/leisung-2035.git}"
BRANCH="${HISENSE_REMOTE_BRANCH:-claude/hisense-tv-remote-control-4hv6r3}"
CHECKOUT="${HISENSE_REMOTE_CHECKOUT:-$HOME/leisung-2035}"

# Use the pure-Python builds of these packages instead of compiling C extensions
# (no clang or rust needed on the phone).
export SKIP_CYTHON=1 AIOHTTP_NO_EXTENSIONS=1 MULTIDICT_NO_EXTENSIONS=1 YARL_NO_EXTENSIONS=1 \
       FROZENLIST_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1

echo "==> Installing Python, git and the prebuilt cryptography package"
pkg update -y
pkg install -y python python-cryptography git

# Find the project: next to this script when run from a checkout, otherwise download it.
here="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd || true)"
if [ -n "$here" ] && [ -f "$here/pyproject.toml" ] && grep -q 'name = "hisense-remote"' "$here/pyproject.toml"; then
  project="$here"
else
  if [ -d "$CHECKOUT/.git" ]; then
    echo "==> Updating the existing download in $CHECKOUT"
    git -C "$CHECKOUT" pull --ff-only || echo "    (could not update, using the files already there)"
  else
    echo "==> Downloading the remote into $CHECKOUT"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$CHECKOUT"
  fi
  project="$CHECKOUT/tv-remote"
fi

PIP_FLAGS=""
if python -m pip install --help 2>/dev/null | grep -q -- --break-system-packages; then
  PIP_FLAGS="--break-system-packages"
fi
echo "==> Installing the remote and its Python packages (a few minutes on first run)"
python -m pip install $PIP_FLAGS --prefer-binary -e "$project"

# Start script, also used by the Termux:Boot add-on if it is installed.
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/hisense-remote.sh" <<'EOS'
#!/data/data/com.termux/files/usr/bin/sh
# Keeps the phone awake enough to serve the remote, then runs it for this phone only.
# Use --bind 0.0.0.0 instead to let other phones on the Wi-Fi use it too.
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
exec hisense-remote serve --bind 127.0.0.1
EOS
chmod +x "$HOME/.termux/boot/hisense-remote.sh"

echo
echo "Installed. Next steps:"
echo "  hisense-remote pair               # one-time: type the code the TV shows"
echo "  ~/.termux/boot/hisense-remote.sh  # start the remote on this phone"
echo "Then open http://127.0.0.1:8765/ in Chrome and choose 'Add to Home screen'."
echo "Tip: tap 'Acquire wakelock' in the Termux notification so Android keeps it running;"
echo "install the Termux:Boot add-on to start it automatically after a reboot."

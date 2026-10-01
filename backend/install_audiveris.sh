#!/bin/sh
# Installs Audiveris (open-source optical music recognition) for the sheet
# music feature. Audiveris publishes a self-contained .deb per Ubuntu
# release that bundles its own Java runtime. The Ubuntu 22.04 build is the
# one whose dependencies (glibc 2.35, libasound2, ...) all exist on this
# image's Debian bookworm base; the 24.04 build needs t64 packages that
# bookworm doesn't have.
#
# Never fails the image build: if anything here goes wrong, the server
# still deploys, audio/video/links keep working, and PDF/photo uploads
# answer with a clear "not set up" message (see sheet_music.py).
#
# Pin a specific build with: --build-arg AUDIVERIS_DEB_URL=https://...deb

set -u

install() {
  url="${AUDIVERIS_DEB_URL:-}"

  if [ -z "$url" ]; then
    url=$(python - <<'EOF'
import json, urllib.request
try:
    with urllib.request.urlopen("https://api.github.com/repos/Audiveris/audiveris/releases/latest", timeout=30) as r:
        assets = json.load(r).get("assets", [])
    for a in assets:
        name = a.get("name", "")
        if name.endswith(".deb") and "ubuntu22.04" in name and "x86_64" in name:
            print(a["browser_download_url"])
            break
except Exception:
    pass
EOF
)
  fi

  # GitHub's API rate-limits shared build machines. Fall back to the
  # release page redirect to learn the latest tag, then build the asset
  # name from Audiveris's naming pattern.
  if [ -z "$url" ]; then
    tag=$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/Audiveris/audiveris/releases/latest | sed 's#.*/tag/##')
    if [ -n "$tag" ]; then
      ver=$(echo "$tag" | sed 's/^v//')
      url="https://github.com/Audiveris/audiveris/releases/download/${tag}/Audiveris-${ver}-ubuntu22.04-x86_64.deb"
    fi
  fi

  [ -n "$url" ] || { echo "Couldn't find an Audiveris download URL"; return 1; }
  echo "Installing Audiveris from $url"

  curl -fsSL -o /tmp/audiveris.deb "$url" || return 1
  apt-get update || return 1
  apt-get install -y --no-install-recommends /tmp/audiveris.deb || return 1
  rm -f /tmp/audiveris.deb

  bin=$(find /opt -type f -name Audiveris -path '*/bin/*' 2>/dev/null | head -1)
  [ -n "$bin" ] || { echo "Audiveris installed but its launcher wasn't found"; return 1; }
  ln -sf "$bin" /usr/local/bin/audiveris
  echo "Audiveris ready at $bin"
}

if ! install; then
  echo "WARNING: Audiveris install failed. Sheet music scanning (PDF/images) will be unavailable;"
  echo "         MusicXML and MIDI uploads still work."
fi
rm -rf /var/lib/apt/lists/*
exit 0

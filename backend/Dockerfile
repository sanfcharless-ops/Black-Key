FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    curl \
    unzip \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# yt-dlp's YouTube extractor needs a JS runtime to decode video URls —
# without it, extraction fails with "This video is not available."
RUN curl -fsSL https://deno.land/install.sh | sh -s -- -y \
    && mv /root/.deno/bin/deno /usr/local/bin/deno

# Sheet music scanning (PDF/photo -> MusicXML). See the script for why it
# never fails the build.
ARG AUDIVERIS_DEB_URL=""
COPY install_audiveris.sh /tmp/install_audiveris.sh
RUN AUDIVERIS_DEB_URL="$AUDIVERIS_DEB_URL" sh /tmp/install_audiveris.sh
# Audiveris reads text (titles, tempo words) with Tesseract.
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Hugging Face Spaces runs the container as user 1000, not root. Python
# packages go in that user's own folder so they stay writable at runtime:
# the yt-dlp self-upgrade below, and librosa/numba's on-disk function
# cache, both fail on a root-owned site-packages.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .

# - The yt-dlp upgrade on boot: YouTube and TikTok change often enough that
#   a yt-dlp frozen at build time goes stale within weeks, and links
#   silently stop working. It's quick and never blocks startup if it fails.
# - Port 7860 is what Hugging Face expects (see app_port in README.md);
#   hosts that set $PORT themselves (Railway, Render) still work.
# - --proxy-headers: the host terminates HTTPS in front of the app; without
#   this, the app thinks every request came in over plain http.
CMD pip install --no-cache-dir -q --user -U "yt-dlp[default,curl-cffi]" || true; \
    uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860} --proxy-headers --forwarded-allow-ips="*"

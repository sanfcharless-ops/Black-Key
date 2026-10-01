"""
Uploads backend/ to a Hugging Face Docker Space, creating the Space the
first time. Hugging Face rebuilds and restarts it on every upload.

Only needs HF_TOKEN; the account name comes from the token itself, so the
Space ends up at https://huggingface.co/spaces/<you>/keydrops-api and the
API at https://<you>-keydrops-api.hf.space.
"""

import os
import re
import sys

from huggingface_hub import HfApi

token = os.environ.get("HF_TOKEN", "").strip()
if not token:
    sys.exit(
        "HF_TOKEN is missing. Create a token with Write access at "
        "https://huggingface.co/settings/tokens and save it in this GitHub repo under "
        "Settings -> Secrets and variables -> Actions -> New repository secret, named HF_TOKEN."
    )

api = HfApi(token=token)
owner = api.whoami()["name"]
space_name = os.environ.get("HF_SPACE_NAME", "").strip() or "keydrops-api"
repo_id = f"{owner}/{space_name}"

# Public on purpose: the website calls this API straight from visitors'
# browsers, which can't send a private Space's token.
api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=False, exist_ok=True)

sha = os.environ.get("GITHUB_SHA", "")[:7]
api.upload_folder(
    folder_path="backend",
    repo_id=repo_id,
    repo_type="space",
    commit_message=f"Deploy {sha}" if sha else "Deploy",
    ignore_patterns=["__pycache__/*", "*.pyc", "venv*/*"],
)

subdomain = re.sub(r"[^a-z0-9]+", "-", repo_id.lower()).strip("-")
space_url = f"https://huggingface.co/spaces/{repo_id}"
api_url = f"https://{subdomain}.hf.space"
summary = (
    f"Uploaded to {space_url}\n\n"
    f"API URL for frontend/index.html: {api_url}\n\n"
    "The Space now rebuilds; the first build takes several minutes. Watch it under the Space's Logs tab."
)
print(summary)
step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
if step_summary:
    with open(step_summary, "a") as f:
        f.write(summary + "\n")

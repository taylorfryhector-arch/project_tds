# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests",
# ]
# ///

import requests
import base64
import random

# Generate a seed for uniqueness
seed = random.randint(1000, 9999)

# Optional: example placeholder for markdown/content (not strictly needed here)
# content = f"GitHub User Fetcher Seed: {seed}"

# Base64 encoding is not strictly needed here but keeping consistent pattern
seed_str = str(seed)
seed_base64 = base64.b64encode(seed_str.encode("utf-8")).decode()

# Construct payload for Round 1
payload = {
    "email": "student@example.com",
    "secret": "praneetha",
    "task": "github-user-created",
    "round": 1,
    "nonce": f"unique-nonce-{seed}",
    "brief": f"Publish a Bootstrap page with form id='github-user-{seed}' that fetches a GitHub username, optionally uses ?token=, and displays the account creation date in YYYY-MM-DD UTC inside #github-created-at.",
    "evaluation_url": "https://webhook.site/your-webhook-url",  # replace with your actual URL
    "attachments": [],
    "checks": [
        {"js": f'document.querySelector("#github-user-{seed}").tagName === "FORM"'},
        {"js": 'document.querySelector("#github-created-at").textContent.includes("20")'},
        {"js": 'document.querySelector("script").textContent.includes("https://api.github.com/users/")'}
    ]
}

# Hugging Face Space endpoint
HF_API_URL = "https://taylorfry-projectds.hf.space/handle_request"

# Send the request
try:
    response = requests.post(HF_API_URL, json=payload, timeout=30)
    print("Status Code:", response.status_code)
    if response.headers.get('content-type') == 'application/json':
        print("Response JSON:", response.json())
    else:
        print("Response Text:", response.text)
except Exception as e:
    print("Error sending request:", e)

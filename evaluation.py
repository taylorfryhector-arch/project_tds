# Fixed Python Script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests",
# ]
# ///

import requests
import base64
import os

# ----------------------
# Load sample captcha
# ----------------------
file_path = "text_image.png"
if not os.path.exists(file_path):
    raise FileNotFoundError(f"{file_path} not found.")

with open(file_path, "rb") as f:
    file_bytes = f.read()

captcha_base64 = base64.b64encode(file_bytes).decode()

# ----------------------
# Payload
# ----------------------
payload = {
    "email": "student@example.com",
    "secret": "praneetha",
    "task": "captcha-solver-demo-318",
    "round": 1,
    "nonce": "ab123-nonce-teste",
    "brief": (
        "Create a captcha solver web app that takes ?url=https://example.com/captcha.png "
        "as a query parameter and displays both the image and its solved text. "
        "If no URL is given, use the attached sample captcha image."
    ),
    "evaluation_url": "https://webhook.site/21c9e554-87bf-48a4-8220-9101bad7f00f",
    "attachments": [
        {
            "name": "captcha.png",
            "url": f"data:image/png;base64,{captcha_base64}"
        }
    ]
}

# ----------------------
# FIXED: Correct URL without /api/
# ----------------------
HF_API_URL = "https://taylorfry-projectds.hf.space/handle_request"

try:
    response = requests.post(HF_API_URL, json=payload, timeout=30)
    print("Status Code:", response.status_code)
    print("Response:", response.json() if response.headers.get('content-type') == 'application/json' else response.text)
except Exception as e:
    print("Error:", e)
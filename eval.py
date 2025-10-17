# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests",
# ]
# ///
import requests
import base64
import os

# Read the same sample captcha PNG for attachment
file_path = "text_image.png"
if not os.path.exists(file_path):
    raise FileNotFoundError(f"{file_path} not found. Please place your sample captcha PNG in the script folder.")

with open(file_path, "rb") as f:
    file_bytes = f.read()

captcha_base64 = base64.b64encode(file_bytes).decode()  # full Base64

def task_round2():
    payload = {
        "email": "student@example.com",
        "secret": "praneetha",
        "task": "captcha-solver-demo-318",  # same repo/task name
        "round": 2,
        "nonce": "abc123-round2-nonce",
        "brief": (
            "Update the existing captcha solver web app to improve accuracy "
            "and allow users to submit multiple captcha URLs via ?url=...&url=... "
            "The page should display all images and solved texts. "
            "If no URL is given, use the attached sample captcha image."
        ),
        "checks": [
            "Repo has MIT license",
            "README.md updated to describe new multi-captcha feature",
            "Web page displays all captcha URLs passed as query parameters",
            "Captcha solving remains under 15 seconds per image",
            "No secrets or credentials are committed to git history"
        ],
        "evaluation_url": "https://webhook.site/21c9e554-87bf-48a4-8220-9101bad7f00f",
        "attachments": [
            {
                "name": "captcha.png",
                "url": f"data:image/png;base64,{captcha_base64}"
            }
        ]
    }

    response = requests.post("https://taylorfry-projectds.hf.space/handle_request", json=payload)
    print("Status Code:", response.status_code)
    try:
        print("Response JSON:", response.json())
    except Exception:
        print("Response Text:", response.text)


if __name__ == "__main__":
    task_round2()

# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fastapi[standard]",
#   "uvicorn",
#   "httpx",
# ]
# ///

from fastapi import FastAPI
import os, json, base64, asyncio, re, httpx

app = FastAPI()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ----------------------
# Helpers
# ----------------------

def validate_secret(secret: str) -> bool:
    return secret == os.getenv("secret")

import re, json

def safe_json_parse(content):
    """Robustly extract and parse JSON from LLM output."""
    if isinstance(content, dict):
        return content

    content = str(content).strip()

    # Remove common markdown fences like ```json ... ```
    content = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", content, flags=re.MULTILINE).strip()

    # Extract first JSON-like block (curly braces)
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        content = match.group(0)

    # Try parsing safely
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        # Attempt to repair malformed JSON
        fixed = content.replace("\\n", "\\\\n").replace("\\", "\\\\").replace("\r", "")
        try:
            return json.loads(fixed)
        except Exception:
            print(f"⚠️ JSON parse failed: {e}")
            print(f"Raw output (truncated): {content[:500]}...")
            # Fallback — return the text so workflow doesn't crash
            return {"README.md": content}
        
import re

def attachment_to_gemini_part(attachment: dict) -> dict | None:
    """
    Converts a single attachment dict into a Gemini API 'inlineData' part.
    Expects attachment = {"name": "file.png", "url": "data:image/png;base64,..."}
    Returns None if invalid or non-image.
    """
    data_uri = attachment.get("url")
    if not data_uri or not isinstance(data_uri, str):
        return None

    if not is_image_data_uri(data_uri):
        return None

    try:
        # Strip prefix and extract only base64 content
        base64_data = data_uri.split("base64,")[-1].replace("\n", "").replace("\r", "").strip()

        # Validate it's proper Base64
        import base64
        try:
            decoded_bytes = base64.b64decode(base64_data, validate=True)
        except Exception:
            print(f"⚠️ Invalid Base64 for attachment {attachment.get('name')}")
            return None

        mime_type = re.match(r"data:(?P<mime>[^;]+);base64,", data_uri).group("mime")
        return {
            "inlineData": {
                "data": base64_data,
                "mimeType": mime_type
            }
        }

    except Exception as e:
        print(f"Error processing attachment {attachment.get('name')}: {e}")
        return None


def is_image_data_uri(data_uri: str) -> bool:
    """
    Checks if a Data URI string represents an image.
    Returns True if the MIME type starts with 'image/'.
    """
    if not isinstance(data_uri, str) or not data_uri.startswith("data:"):
        return False
    return bool(re.match(r"data:image/[^;]+;base64,", data_uri, re.IGNORECASE))


# --- Example usage ---





GITHUB_USER = "taylorfryhector-arch"
GITHUB_TOKEN = "YOUR_GITHUB_TOKEN"

async def create_github_repo(repo_name: str):
    """
    Creates a new GitHub repository under the configured user.
    """
    url = f"https://api.github.com/user/repos"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    data = {
        "name": repo_name,
        "private": False,
        "auto_init": True,
        "license_template": "mit"
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=data, headers=headers)
        if resp.status_code not in [200, 201]:
            raise Exception(f"Failed to create repo: {resp.text}")
        return resp.json()



def save_files_locally(repo_name, project_files, attachments=None):
    """
    Saves project files and attachments into a local directory.
    
    project_files: dict {filename: content as string}
    attachments: list of dicts with keys: 'name', 'url' (data URI)
    """
    local_path = f"/tmp/{repo_name}"
    os.makedirs(local_path, exist_ok=True)

    # 1️⃣ Save project files (text)
    for filename, content in project_files.items():
        file_path = os.path.join(local_path, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

    # 2️⃣ Save attachments (binary)
    if attachments:
        for attachment in attachments:
            filename = attachment.get("name")
            data_uri = attachment.get("url")
            if not filename or not data_uri or not data_uri.startswith("data:"):
                continue

            # Extract base64 data
            match = re.search(r"base64,(.*)", data_uri, re.I)
            if not match:
                continue

            file_bytes = base64.b64decode(match.group(1))
            file_path = os.path.join(local_path, filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "wb") as f:
                f.write(file_bytes)

    return local_path


# ----------------------
# LLM Call
# ----------------------

import asyncio
import httpx
import json
import os


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


async def write_code_llm(data: dict, response_schema=None) -> dict:
    task_id = data.get("task")
    round_index = data.get("round", 1)
    brief = data.get("brief", "")
    attachments = data.get("attachments", [])

    image_parts = [attachment_to_gemini_part(att) for att in attachments if is_image_data_uri(att.get("url", ""))]
    image_parts = [p for p in image_parts if p]

    attachment_names = [att.get("name") for att in attachments if att.get("name")]
    attachment_list_str = ", ".join(attachment_names)

    # Construct prompt
    if round_index > 1:
        prompt = f"UPDATE (ROUND {round_index}): Modify existing files according to brief: '{brief}'. Provide full replacements."
    else:
        prompt = f"Generate a complete solution for: {brief}."

    if attachment_list_str:
        prompt += f" Available attachments: {attachment_list_str}. Reference them correctly."

    system_prompt = "You are an expert developer. Output strictly as JSON with required files."

    if response_schema is None:
        response_schema = {
            "type": "object",
            "properties": {"index.html": {"type": "string"}, "README.md": {"type": "string"}, "LICENSE": {"type": "string"}},
            "required": ["index.html", "README.md", "LICENSE"]
        }

    contents = [{"parts": (image_parts if image_parts else []) + [{"text": prompt}]}]
    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": response_schema, "temperature": 0},
    }

    max_retries = 3
    base_delay = 1
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
                resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                resp.raise_for_status()
                result = resp.json()
                parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                full_text = "".join([p.get("text", "") for p in parts])
                return safe_json_parse(full_text)
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(base_delay * (2 ** attempt))
            else:
                raise Exception(f"LLM generation failed: {e}")

# ----------------------
# GitHub Push
# ----------------------

async def push_files_to_repo(repo_name, local_path):
    repo_api = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}/contents"
    commit_sha = None

    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
        for root, _, files in os.walk(local_path):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, local_path)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = base64.b64encode(f.read().encode()).decode()

                # Get previous file SHA (to update instead of creating new)
                file_resp = await client.get(f"{repo_api}/{rel_path}", headers=headers)
                prev_sha = file_resp.json().get("sha") if file_resp.status_code == 200 else None

                payload = {
                    "message": f"Round 2 update for {file}",
                    "content": content,
                    "sha": prev_sha
                }

                resp = await client.put(f"{repo_api}/{rel_path}", headers=headers, json=payload)
                if resp.status_code in [200, 201]:
                    commit_sha = resp.json()["commit"]["sha"]

    return commit_sha

# ----------------------
# GitHub Pages Deployment
# ----------------------

import asyncio
import httpx
import os

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

async def deploy_github_pages(repo_name: str) -> str:
    github_user = "taylorfryhector-arch"
    api_url = f"https://api.github.com/repos/{github_user}/{repo_name}/pages"
    payload = {"source": {"branch": "main", "path": "/"}, "build_type": "legacy"}
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    async with httpx.AsyncClient(timeout=60) as client:
        # Step 1: Try enabling Pages via API
        for attempt in range(10):
            try:
                get_resp = await client.get(api_url, headers=headers)

                if get_resp.status_code == 404:
                    resp = await client.post(api_url, json=payload, headers=headers)
                elif get_resp.status_code == 200:
                    resp = await client.patch(api_url, json=payload, headers=headers)
                else:
                    get_resp.raise_for_status()
                    resp = get_resp

                if resp.status_code in (200, 201):
                    print(f"✅ GitHub Pages setup initiated (attempt {attempt + 1})")
                    break
                elif resp.status_code == 409:
                    print(f"⚠️ Conflict on attempt {attempt + 1}, retrying in 5s...")
                    await asyncio.sleep(5)
                else:
                    resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                print(f"HTTP error on attempt {attempt + 1}: {e}")
                await asyncio.sleep(5)
        else:
            print("⚠️ API did not return success, but GitHub may still deploy Pages eventually.")

        # Step 2: Poll the actual page URL until it responds
        pages_url = f"https://{github_user}.github.io/{repo_name}/"
        for poll_attempt in range(30):  # 30 * 5s = 150s max
            try:
                r = await client.get(pages_url)
                if r.status_code == 200:
                    print(f"🚀 GitHub Pages live at: {pages_url}")
                    return pages_url
            except Exception:
                pass
            await asyncio.sleep(5)

    raise Exception(f"❌ GitHub Pages not reachable after 150 seconds: {pages_url}")


# ----------------------
# Evaluation POST
# ----------------------

async def post_evaluation(evaluation_url, payload):
    async with httpx.AsyncClient() as client:
        delay = 1
        for _ in range(6):
            try:
                resp = await client.post(evaluation_url, json=payload, headers={"Content-Type": "application/json"})
                if resp.status_code == 200:
                    return
            except Exception:
                pass
            await asyncio.sleep(delay)
            delay *= 2
        print("Failed to POST evaluation after retries.")


async def round1_task(data: dict):
    try:
        repo_name = f"{data['task']}"

        print("🧠 Generating code with LLM...")
        project_files = await write_code_llm(data)

        print("💾 Saving files locally...")
        local_path = save_files_locally(repo_name, project_files)

        print("📦 Creating GitHub repository...")
        repo_info = await create_github_repo(repo_name)

        print("🚀 Pushing files to GitHub...")
        last_commit_sha = await push_files_to_repo(repo_name, local_path)
        await asyncio.sleep(25)  # Wait a bit for GitHub to process

        print("🌐 Enabling GitHub Pages...")
        pages_url = await deploy_github_pages(repo_name)

        evaluation_payload = {
            "email": data["email"],
            "task": data["task"],
            "round": data["round"],
            "nonce": data["nonce"],
            "repo_url": repo_info["html_url"],
            "commit_sha": last_commit_sha,
            "pages_url": pages_url
        }

        print("📨 Sending evaluation...")
        await post_evaluation(data["evaluation_url"], evaluation_payload)

        print("✅ Round1 complete!")
    except Exception as e:
        print("Error in round1_task:", str(e))
        
#round 2 placeholder
async def round2_task(data: dict):
    try:
        # Same task ID as Round 1
        repo_name = f"{data['task']}"
        github_user = "taylorfryhector-arch"

        print(f"🔁 Round 2: Modifying repo {repo_name}...")

        # (1) Get existing files from GitHub
        async with httpx.AsyncClient() as client:
            repo_api = f"https://api.github.com/repos/{github_user}/{repo_name}/contents"
            resp = await client.get(repo_api, headers={"Authorization": f"Bearer {GITHUB_TOKEN}"})
            repo_files = {}
            for file in resp.json():
                if file["type"] == "file":
                    content_resp = await client.get(file["download_url"])
                    repo_files[file["name"]] = content_resp.text

        # (2) Generate improved code
        data["existing_files"] = repo_files  # pass to LLM
        new_files = await write_code_llm(data, max_retries=3)

        # (3) Save + push modified files
        local_path = save_files_locally(repo_name, new_files)
        commit_sha=await push_files_to_repo(repo_name, local_path)
        await asyncio.sleep(25)

        # (4) Redeploy GitHub Pages
        pages_url = await deploy_github_pages(repo_name)

        # (5) Send evaluation
        evaluation_payload = {
            "email": data["email"],
            "task": data["task"],
            "round": data["round"],
            "nonce": data["nonce"],
            "repo_url" : f"https://github.com/{github_user}/{repo_name}",
            "commit_sha": commit_sha,  # or actual sha
            "pages_url": pages_url
        }

        await post_evaluation(data["evaluation_url"], evaluation_payload)
        print("✅ Round 2 complete!")

    except Exception as e:
        print(f"❌ Error in round2_task: {e}")


# ----------------------
# FastAPI endpoint
# ----------------------

@app.post("/handle_request")
async def handle_request(data: dict):
    if not validate_secret(data.get("secret", "")):
        return {"status": "error", "message": "Invalid secret"}
    round_number = data.get("round", 1)

    if round_number == 1:
        asyncio.create_task(round1_task(data))
    elif round_number == 2:
        asyncio.create_task(round2_task(data))
    else:
        return {"status": "error", "message": f"Unknown round: {round_number}"}
    
    return {"status": "ok", "message": "Processing started in background"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

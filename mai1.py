# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fastapi[standard]",
#   "uvicorn",
#   "httpx",
#   "aiofiles",
#   "gradio",
# ]
# ///

from fastapi import FastAPI
import os, json, base64, asyncio, re, httpx, aiofiles,urllib.parse,traceback,subprocess
app = FastAPI()

# ----------------------
# Config
# ----------------------
GITHUB_USER = "taylorfryhector-arch"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
OPENAI_API_KEY = os.getenv("OPEN_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://aipipe.org/openrouter/v1/chat/completions")
SECRET_KEY = os.getenv("secret")

# ----------------------
# Helpers
# ----------------------
def validate_secret(secret: str) -> bool:
    return secret == SECRET_KEY


async def detect_attachment_type(att):
    """Detects type of attachment based on filename or MIME."""
    name = att.get("name", "")
    url = att.get("url", "")
    if name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg")):
        return "image"
    elif name.lower().endswith(".csv"):
        return "csv"
    elif name.lower().endswith(".json"):
        return "json"
    elif name.lower().endswith((".mp3", ".wav", ".ogg", ".flac", ".m4a")):
        return "audio"
    else:
        return "text"


async def save_files_locally(repo_name, project_files, attachments=None):
    """
    Save project files and attachments to /tmp/{repo_name}.
    Handles:
    - Text files (UTF-8)
    - Binary files (images/audio/base64)
    - Remote attachments (via URL)
    Returns:
        local_path: str
        saved_attachments: list of file paths
    """
    local_path = f"/tmp/{repo_name}"
    os.makedirs(local_path, exist_ok=True)
    saved_attachments = []

    # ---------------------- Save project files ----------------------
    for filename, content in project_files.items():
        file_path = os.path.join(local_path, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        if isinstance(content, str) and content.startswith("data:") and "base64," in content:
            # Base64 data URI
            match = re.search(r"base64,(.*)", content, re.I)
            if match:
                file_bytes = base64.b64decode(match.group(1))
                async with aiofiles.open(file_path, "wb") as f:
                    await f.write(file_bytes)
        else:
            # Text file
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(content)

    # ---------------------- Save attachments ----------------------
    if attachments:
        for att in attachments:
            name = att.get("name", "unknown")
            url_or_data = att.get("url", "")

            file_path = os.path.join(local_path, name)
            try:
                if url_or_data.startswith("data:") and "base64," in url_or_data:
                    match = re.search(r"base64,(.*)", url_or_data, re.I)
                    if match:
                        file_bytes = base64.b64decode(match.group(1))
                        async with aiofiles.open(file_path, "wb") as f:
                            await f.write(file_bytes)
                elif url_or_data.startswith("http://") or url_or_data.startswith("https://"):
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(url_or_data)
                        resp.raise_for_status()
                        async with aiofiles.open(file_path, "wb") as f:
                            await f.write(resp.content)
                else:
                    print(f"⚠️ Skipping unknown attachment format: {name}")
                    continue

                saved_attachments.append(file_path)
            except Exception as e:
                print(f"⚠️ Failed to save attachment {name}: {e}")

    return local_path, saved_attachments



def clean_json_response(text: str):
    """Strip Markdown code fences and safely parse JSON."""
    try:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        return json.loads(cleaned)
    except Exception:
        return None

async def write_code_llm(data: dict) -> list:
    """
    Fast LLM code generation with retries:
    - Only sends brief + minimal attachment info
    - Retries up to 3 times on network/DNS errors
    - Returns all essential project files quickly
    """
    brief = data.get("brief", "")
    round_index = data.get("round", 1)
    attachments = data.get("attachments", [])
    existing_files = data.get("existing_files", {})

    # -------------------------------
    # Prepare minimal attachment info in parallel
    # -------------------------------
    if attachments:
        results = await asyncio.gather(*(detect_attachment_type(att) for att in attachments))
        attachment_info = [
            f"{att['name']} ({typ})" for att, typ in zip(attachments, results) if att.get("name")
        ]
        attachment_list_str = ", ".join(attachment_info)
    else:
        attachment_list_str = ""

    # -------------------------------
    # Build prompt
    # -------------------------------
    if round_index == 1:
        user_prompt = f"Generate essential project files for this task:\n{brief}"
    else:
        # Only send first 5 existing files for speed
        existing_files_list = list(existing_files.keys())[:5]
        user_prompt = f"Update existing project with this brief:\n{brief}\nExisting files: {existing_files_list}"

    if attachment_list_str:
        user_prompt += f"\nAttachments available: {attachment_list_str}"

    system_prompt = (
        "You are an expert full-stack developer. "
        "Return a JSON array of objects with 'filename' and 'content'. "
        "Include at least: index.html, README.md, LICENSE. "
        "README.md summarizes the app, setup, usage. LICENSE is MIT. "
        "Do not include unnecessary text outside JSON."
    )

    payload = {
        "model": "gpt-4.1-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }

    # -------------------------------
    # Send request to LLM with retries
    # -------------------------------
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    OPENAI_BASE_URL,
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )
                resp.raise_for_status()
                result = resp.json()
                text = result["choices"][0]["message"]["content"]

                files = clean_json_response(text)
                if not isinstance(files, list):
                    raise ValueError("Invalid JSON output from LLM")

                # -------------------------------
                # Ensure mandatory files exist
                # -------------------------------
                mandatory = {
                    "index.html": "<!DOCTYPE html><html><body>Error</body></html>",
                    "README.md": "Project generated by LLM.",
                    "LICENSE": "MIT License"
                }
                existing_filenames = [f["filename"] for f in files]
                for fname, content in mandatory.items():
                    if fname not in existing_filenames:
                        files.append({"filename": fname, "content": content})

                # Return all files (do NOT filter out CSS/JS/images)
                return files

        except httpx.ConnectError as e:
            print(f"⚠️ Network/DNS error on attempt {attempt+1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(3)
            else:
                raise Exception(f"LLM generation failed after {max_retries} attempts: {e}")
        except Exception as e:
            raise Exception(f"LLM generation failed: {e}")




# GitHub Repo + Push
# ----------------------
async def create_github_repo(repo_name: str):
    url = f"https://api.github.com/user/repos"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    data = {"name": repo_name, "private": False, "auto_init": True, "license_template": "mit"}

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=data, headers=headers)
        if resp.status_code not in [200, 201]:
            raise Exception(f"Failed to create repo: {resp.text}")
        return resp.json()

async def push_files_to_repo(repo_name: str, local_path: str):
    """
    Push all files from local_path to GitHub repo using API.
    Ensures all files are Base64-encoded (required by GitHub API).
    Returns last commit SHA.
    """
    repo_api = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}/contents"
    commit_sha = None

    async with httpx.AsyncClient() as client:
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }

        for root, _, files in os.walk(local_path):
            for file in files:
                if file.startswith(".") or file.lower() in ("thumbs.db",):
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, local_path).replace("\\", "/")
                rel_path_encoded = urllib.parse.quote(rel_path)

                try:
                    # Read file as bytes
                    with open(file_path, "rb") as f:
                        content_bytes = f.read()

                    # Encode all files as Base64
                    content_b64 = base64.b64encode(content_bytes).decode()

                    # Check if file exists to get previous SHA
                    prev_sha = None
                    resp = await client.get(f"{repo_api}/{rel_path_encoded}", headers=headers)
                    if resp.status_code == 200:
                        prev_sha = resp.json().get("sha")

                    payload = {
                        "message": f"{'Create' if prev_sha is None else 'Update'} {rel_path}",
                        "content": content_b64
                    }
                    if prev_sha:
                        payload["sha"] = prev_sha

                    resp = await client.put(f"{repo_api}/{rel_path_encoded}", headers=headers, json=payload)
                    if resp.status_code in [200, 201]:
                        commit_sha = resp.json()["commit"]["sha"]
                        print(f"✅ {'Created' if prev_sha is None else 'Updated'}: {rel_path}")
                    else:
                        print(f"⚠️ Failed to upload {rel_path}: {resp.status_code} {resp.text[:100]}")
                except Exception as e:
                    print(f"⚠️ Error uploading {rel_path}: {e}")

    return commit_sha



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

        # Step 2: Poll the actual page URL for up to 3 minutes
        pages_url = f"https://{github_user}.github.io/{repo_name}/"
        for poll_attempt in range(30):  # 36 × 5s = ~3 minutes
            try:
                r = await client.get(pages_url)
                if r.status_code == 200:
                    print(f"🚀 GitHub Pages live at: {pages_url}")
                    return pages_url
            except Exception:
                pass
            await asyncio.sleep(5)

    # Timeout reached, return URL anyway
    print(f"⚠️ Timeout reached. Returning Pages URL anyway: {pages_url}")
    return pages_url



import asyncio, traceback

async def round1_task(data: dict):
    repo_name = data.get("task", "untitled-project")
    attachments = data.get("attachments", [])

    try:
        print("🧠 Generating code with LLM...")
        project_files = await write_code_llm(data)

        # Normalize project files
        if isinstance(project_files, dict):
            project_files_list = [{"filename": k, "content": v} for k, v in project_files.items()]
        elif isinstance(project_files, list):
            project_files_list = project_files
        else:
            raise TypeError(f"Unexpected project_files type: {type(project_files)}")

        project_files_dict = {f['filename']: f['content'] for f in project_files_list}

        print("💾 Saving files locally...")
        local_path, saved_attachments = await save_files_locally(repo_name, project_files_dict, attachments)

        print("📦 Creating GitHub repository...")
        repo_info = await create_github_repo(repo_name)

        print("🚀 Pushing files to GitHub...")
        last_commit_sha = await push_files_to_repo(repo_name, local_path)

        print("⏳ Waiting for GitHub to sync...")
        await asyncio.sleep(40)  # More stable delay before deployment

        print("🌐 Enabling GitHub Pages...")
        pages_url = await deploy_github_pages(repo_name)

        evaluation_payload = {
            "email": data.get("email"),
            "task": data.get("task"),
            "round": data.get("round"),
            "nonce": data.get("nonce"),
            "repo_url": repo_info.get("html_url"),
            "commit_sha": last_commit_sha,
            "pages_url": pages_url
        }

        print("📨 Sending evaluation payload...")
        try:
            await post_evaluation(data["evaluation_url"], evaluation_payload)
        except Exception as e:
            print(f"⚠️ Evaluation submission failed: {e}")

        print("✅ Round 1 complete!")

    except Exception as e:
        print(f"❌ Error in round1_task: {e}")
        print(traceback.format_exc())

        


def run_cmd(cmd, cwd=None):
    """Run a shell command safely with error handling."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return result.stdout.decode().strip()
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Command failed: {' '.join(cmd)}")
        if e.stderr:
            print("stderr:", e.stderr.decode(errors="ignore"))
        raise

# ----------------------------
# Round 2 main task
# ----------------------------
async def round2_task(data: dict):
    try:
        repo_name = f"{data['task']}"
        github_user = GITHUB_USER
        repo_url = f"https://{GITHUB_USER}:{GITHUB_TOKEN}@github.com/{github_user}/{repo_name}.git"

        print(f"🔁 Round 2: Cloning repo {repo_name}...")

        # ---------------------- (1) Clone repo locally ----------------------
        local_path = f"/tmp/{repo_name}"
        if os.path.exists(local_path):
            run_cmd(["rm", "-rf", local_path])
        run_cmd(["git", "clone", repo_url, local_path])

        # ---------------------- (2) Read existing files ----------------------
        text_extensions = {".txt", ".md", ".py", ".html", ".json", ".csv", ".js", ".css"}
        existing_files = {}

        for root, _, files in os.walk(local_path):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, local_path)
                ext = os.path.splitext(file)[1].lower()
                try:
                    if ext in text_extensions:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                    else:
                        with open(file_path, "rb") as f:
                            content = "data:application/octet-stream;base64," + base64.b64encode(f.read()).decode()
                    existing_files[rel_path] = content
                except Exception as fe:
                    print(f"⚠️ Skipping unreadable file: {file_path} ({fe})")

        # ---------------------- (3) Generate updated project via LLM ----------------------
        data["existing_files"] = existing_files
        result = await write_code_llm(data)

        if isinstance(result, dict):
            new_files_list = [{"filename": k, "content": v} for k, v in result.items()]
        elif isinstance(result, list):
            new_files_list = result
        else:
            raise TypeError(f"Unexpected return type from write_code_llm: {type(result)}")

        new_files_dict = {f["filename"]: f["content"] for f in new_files_list}
        
        print("💾 Saving updated files locally...")
        await save_files_locally(repo_name, new_files_dict)  # your helper handles writing

        # ---------------------- (4) Commit & Push updates ----------------------
        print("📤 Committing and pushing updates to GitHub...")
        run_cmd(["git", "add", "."], cwd=local_path)

        diff_check = subprocess.run(["git", "diff", "--staged", "--quiet"], cwd=local_path)
        if diff_check.returncode != 0:
            run_cmd(["git", "config", "user.email", "llm@autogen.com"], cwd=local_path)
            run_cmd(["git", "config", "user.name", "Auto LLM Bot"], cwd=local_path)
            run_cmd(["git", "commit", "-m", "Round 2 update from LLM"], cwd=local_path)

            branches = run_cmd(["git", "branch", "-r"], cwd=local_path)
            default_branch = "main" if "origin/main" in branches else "master"
            run_cmd(["git", "push", "origin", default_branch, "--force"], cwd=local_path)
        else:
            print("⚠️ No changes detected; skipping commit and push.")

        # ---------------------- (5) Get last commit SHA ----------------------
        commit_sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=local_path)

        # ---------------------- (6) Deploy GitHub Pages ----------------------
        await asyncio.sleep(15)  # Allow time for GitHub to register commit
        print("🌐 Deploying GitHub Pages...")
        pages_url = await deploy_github_pages(repo_name)

        # ---------------------- (7) Send evaluation ----------------------
        evaluation_payload = {
            "email": data["email"],
            "task": data["task"],
            "round": data["round"],
            "nonce": data["nonce"],
            "repo_url": f"https://github.com/{github_user}/{repo_name}",
            "commit_sha": commit_sha,
            "pages_url": pages_url,
        }

        await post_evaluation(data["evaluation_url"], evaluation_payload)
        print(f"✅ Round 2 complete! Repo: {evaluation_payload['repo_url']} Pages: {pages_url} Commit: {commit_sha}")

    except Exception as e:
        print(f"❌ Error in round2_task: {e}")

# ----------------------
# FastAPI Endpoint
# ----------------------
# Use asyncio.create_task safely
@app.post("/handle_request")
async def handle_request(data: dict):
    if not validate_secret(data.get("secret", "")):
        return {"status": "error", "message": "Invalid secret"}
    round_number = data.get("round", 1)
    try:
        if round_number == 1:
            asyncio.create_task(round1_task(data))
        elif round_number == 2:
            asyncio.create_task(round2_task(data))
        else:
            return {"status": "error", "message": f"Unknown round: {round_number}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to start task: {e}"}
    return {"status": "ok", "message": "Processing started in background"}

@app.get("/")
async def root():
    return {"status": "ok", "message": "LLM task runner is liv!"}


import gradio as gr
from fastapi.middleware.wsgi import WSGIMiddleware

# Minimal Gradio interface
iface = gr.Interface(fn=lambda: "LLM Task Runner Live!", inputs=[], outputs="text")

# Mount Gradio app under /api (so Space root still works)
app.mount("/api", WSGIMiddleware(iface.app))
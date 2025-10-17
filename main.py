# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fastapi[standard]",
#   "uvicorn",
#   "httpx",
#   "aiofiles",
#   "gradio>=4.0.0",
# ]
# ///

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os, json, base64, asyncio, re, httpx, aiofiles, urllib.parse, traceback, subprocess, shutil
import gradio as gr

# ----------------------
# Config
# ----------------------
GITHUB_USER = "taylorfryhector-arch"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
OPENAI_API_KEY = os.getenv("OPEN_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://aipipe.org/openrouter/v1/chat/completions")
SECRET_KEY = os.getenv("secret")

# ----------------------
# Initialize FastAPI FIRST
# ----------------------
app = FastAPI(
    title="LLM Task Runner API",
    description="API for handling LLM-based code generation tasks",
    version="1.0.0"
)

# Add CORS middleware if needed
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------
# Helpers (keep all your existing helper functions)
# ----------------------
def validate_secret(secret: str) -> bool:
    return secret == SECRET_KEY

async def detect_attachment_type(att):
    """Detects type of attachment based on filename or MIME."""
    name = att.get("name", "").lower()

    if name.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg")):
        return "image"
    elif name.endswith(".csv"):
        return "csv"
    elif name.endswith(".json"):
        return "json"
    elif name.endswith((".mp3", ".wav", ".ogg", ".flac", ".m4a")):
        return "audio"
    elif name.endswith(".html"):
        return "html"
    elif name.endswith(".css"):
        return "css"
    elif name.endswith(".js"):
        return "javascript"
    else:
        return "text"


async def save_files_locally(repo_name, project_files, attachments=None):
    """Save project files and attachments to /tmp/{repo_name}."""
    local_path = f"/tmp/{repo_name}"
    os.makedirs(local_path, exist_ok=True)
    saved_attachments = []

    for filename, content in project_files.items():
        file_path = os.path.join(local_path, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        if isinstance(content, str) and content.startswith("data:") and "base64," in content:
            match = re.search(r"base64,(.*)", content, re.I)
            if match:
                file_bytes = base64.b64decode(match.group(1))
                async with aiofiles.open(file_path, "wb") as f:
                    await f.write(file_bytes)
        elif isinstance(content, str):
            async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                await f.write(content)
        # Already bytes
        elif isinstance(content, bytes):
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(content)

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
                    async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
                            await f.write(url_or_data)

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
    """Fast LLM code generation with retries."""
    brief = data.get("brief", "")
    checks = data.get("checks", [])
    round_index = data.get("round", 1)
    attachments = data.get("attachments", [])
    existing_files = data.get("existing_files", {})
    task = data.get("task", "project")

    # Detect attachment types and summarize them
    if attachments:
        results = await asyncio.gather(*(detect_attachment_type(att) for att in attachments))
        attachment_info = [f"{att['name']} ({typ})" for att, typ in zip(attachments, results) if att.get("name")]
        attachment_list_str = ", ".join(attachment_info)
    else:
        attachment_list_str = "None"

    # Format checks into a bullet list for prompt clarity
    

    # Base system prompt — expert full-stack developer, output JSON array only
    system_prompt = (
    """
        You are a highly experienced full-stack developer with extensive expertise in building complete, professional web applications.

        Your task is to generate a fully functional project codebase that strictly adheres to the following specifications:
        Verify all external library APIs  match their latest stable CDN versions.
        Use correct function calls and import paths as per official documentation.

        - Deliver ONLY a JSON array of objects, each containing:
        - 'filename' — the file name.
        - 'content' — the complete file content.
        - Do NOT include any text, explanations, or formatting outside this JSON array.
        - Include at minimum the following files:
        - index.html
        - README.md
        - LICENSE
        - The README.md must provide a clear, professional summary of the application, covering:
        - Purpose and overview of the app.
        - Setup and installation instructions.
        - Usage guidelines and examples.
        - Detailed explanation of the code structure, components, and functionality.
        - The LICENSE file must contain the complete text of the MIT License.
        """
)


    if round_index == 1:
        # Initial build: instruct to generate a complete project implementing all checks
        user_prompt = (
            f"Task: {task}\n"
            f"Brief: {brief}\n"
            f"Evaluation Checks: {checks}\n"
            f"Attachments: {attachment_list_str}\n\n"
            "Generate a full project with all necessary files (HTML, CSS, JS, assets) to fully implement the above brief and pass all checks. "
            "Dynamically load and display images or other attachments as required."
            "Implement all interactive or dynamic behaviors needed to pass checks. "
            "Implement all core features fully; no placeholders or stubs.\n"
            "Include professional README.md and LICENSE files. "
            "Return ONLY the complete project files as a JSON array.")
    else:
        # Round 2 revision: update existing code, make incremental changes only
        # Provide list of existing files (show up to 10 files)
        # Prepare existing file previews (first 500 chars each)
        max_preview_chars = 500  # limit per file for huge files
        text_extensions = {".txt", ".md", ".py", ".html", ".js", ".css", ".json", ".csv"}

        existing_files_preview_list = []
        for fname, content in existing_files.items():
            # If file is too large, truncate preview
            if isinstance(content, str) and len(content) > max_preview_chars:
                preview = content[:max_preview_chars] + "\n... [truncated]"
            else:
                preview = content
            existing_files_preview_list.append(f"--- {fname} ---\n{preview}")

        existing_files_preview = "\n\n".join(existing_files_preview_list) if existing_files else "No existing files."

        # Build user prompt for round 2
        user_prompt = (
            f"Task: {task} (Revision)\n"
            f"New Brief: {brief}\n"
            f"Updated Evaluation Checks: {checks}\n"
            f"Attachments: {attachment_list_str}\n\n"
            f"Existing files in project (full content, truncated if very long):\n{existing_files_preview}\n\n"
            "Instructions for LLM:\n"
            "1. Reuse all existing code and logic wherever applicable.\n"
            "2. Integrate attachments (CSV, JSON, images, etc.) as required for the new brief.\n"
            "3. Do NOT overwrite unrelated files or previously working logic.\n"
            "4. Preserve previously computed values, state, or configuration where relevant.\n"
            "5. Only modify files necessary to implement the new brief, pass updated checks, fix bugs, or refactor.\n"
            "6. Update README.md if new features are added.\n"
            "7. Maintain existing LICENSE if present.\n"
            "8. Ensure all provided evaluation checks pass successfully before submission.\n"
            "9. Return ONLY the new or updated files as a JSON array with filename and content.\n"
        )


    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    OPENAI_BASE_URL,
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json=payload
                )
                if resp.status_code >= 500:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(3 * (attempt + 1))
                        continue
                    else:
                        raise Exception(f"LLM service failed after {max_retries} retries (HTTP {resp.status_code})")

                resp.raise_for_status()
                result = resp.json()
                text = result["choices"][0]["message"]["content"]
                files = clean_json_response(text)

                if not isinstance(files, list):
                    raise ValueError("Invalid JSON output from LLM")

                # Ensure mandatory files
                mandatory = {
                    "index.html": "<!DOCTYPE html><html><body>Error</body></html>",
                    "README.md": "Project generated by LLM.",
                    "LICENSE": "MIT License"
                }
                existing_filenames = [f["filename"] for f in files]
                for fname, content in mandatory.items():
                    if fname not in existing_filenames:
                        files.append({"filename": fname, "content": content})

                return files

        except (httpx.ConnectError, httpx.TimeoutException) as e:
            print(f"⚠️ Network error (attempt {attempt+1}/{max_retries}): {e}")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"❌ Error in attempt {attempt+1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                raise Exception(f"LLM generation failed: {e}")

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
    """Push all files from local_path to GitHub repo using API."""
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
                    with open(file_path, "rb") as f:
                        content_bytes = f.read()
                    content_b64 = base64.b64encode(content_bytes).decode()

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
                        print(f"⚠️ Failed to upload {rel_path}: {resp.status_code}")
                except Exception as e:
                    print(f"⚠️ Error uploading {rel_path}: {e}")

    return commit_sha

async def post_evaluation(evaluation_url, payload):
    async with httpx.AsyncClient() as client:
        delay = 1
        for attempt in range(6):
            try:
                resp = await client.post(evaluation_url, json=payload, headers={"Content-Type": "application/json"})
                print(f"POST attempt {attempt+1}: status {resp.status_code}, text: {resp.text}")
                if resp.status_code in (200, 201, 204):
                    return True
            except Exception as e:
                print(f"POST attempt {attempt+1} failed: {e}")
            await asyncio.sleep(delay)
            delay *= 2
        print("⚠️ Failed to POST evaluation after retries.")
        return False


    
async def deploy_github_pages(repo_name: str) -> str:
    github_user = GITHUB_USER
    api_url = f"https://api.github.com/repos/{github_user}/{repo_name}/pages"
    payload = {"source": {"branch": "main", "path": "/"}, "build_type": "legacy"}
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(10):
            try:
                get_resp = await client.get(api_url, headers=headers)
                if get_resp.status_code == 404:
                    resp = await client.post(api_url, json=payload, headers=headers)
                elif get_resp.status_code == 200:
                    resp = await client.patch(api_url, json=payload, headers=headers)
                else:
                    resp = get_resp

                if resp.status_code in (200, 201):
                    print(f"✅ GitHub Pages setup initiated (attempt {attempt + 1})")
                    break
                elif resp.status_code == 409:
                    await asyncio.sleep(5)
                else:
                    resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                print(f"HTTP error on attempt {attempt + 1}: {e}")
                await asyncio.sleep(5)

        pages_url = f"https://{github_user}.github.io/{repo_name}/"
        for poll_attempt in range(30):
            try:
                r = await client.get(pages_url)
                if r.status_code == 200:
                    print(f"🚀 GitHub Pages live at: {pages_url}")
                    return pages_url
            except Exception:
                pass
            await asyncio.sleep(5)

    return pages_url

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

async def round1_task(data: dict):
    repo_name = data.get("task", "untitled-project")
    attachments = data.get("attachments", [])

    try:
        print("🧠 Generating code with LLM...")
        project_files = await write_code_llm(data)

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
        await asyncio.sleep(25)

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
    finally: 
        if os.path.exists(local_path):
            try:
                shutil.rmtree(local_path)
                print(f"✅ Temporary folder {local_path} cleaned up.")
            except Exception as e:
                print(f"⚠️ Failed to cleanup temp folder {local_path}: {e}")
                    

async def round2_task(data: dict):
    try:
        repo_name = f"{data['task']}"
        github_user = GITHUB_USER
        repo_url = f"https://{GITHUB_USER}:{GITHUB_TOKEN}@github.com/{github_user}/{repo_name}.git"

        print(f"🔁 Round 2: Cloning repo {repo_name}...")

        local_path = f"/tmp/{repo_name}"
        if os.path.exists(local_path):
            run_cmd(["rm", "-rf", local_path])
        run_cmd(["git", "clone", repo_url, local_path])

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
        await save_files_locally(repo_name, new_files_dict)

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

        commit_sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=local_path)

        await asyncio.sleep(15)
        print("🌐 Deploying GitHub Pages...")
        pages_url = await deploy_github_pages(repo_name)

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
        print(f"✅ Round 2 complete!")

    except Exception as e:
        print(f"❌ Error in round2_task: {e}")
    finally:
        if os.path.exists(local_path):
            try:
                shutil.rmtree(local_path)
                print(f"✅ Temporary folder {local_path} cleaned up.")      
            except Exception as e:
                print(f"⚠️ Failed to cleanup temp folder {local_path}: {e}")    

# ----------------------
# FastAPI Routes (DEFINE BEFORE GRADIO)
# ----------------------
@app.get("/")
async def root():
    return {
        "status": "ok", 
        "message": "LLM Task Runner is live!",
        "endpoints": {
            "api_docs": "/docs",
            "handle_request": "/handle_request",
            "health": "/health"
        }
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "github_token": "configured" if GITHUB_TOKEN else "missing",
        "openai_key": "configured" if OPENAI_API_KEY else "missing",
        "secret": "configured" if SECRET_KEY else "missing"
    }

@app.post("/handle_request")
async def handle_request(request: Request):
    try:
        data = await request.json()
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Invalid JSON: {str(e)}"}
        )
    
    if not validate_secret(data.get("secret", "")):
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "Invalid secret"}
        )
    
    round_number = data.get("round", 1)
    
    try:
        if round_number == 1:
            asyncio.create_task(round1_task(data))
        elif round_number == 2:
            asyncio.create_task(round2_task(data))
        else:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": f"Unknown round: {round_number}"}
            )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Failed to start task: {str(e)}"}
        )
    
    return {"status": "ok", "message": f"Round {round_number} processing started in background"}

# ----------------------
# Mount Gradio LAST
# ----------------------
def gradio_interface():
    return "✅ LLM Task Runner is operational!\n\nAPI Endpoint: POST /handle_request\nDocs: /docs"

demo = gr.Interface(
    fn=gradio_interface,
    inputs=[],
    outputs="text",
    title="LLM Task Runner",
    description="FastAPI + Gradio Integration. Use POST /handle_request for API access."
)

# Mount Gradio at /ui so it doesn't conflict with FastAPI routes
app = gr.mount_gradio_app(app, demo, path="/ui")

# For Hugging Face Spaces
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
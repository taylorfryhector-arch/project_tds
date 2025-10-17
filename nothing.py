# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fastapi[standard]",
#   "uvicorn",
#   "httpx",
# ]
# ///
import asyncio
import os
import httpx

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
repo_name = "captcha-solver-demo-001_abc123-nonce-teste"  # Replace with an existing repo under your account
github_user = "taylorfryhector-arch"

async def deploy_github_pages(repo_name):
    url = f"https://api.github.com/repos/{github_user}/{repo_name}/pages"
    payload = {"source": {"branch": "main", "path": "/"}, "build_type": "legacy"}
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    async with httpx.AsyncClient() as client:
        for attempt in range(10):
            try:
                get_resp = await client.get(url, headers=headers)
                print(f"Attempt {attempt+1} GET Pages status:", get_resp.status_code)
                if get_resp.status_code == 404:
                    print("Pages not found, trying POST...")
                    resp = await client.post(url, json=payload, headers=headers)
                elif get_resp.status_code == 200:
                    print("Pages exist, trying PATCH...")
                    resp = await client.patch(url, json=payload, headers=headers)
                else:
                    get_resp.raise_for_status()
                    resp = get_resp

                print("POST/PATCH response status:", resp.status_code)
                if resp.status_code in (200, 201):
                    print("Pages setup succeeded!")
                    break
                elif resp.status_code == 409:
                    print("Conflict, retrying in 5s...")
                    await asyncio.sleep(5)
                else:
                    resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                print(f"HTTP error during Pages setup: {e}")
                await asyncio.sleep(5)
        else:
            raise Exception("Failed to enable GitHub Pages after multiple retries")

        pages_url = f"https://{github_user}.github.io/{repo_name}/"
        for _ in range(10):  # Reduced to 10 tries for testing
            try:
                r = await client.get(pages_url)
                print("Checking Pages URL:", r.status_code)
                if r.status_code == 200:
                    print("Pages URL reachable:", pages_url)
                    return pages_url
            except Exception as e:
                print("Error checking pages URL:", e)
            await asyncio.sleep(5)

    raise Exception("GitHub Pages not reachable after retries")

# Run the test
asyncio.run(deploy_github_pages(repo_name))

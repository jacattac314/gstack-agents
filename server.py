import os
import json
import subprocess
import re
import shutil
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from gstack_core import GStackSprintOrchestrator, resolve_local_model, load_provider_config, save_provider_config, BASE_DIR, LOGS_DIR, WORKSPACE_DIR

app = FastAPI(
    title="GStack Agents Local gateway Console",
    description="FastAPI console for running role-based YC-style local agent sprints.",
    version="1.0.0"
)

# Enable CORS for frontend dashboard UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Workspace directory as static files under /workspace/app
app.mount("/workspace/app", StaticFiles(directory=WORKSPACE_DIR), name="workspace_app")

# State variable for active background task
active_sprint_task = None

# Load credentials from .env if exists on startup
ENV_FILE_PATH = os.path.join(BASE_DIR, ".env")
def load_github_token():
    if os.path.exists(ENV_FILE_PATH):
        try:
            with open(ENV_FILE_PATH, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and "=" in line and not line.startswith("#"):
                        key, val = line.split("=", 1)
                        if key.strip() in ["GITHUB_TOKEN", "GH_TOKEN"]:
                            os.environ[key.strip()] = val.strip().strip('"').strip("'")
        except Exception:
            pass

load_github_token()

# Helper to run the sprint in background
async def run_sprint_background(goal: str):
    global active_sprint_task
    try:
        orchestrator = GStackSprintOrchestrator(goal)
        active_sprint_task = orchestrator
        await orchestrator.run_sprint()
    except Exception as e:
        print(f"Error in background sprint execution: {e}")
    finally:
        active_sprint_task = None

# --------------------------------------------------------------------
# Static Assets Routes
# --------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    raise HTTPException(status_code=404, detail="index.html not found")

@app.get("/index.css")
async def serve_css():
    css_path = os.path.join(BASE_DIR, "index.css")
    if os.path.exists(css_path):
        return FileResponse(css_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    raise HTTPException(status_code=404, detail="index.css not found")

@app.get("/app.js")
async def serve_js():
    js_path = os.path.join(BASE_DIR, "app.js")
    if os.path.exists(js_path):
        return FileResponse(js_path, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    raise HTTPException(status_code=404, detail="app.js not found")

# --------------------------------------------------------------------
# REST API Endpoints
# --------------------------------------------------------------------
def verify_token_direct(token: str):
    """Verifies the GitHub token directly via GitHub API and returns (username, is_valid)."""
    import urllib.request
    import urllib.error
    import json
    if not token:
        return None, False
    req = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "GStack-Agent-Console"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return data.get("login", "Unknown"), True
    except Exception as e:
        print(f"Direct token verification failed: {e}")
    return None, False

@app.get("/api/github/status")
async def api_github_status():
    """Checks the active git remote configuration and gh auth status."""
    git_dir = os.path.join(WORKSPACE_DIR, ".git")
    active_repo = "Not Configured"
    
    if os.path.exists(git_dir):
        try:
            res = subprocess.run(
                "git remote get-url origin",
                shell=True,
                cwd=WORKSPACE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5
            )
            if res.returncode == 0 and res.stdout:
                # Redact token from url for security
                url = res.stdout.strip()
                redacted_url = re.sub(r"https://[^@]+@", "https://", url)
                active_repo = redacted_url
        except Exception:
            pass
            
    # Check token verification directly
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    gh_user = "Unknown"
    is_authenticated = False
    
    if token:
        try:
            username, is_valid = verify_token_direct(token)
            if is_valid:
                gh_user = username
                is_authenticated = True
        except Exception:
            pass
        
    return {
        "authenticated": is_authenticated,
        "username": gh_user,
        "active_repo": active_repo
    }

@app.post("/api/github/login")
async def api_github_login(payload: dict):
    """Saves a GitHub Personal Access Token (PAT) locally and verifies it."""
    token = payload.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing GitHub Personal Access Token (PAT)")
        
    try:
        # Verify the token by calling the GitHub API directly
        username, is_valid = verify_token_direct(token)
        if not is_valid:
            raise Exception("The provided token is invalid or unauthorized by GitHub.")
            
        # Write token to .env
        with open(ENV_FILE_PATH, "w") as f:
            f.write(f"GITHUB_TOKEN={token}\n")
            f.write(f"GH_TOKEN={token}\n")
            
        # Set active environment variables
        os.environ["GITHUB_TOKEN"] = token
        os.environ["GH_TOKEN"] = token
        
        # If origin exists in workspace, update it to use token
        git_dir = os.path.join(WORKSPACE_DIR, ".git")
        if os.path.exists(git_dir):
            try:
                res_url = subprocess.run(
                    "git remote get-url origin",
                    shell=True,
                    cwd=WORKSPACE_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5
                )
                if res_url.returncode == 0 and res_url.stdout:
                    url = res_url.stdout.strip()
                    # Strip existing credentials and re-inject new token
                    clean_url = re.sub(r"https://[^@]+@", "https://", url)
                    repo_path = clean_url.replace("https://github.com/", "")
                    authed_url = f"https://{username}:{token}@github.com/{repo_path}"
                    subprocess.run(f"git remote set-url origin {authed_url}", shell=True, cwd=WORKSPACE_DIR, timeout=5)
            except Exception:
                pass
                
        return {
            "status": "success",
            "message": "Token verified and securely linked!",
            "username": username
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Authentication failed: {str(e)}"
        }


@app.get("/api/github/repos")
async def api_github_repos():
    """Fetches the list of repositories for the authenticated user from GitHub API."""
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise HTTPException(status_code=401, detail="Please authenticate with a GitHub PAT first")
        
    import urllib.request
    import urllib.error
    import json
    
    req = urllib.request.Request(
        "https://api.github.com/user/repos?per_page=100&sort=updated",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "GStack-Agent-Console"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status == 200:
                repos_data = json.loads(response.read().decode())
                output = []
                for r in repos_data:
                    output.append({
                        "name": r.get("name"),
                        "full_name": r.get("full_name"),
                        "private": r.get("private")
                    })
                return {"repos": output}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch repositories from GitHub: {str(e)}")


@app.post("/api/github/sync")
async def api_github_sync(payload: dict):
    """Clones an existing repository or creates a new one on GitHub using authenticated token."""
    action = payload.get("action") # "create" or "connect"
    repo_name = payload.get("repo_name")
    
    if not repo_name or not action:
        raise HTTPException(status_code=400, detail="Missing 'action' or 'repo_name'")
        
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise HTTPException(status_code=401, detail="Please authenticate with a GitHub PAT first")
        
    # Clean repo name from symbols
    repo_name = re.sub(r"[^a-zA-Z0-9_-]", "", repo_name)
    
    status_res = await api_github_status()
    username = status_res.get("username", "jacattac314")
    
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    env["GITHUB_TOKEN"] = token
    
    # 1. Connect (Clone) Action
    if action == "connect":
        try:
            # Safely recreate workspace directory
            if os.path.exists(WORKSPACE_DIR):
                shutil.rmtree(WORKSPACE_DIR)
            os.makedirs(WORKSPACE_DIR, exist_ok=True)
            
            # Embed username and token in clone URL to guarantee passwordless credentials
            clone_url = f"https://{username}:{token}@github.com/{username}/{repo_name}.git"
            
            res = subprocess.run(
                f"git clone {clone_url} .",
                shell=True,
                env=env,
                cwd=WORKSPACE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if res.returncode != 0:
                raise Exception(res.stderr or "Clone failed")
                
            return {
                "status": "success",
                "message": f"Successfully cloned remote repository as @{username}!"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to connect repository: {str(e)}"
            }
            
    # 2. Create Action
    elif action == "create":
        try:
            # Create repo on GitHub with optional description
            desc_val = payload.get("description", "").strip()
            clean_desc = desc_val.replace('"', '\\"')
            desc_flag = f'--description "{clean_desc}"' if clean_desc else ""
            
            res = subprocess.run(
                f"gh repo create {repo_name} --public {desc_flag}",
                shell=True,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15
            )
            if res.returncode != 0 and "already exists" not in (res.stderr + res.stdout):
                raise Exception(res.stderr or "GitHub repository creation failed")
                
            # Initialize Git inside workspace
            subprocess.run("git init", shell=True, cwd=WORKSPACE_DIR)
            
            # Remove existing remote if it exists
            subprocess.run("git remote remove origin", shell=True, cwd=WORKSPACE_DIR)
            
            # Add authenticated remote origin
            remote_url = f"https://{username}:{token}@github.com/{username}/{repo_name}.git"
            subprocess.run(f"git remote add origin {remote_url}", shell=True, cwd=WORKSPACE_DIR)
            
            # Create a base README.md if workspace is empty
            readme_path = os.path.join(WORKSPACE_DIR, "README.md")
            if not os.listdir(WORKSPACE_DIR) or not os.path.exists(readme_path):
                with open(readme_path, "w") as f:
                    desc_para = f"\n{desc_val}\n" if desc_val else ""
                    f.write(f"# {repo_name}\n{desc_para}\nAutomated workspace project created via local GStack Agent stack.\n")
                    
            # Stage, commit, and push initial commit
            subprocess.run("git add .", shell=True, cwd=WORKSPACE_DIR)
            subprocess.run('git commit -m "initial commit from local gstack agents"', shell=True, cwd=WORKSPACE_DIR)
            subprocess.run("git branch -M main", shell=True, cwd=WORKSPACE_DIR)
            
            push_res = subprocess.run(
                "git push -u origin main",
                shell=True,
                env=env,
                cwd=WORKSPACE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if push_res.returncode != 0:
                raise Exception(push_res.stderr or "Initial git push failed")
                
            return {
                "status": "success",
                "message": f"Successfully created and pushed remote repository: https://github.com/{username}/{repo_name}"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to create repository: {str(e)}"
            }
            
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

@app.post("/api/sprint/start")
async def api_sprint_start(payload: dict, background_tasks: BackgroundTasks):
    global active_sprint_task
    goal = payload.get("goal")
    if not goal:
        raise HTTPException(status_code=400, detail="Missing 'goal' in payload")
        
    if active_sprint_task is not None:
        return {"status": "error", "message": "A sprint is already running!"}
        
    # Reset existing logs to prevent flash of old content
    for agent in ["ceo", "eng_manager", "designer", "coder", "qa_lead", "release_engineer"]:
        log_path = os.path.join(LOGS_DIR, f"{agent}.log")
        if os.path.exists(log_path):
            try:
                os.remove(log_path)
            except Exception:
                pass
                
    # Reset state file
    state_file = os.path.join(LOGS_DIR, "sprint_state.json")
    if os.path.exists(state_file):
        try:
            os.remove(state_file)
        except Exception:
            pass
            
    # Trigger sprint in background
    background_tasks.add_task(run_sprint_background, goal)
    return {"status": "success", "message": "GStack sprint triggered successfully in background."}

@app.post("/api/sprint/stop")
async def api_sprint_stop():
    global active_sprint_task
    if active_sprint_task is None:
        # Self-healing: If no active python task object exists, check if the state file indicates a running sprint
        state_file = os.path.join(LOGS_DIR, "sprint_state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, "r") as f:
                    state_data = json.load(f)
                
                # If it's indeed running, force-cancel the state file directly to recover gracefully
                if state_data.get("current_phase") not in ["idle", "completed", "cancelled"]:
                    state_data["current_phase"] = "cancelled"
                    for phase in state_data.get("phases", {}):
                        if state_data["phases"][phase].get("status") in ["running", "pending"]:
                            state_data["phases"][phase]["status"] = "cancelled"
                    
                    with open(state_file, "w") as f:
                        json.dump(state_data, f, indent=2)
                        
                    return {"status": "success", "message": "No running thread detected. Force-cancelled sprint state successfully."}
            except Exception as e:
                print(f"Failed to self-heal/force-cancel sprint state: {e}")
                
        return {"status": "error", "message": "No active sprint is running."}
    
    try:
        active_sprint_task.cancel()
        return {"status": "success", "message": "Sprint cancellation requested successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cancel sprint: {e}")

@app.get("/api/sprint/status")
async def api_sprint_status():
    state_file = os.path.join(LOGS_DIR, "sprint_state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except Exception as e:
            return {"status": "error", "message": f"Could not read state: {e}"}
            
    # Default idle state if file doesn't exist yet
    return {
        "goal": "No active sprint",
        "current_phase": "idle",
        "phases": {},
        "metrics": {
            "active_model": resolve_local_model(),
            "total_runs": 0,
            "accumulated_savings": 0.0,
            "latency_history": []
        }
    }

@app.get("/api/agent/log")
async def api_agent_log(agent: str = Query(..., description="The agent key (e.g. ceo, coder)")) -> JSONResponse:
    log_path = os.path.join(LOGS_DIR, f"{agent}.log")
    if not os.path.exists(log_path):
        return JSONResponse({"log": f"Waiting for {agent.upper()} to start...\n"})
    try:
        with open(log_path, "r") as f:
            return JSONResponse({"log": f.read()})
    except Exception as e:
        return JSONResponse({"log": f"Error reading log file: {e}"})

@app.get("/api/workspace/files")
async def api_workspace_files():
    try:
        files = os.listdir(WORKSPACE_DIR)
        output = []
        for file in files:
            p = os.path.join(WORKSPACE_DIR, file)
            # Skip hidden files
            if file.startswith("."):
                continue
            size = os.path.getsize(p)
            output.append({"name": file, "size": size})
        return {"files": output}
    except Exception as e:
        return {"files": [], "error": str(e)}

@app.get("/api/workspace/file")
async def api_workspace_file(path: str = Query(..., description="Filename to read")):
    safe_path = os.path.join(WORKSPACE_DIR, os.path.basename(path))
    if not os.path.exists(safe_path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        with open(safe_path, 'r') as f:
            return {"content": f.read()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config/provider")
async def api_get_provider_config():
    """Serves the active intelligence provider configuration."""
    try:
        return load_provider_config()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/config/provider")
async def api_post_provider_config(payload: dict):
    """Updates the intelligence provider configuration."""
    try:
        provider = payload.get("provider", "lm_studio")
        freellmapi_url = payload.get("freellmapi_url", "http://localhost:3001/v1")
        freellmapi_token = payload.get("freellmapi_token", "")
        freellmapi_model = payload.get("freellmapi_model", "google/gemini-2.5-flash")
        
        config = {
            "provider": provider,
            "freellmapi_url": freellmapi_url,
            "freellmapi_token": freellmapi_token,
            "freellmapi_model": freellmapi_model
        }
        
        save_provider_config(config)
        return {"status": "success", "message": "Provider configuration updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/models")
async def api_models():
    config = load_provider_config()
    if config.get("provider") == "freellmapi":
        model_name = "FreeLLMAPI: " + config.get("freellmapi_model", "google/gemini-2.5-flash")
        return {"active_model": model_name}
    return {"active_model": resolve_local_model()}

if __name__ == "__main__":
    print(f"Initializing GStack API Dashboard on http://127.0.0.1:8000...")
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=False)

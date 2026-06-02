import os
import json
import subprocess
import re
import shutil
import base64
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

_ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "")
if _ALLOWED_ORIGINS:
    _cors_kwargs = {"allow_origins": [o.strip() for o in _ALLOWED_ORIGINS.split(",")]}
else:
    _cors_kwargs = {"allow_origin_regex": r"^(tauri://localhost|https?://(localhost|127\.0\.0\.1)(:\d+)?)$"}

app.add_middleware(
    CORSMiddleware,
    **_cors_kwargs,
    allow_credentials=False,
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

def redact_secret(text: str, secret: str = None) -> str:
    if not text:
        return text
    redacted = text
    if secret:
        redacted = redacted.replace(secret, "[redacted]")
    return re.sub(r"https://[^@\s]+@", "https://[redacted]@", redacted)

def github_auth_header(username: str, token: str) -> str:
    auth = base64.b64encode(f"{username}:{token}".encode("utf-8")).decode("ascii")
    return f"AUTHORIZATION: Basic {auth}"

def run_git_with_github_token(args, username: str, token: str, cwd: str, env: dict = None, timeout: int = None):
    command = [
        "git",
        "-c",
        f"http.https://github.com/.extraheader={github_auth_header(username, token)}",
        *args,
    ]
    return subprocess.run(
        command,
        env=env,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )

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
                ["git", "remote", "get-url", "origin"],
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
        
        # If origin exists in workspace, remove any embedded credentials instead
        # of persisting the new token into .git/config.
        git_dir = os.path.join(WORKSPACE_DIR, ".git")
        if os.path.exists(git_dir):
            try:
                res_url = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
                    cwd=WORKSPACE_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5
                )
                if res_url.returncode == 0 and res_url.stdout:
                    url = res_url.stdout.strip()
                    clean_url = re.sub(r"https://[^@]+@", "https://", url)
                    subprocess.run(["git", "remote", "set-url", "origin", clean_url], cwd=WORKSPACE_DIR, timeout=5)
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
            
            clone_url = f"https://github.com/{username}/{repo_name}.git"
            
            res = run_git_with_github_token(
                ["clone", clone_url, "."],
                username,
                token,
                WORKSPACE_DIR,
                env=env,
            )
            if res.returncode != 0:
                raise Exception(redact_secret(res.stderr or "Clone failed", token))
            
            subprocess.run(["git", "remote", "set-url", "origin", clone_url], cwd=WORKSPACE_DIR, timeout=5)
                
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
            create_args = ["gh", "repo", "create", repo_name, "--public"]
            if desc_val:
                create_args.extend(["--description", desc_val])
            
            res = subprocess.run(
                create_args,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15
            )
            if res.returncode != 0 and "already exists" not in (res.stderr + res.stdout):
                raise Exception(res.stderr or "GitHub repository creation failed")
                
            # Initialize Git inside workspace
            subprocess.run(["git", "init"], cwd=WORKSPACE_DIR)
            
            # Remove existing remote if it exists
            subprocess.run(["git", "remote", "remove", "origin"], cwd=WORKSPACE_DIR)
            
            remote_url = f"https://github.com/{username}/{repo_name}.git"
            subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=WORKSPACE_DIR)
            
            # Create a base README.md if workspace is empty
            readme_path = os.path.join(WORKSPACE_DIR, "README.md")
            if not os.listdir(WORKSPACE_DIR) or not os.path.exists(readme_path):
                with open(readme_path, "w") as f:
                    desc_para = f"\n{desc_val}\n" if desc_val else ""
                    f.write(f"# {repo_name}\n{desc_para}\nAutomated workspace project created via local GStack Agent stack.\n")
                    
            # Stage, commit, and push initial commit
            subprocess.run(["git", "add", "."], cwd=WORKSPACE_DIR)
            subprocess.run(["git", "commit", "-m", "initial commit from local gstack agents"], cwd=WORKSPACE_DIR)
            subprocess.run(["git", "branch", "-M", "main"], cwd=WORKSPACE_DIR)
            
            push_res = run_git_with_github_token(
                ["push", "-u", "origin", "main"],
                username,
                token,
                WORKSPACE_DIR,
                env=env,
            )
            if push_res.returncode != 0:
                raise Exception(redact_secret(push_res.stderr or "Initial git push failed", token))
                
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
                
    # Reset debate logs
    debate_path = os.path.join(LOGS_DIR, "debate_log.json")
    if os.path.exists(debate_path):
        try:
            os.remove(debate_path)
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

@app.post("/api/sprint/reset")
async def api_sprint_reset():
    global active_sprint_task
    # 1. Stop active thread if running
    if active_sprint_task is not None:
        try:
            active_sprint_task.cancel()
        except Exception:
            pass
        active_sprint_task = None
        
    # 2. Reset logs
    for agent in ["ceo", "eng_manager", "designer", "coder", "qa_lead", "release_engineer"]:
        log_path = os.path.join(LOGS_DIR, f"{agent}.log")
        if os.path.exists(log_path):
            try:
                os.remove(log_path)
            except Exception:
                pass
                
    debate_path = os.path.join(LOGS_DIR, "debate_log.json")
    if os.path.exists(debate_path):
        try:
            os.remove(debate_path)
        except Exception:
            pass

    # 3. Overwrite sprint state file back to default idle
    state_file = os.path.join(LOGS_DIR, "sprint_state.json")
    default_state = {
        "goal": "No active sprint",
        "current_phase": "idle",
        "phases": {
            "think": {"status": "pending", "agent": "ceo", "summary": ""},
            "plan": {"status": "pending", "agent": "eng_manager", "summary": ""},
            "design": {"status": "pending", "agent": "designer", "summary": ""},
            "build": {"status": "pending", "agent": "coder", "summary": ""},
            "review": {"status": "pending", "agent": "release_engineer", "summary": ""},
            "test": {"status": "pending", "agent": "qa_lead", "summary": ""},
            "ship": {"status": "pending", "agent": "release_engineer", "summary": ""}
        },
        "metrics": {
            "active_model": resolve_local_model(),
            "total_runs": 0,
            "accumulated_savings": 0.0,
            "latency_history": []
        }
    }
    try:
        with open(state_file, "w") as f:
            json.dump(default_state, f, indent=2)
    except Exception:
        pass

    # 4. Clean workspace: delete all files except hidden files (like .git, .env)
    try:
        if os.path.exists(WORKSPACE_DIR):
            for filename in os.listdir(WORKSPACE_DIR):
                if filename.startswith("."):
                    continue
                file_path = os.path.join(WORKSPACE_DIR, filename)
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                else:
                    os.remove(file_path)
    except Exception as e:
        print(f"Error cleaning workspace: {e}")

    return {"status": "success", "message": "Dashboard state and workspace successfully reset."}

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

# --------------------------------------------------------------------
# HITL Approval & Webhook Config Endpoints
# --------------------------------------------------------------------
WEBHOOK_CONFIG_PATH = os.path.join(LOGS_DIR, "webhook_config.json")

def load_webhook_config() -> dict:
    if os.path.exists(WEBHOOK_CONFIG_PATH):
        try:
            with open(WEBHOOK_CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"slack_webhook": "", "whatsapp_webhook": ""}

def save_webhook_config(config: dict):
    try:
        with open(WEBHOOK_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving webhook config: {e}")

@app.get("/api/config/webhook")
async def api_get_webhook_config():
    return load_webhook_config()

@app.post("/api/config/webhook")
async def api_post_webhook_config(payload: dict):
    save_webhook_config(payload)
    return {"status": "success", "message": "Webhook configuration updated successfully."}

@app.get("/api/sprint/approval")
async def api_sprint_approval():
    state_file = os.path.join(LOGS_DIR, "sprint_state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                state = json.load(f)
                
                # Resolve requesting agent name
                phase_to_agent = {
                    "think": "CEO Agent",
                    "plan": "Engineering Manager",
                    "design": "Designer",
                    "build": "Coder Agent",
                    "review": "Release Engineer",
                    "test": "QA Lead",
                    "ship": "Release Engineer"
                }
                curr_phase = state.get("current_phase", "build")
                agent_name = phase_to_agent.get(curr_phase, "Release Engineer")
                
                return {
                    "approval_status": state.get("approval_status", ""),
                    "requested_command": state.get("requested_command", ""),
                    "requesting_agent": agent_name
                }
        except Exception:
            pass
    return {"approval_status": "", "requested_command": "", "requesting_agent": "Release Engineer"}

@app.post("/api/sprint/approve")
async def api_sprint_approve():
    state_file = os.path.join(LOGS_DIR, "sprint_state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                state = json.load(f)
            state["approval_status"] = "approved"
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)
            return {"status": "success", "message": "Command approved successfully."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to approve command: {e}")
    raise HTTPException(status_code=404, detail="Sprint state not found.")

@app.post("/api/sprint/reject")
async def api_sprint_reject():
    state_file = os.path.join(LOGS_DIR, "sprint_state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                state = json.load(f)
            state["approval_status"] = "rejected"
            with open(state_file, "w") as f:
                json.dump(state, f, indent=2)
            return {"status": "success", "message": "Command rejected successfully."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to reject command: {e}")
    raise HTTPException(status_code=404, detail="Sprint state not found.")

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

@app.get("/api/health")
async def api_health():
    return {"status": "ok"}

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

@app.get("/api/config/freellmapi/models")
async def api_get_freellmapi_models(url: str = None, token: str = None):
    """Proxies models retrieval from the configured FreeLLMAPI instance to prevent client-side CORS issues."""
    config = load_provider_config()
    base_url = url or config.get("freellmapi_url", "http://localhost:3001/v1")
    base_url = base_url.rstrip("/")
    target_url = f"{base_url}/models"
    
    actual_token = token if token is not None else config.get("freellmapi_token", "")
    actual_token = actual_token.strip()
    
    headers = {}
    if actual_token:
        headers["Authorization"] = f"Bearer {actual_token}"
        
    import urllib.request
    import json
    req = urllib.request.Request(target_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                return json.loads(response.read().decode())
    except Exception as e:
        print(f"Proxy models fetch failed: {e}. Serving premium fallback list.")
        
    # Fallback list of popular models if FreeLLMAPI is offline, unreachable or unauthenticated
    return {
        "data": [
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "owned_by": "google"},
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B", "owned_by": "groq"},
            {"id": "gpt-4o", "name": "GPT-4o", "owned_by": "github"},
            {"id": "mistral-large-latest", "name": "Mistral Large 3", "owned_by": "mistral"},
            {"id": "codestral-latest", "name": "Codestral", "owned_by": "mistral"},
            {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B", "owned_by": "groq"},
            {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B (free)", "owned_by": "openrouter"},
            {"id": "nousresearch/hermes-3-llama-3.1-405b:free", "name": "Hermes 3 405B (free)", "owned_by": "openrouter"}
        ]
    }

@app.get("/api/sprint/debate")
async def api_sprint_debate():
    debate_file = os.path.join(LOGS_DIR, "debate_log.json")
    if os.path.exists(debate_file):
        try:
            with open(debate_file, "r") as f:
                return json.load(f)
        except Exception as e:
            return {"status": "error", "message": f"Could not read debate logs: {e}"}
    return []

@app.get("/api/models")
async def api_models():
    config = load_provider_config()
    provider = config.get("provider")
    if provider == "freellmapi":
        model_name = "FreeLLMAPI: " + config.get("freellmapi_model", "google/gemini-2.5-flash")
        return {"active_model": model_name}
    elif provider == "cloud_first":
        model_name = "Cloud First: " + config.get("freellmapi_model", "google/gemini-2.5-flash")
        return {"active_model": model_name}
    return {"active_model": resolve_local_model()}

if __name__ == "__main__":
    print(f"Initializing GStack API Dashboard on http://127.0.0.1:8000...")
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)

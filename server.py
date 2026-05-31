import os
import json
import subprocess
import re
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from gstack_core import GStackSprintOrchestrator, resolve_local_model, BASE_DIR, LOGS_DIR, WORKSPACE_DIR

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

# State variable for active background task
active_sprint_task = None

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
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="index.html not found")

@app.get("/index.css")
async def serve_css():
    css_path = os.path.join(BASE_DIR, "index.css")
    if os.path.exists(css_path):
        return FileResponse(css_path)
    raise HTTPException(status_code=404, detail="index.css not found")

@app.get("/app.js")
async def serve_js():
    js_path = os.path.join(BASE_DIR, "app.js")
    if os.path.exists(js_path):
        return FileResponse(js_path)
    raise HTTPException(status_code=404, detail="app.js not found")

# --------------------------------------------------------------------
# REST API Endpoints
# --------------------------------------------------------------------
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
                text=True
            )
            if res.returncode == 0 and res.stdout:
                active_repo = res.stdout.strip()
        except Exception:
            pass
            
    # Check gh CLI authentication status
    gh_user = "Unknown"
    is_authenticated = False
    try:
        res = subprocess.run(
            "env -u GITHUB_TOKEN gh auth status",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        # gh auth status outputs to stderr typically
        output = res.stderr + "\n" + res.stdout
        match = re.search(r"Logged in to github\.com account ([a-zA-Z0-9_-]+)", output)
        if match:
            gh_user = match.group(1)
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
    """Pipes a GitHub Personal Access Token (PAT) directly into gh auth login."""
    token = payload.get("token")
    if not token:
        raise HTTPException(status_code=400, detail="Missing GitHub Personal Access Token (PAT)")
        
    try:
        # Pipe token to gh CLI auth login
        process = subprocess.Popen(
            ["env", "-u", "GITHUB_TOKEN", "gh", "auth", "login", "--with-token"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=token)
        
        if process.returncode != 0:
            raise Exception(stderr or stdout or "gh auth login command failed")
            
        # Get updated status
        status = await api_github_status()
        return {
            "status": "success",
            "message": "Successfully authenticated with GitHub!",
            "username": status.get("username")
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"GitHub login failed: {str(e)}"
        }

@app.post("/api/github/sync")
async def api_github_sync(payload: dict):
    """Clones an existing repository or creates a new one on GitHub."""
    action = payload.get("action") # "create" or "connect"
    repo_name = payload.get("repo_name")
    
    if not repo_name or not action:
        raise HTTPException(status_code=400, detail="Missing 'action' or 'repo_name'")
        
    # Clean repo name from symbols
    repo_name = re.sub(r"[^a-zA-Z0-9_-]", "", repo_name)
    
    # 1. Connect (Clone) Action
    if action == "connect":
        try:
            # Safely recreate workspace directory
            import shutil
            if os.path.exists(WORKSPACE_DIR):
                shutil.rmtree(WORKSPACE_DIR)
            os.makedirs(WORKSPACE_DIR, exist_ok=True)
            
            # Fetch default username
            status_res = await api_github_status()
            username = status_res.get("username", "jacattac314")
            
            # Run git clone
            clone_url = f"https://github.com/{username}/{repo_name}.git"
            res = subprocess.run(
                f"git clone {clone_url} .",
                shell=True,
                cwd=WORKSPACE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if res.returncode != 0:
                raise Exception(res.stderr or "Clone failed")
                
            return {
                "status": "success",
                "message": f"Successfully cloned remote repository: {clone_url}"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Failed to connect repository: {str(e)}"
            }
            
    # 2. Create Action
    elif action == "create":
        try:
            # Create repo on GitHub
            res = subprocess.run(
                f"env -u GITHUB_TOKEN gh repo create {repo_name} --public",
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if res.returncode != 0 and "already exists" not in (res.stderr + res.stdout):
                raise Exception(res.stderr or "GitHub repository creation failed")
                
            # Initialize Git inside workspace
            subprocess.run("git init", shell=True, cwd=WORKSPACE_DIR)
            
            # Fetch remote url
            status_res = await api_github_status()
            username = status_res.get("username", "jacattac314")
            remote_url = f"https://github.com/{username}/{repo_name}.git"
            
            # Remove existing remote if it exists
            subprocess.run("git remote remove origin", shell=True, cwd=WORKSPACE_DIR)
            
            # Add remote origin
            subprocess.run(f"git remote add origin {remote_url}", shell=True, cwd=WORKSPACE_DIR)
            
            # Create a base README.md if workspace is empty
            readme_path = os.path.join(WORKSPACE_DIR, "README.md")
            if not os.listdir(WORKSPACE_DIR) or not os.path.exists(readme_path):
                with open(readme_path, "w") as f:
                    f.write(f"# {repo_name}\n\nAutomated workspace project created via local GStack Agent stack.\n")
                    
            # Stage, commit, and push initial commit
            subprocess.run("git add .", shell=True, cwd=WORKSPACE_DIR)
            subprocess.run('git commit -m "initial commit from local gstack agents"', shell=True, cwd=WORKSPACE_DIR)
            subprocess.run("git branch -M main", shell=True, cwd=WORKSPACE_DIR)
            
            push_res = subprocess.run(
                "env -u GITHUB_TOKEN git push -u origin main",
                shell=True,
                cwd=WORKSPACE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if push_res.returncode != 0:
                raise Exception(push_res.stderr or "Initial git push failed")
                
            return {
                "status": "success",
                "message": f"Successfully created and synced remote repository: {remote_url}"
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

@app.get("/api/models")
async def api_models():
    return {"active_model": resolve_local_model()}

if __name__ == "__main__":
    print(f"Initializing GStack API Dashboard on http://127.0.0.1:8000...")
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)

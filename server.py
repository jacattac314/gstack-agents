import os
import json
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

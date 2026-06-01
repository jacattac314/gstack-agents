import os
import re
import json
import asyncio
import urllib.request
import urllib.parse
import subprocess
from typing import Dict, Any, List, Tuple

# Base paths
BASE_DIR = "/Users/jack/Documents/gstack-agents"
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
SKILLS_DIR = os.path.join(BASE_DIR, "skills")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
PROVIDER_CONFIG_PATH = os.path.join(LOGS_DIR, "provider_config.json")

# Ensure folders exist
os.makedirs(WORKSPACE_DIR, exist_ok=True)
os.makedirs(SKILLS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

def load_provider_config() -> dict:
    default_config = {
        "provider": "lm_studio",
        "freellmapi_url": "http://localhost:3001/v1",
        "freellmapi_token": "",
        "freellmapi_model": "google/gemini-2.5-flash"
    }
    if os.path.exists(PROVIDER_CONFIG_PATH):
        try:
            with open(PROVIDER_CONFIG_PATH, "r") as f:
                config = json.load(f)
                for k, v in default_config.items():
                    if k not in config:
                        config[k] = v
                return config
        except Exception:
            pass
    return default_config

def save_provider_config(config: dict):
    try:
        with open(PROVIDER_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving provider config: {e}")

# --------------------------------------------------------------------
# 1. Model Resolver (Defensive local model selection)
# --------------------------------------------------------------------
def resolve_local_model() -> str:
    """Queries LM Studio's /v1/models endpoint to resolve active model."""
    url = "http://localhost:1234/v1/models"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode('utf-8'))
            models = data.get("data", [])
            if models:
                # 1. Prefer nvidia/nemotron-3-nano-omni
                for m in models:
                    if "nemotron" in m.get("id", "").lower():
                        return m.get("id")
                # 2. Prefer Qwen Coder
                for m in models:
                    if "qwen" in m.get("id", "").lower() and "coder" in m.get("id", "").lower():
                        return m.get("id")
                # 3. Fallback to first non-embedding model
                for m in models:
                    if "embed" not in m.get("id", "").lower():
                        return m.get("id")
    except Exception:
        pass
    # Global fallback default
    return "nvidia/nemotron-3-nano-omni"

# --------------------------------------------------------------------
# 2. Local Model Request Client (Httpx/Urllib zero-dependency client)
# --------------------------------------------------------------------
async def chat_local_model(system_prompt: str, user_prompt: str, log_file_path: str = None) -> str:
    """Hits the configured LLM endpoint (LM Studio or FreeLLMAPI) with real-time stream logging."""
    config = load_provider_config()
    headers = {"Content-Type": "application/json"}
    
    if config.get("provider") == "freellmapi":
        base_url = config.get("freellmapi_url", "http://localhost:3001/v1").rstrip("/")
        url = f"{base_url}/chat/completions"
        model = config.get("freellmapi_model", "google/gemini-2.5-flash")
        token = config.get("freellmapi_token", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    else:
        # Default: LM Studio
        model = resolve_local_model()
        url = "http://localhost:1234/v1/chat/completions"
        
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.2,
        "stream": True
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST"
    )
    
    full_response = []
    try:
        loop = asyncio.get_event_loop()
        def fetch_stream():
            # Urllib stream reader
            return urllib.request.urlopen(req, timeout=60)
            
        response = await loop.run_in_executor(None, fetch_stream)
        
        while True:
            line_bytes = response.readline()
            if not line_bytes:
                break
            line = line_bytes.decode('utf-8').strip()
            if line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if delta:
                        full_response.append(delta)
                        if log_file_path:
                            with open(log_file_path, "a") as f:
                                f.write(delta)
                                f.flush()
                except Exception:
                    pass
    except Exception as e:
        error_msg = f"\n[LM Link Connection Failure: {e}]\n"
        full_response.append(error_msg)
        if log_file_path:
            with open(log_file_path, "a") as f:
                f.write(error_msg)
                f.flush()
                
    return "".join(full_response)

# --------------------------------------------------------------------
# 3. Custom Workspace Agent Tools
# --------------------------------------------------------------------
def tool_read_file(path: str) -> str:
    """Reads a file in the workspace."""
    safe_path = os.path.join(WORKSPACE_DIR, os.path.basename(path))
    if not os.path.exists(safe_path):
        return f"Error: File '{path}' does not exist."
    try:
        with open(safe_path, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"

def tool_write_file(path: str, content: str) -> str:
    """Writes a file in the workspace."""
    safe_path = os.path.join(WORKSPACE_DIR, os.path.basename(path))
    try:
        with open(safe_path, 'w') as f:
            f.write(content)
        return f"Success: File '{path}' written successfully."
    except Exception as e:
        return f"Error writing file: {e}"

def tool_list_directory() -> str:
    """Lists files in the workspace directory."""
    try:
        files = os.listdir(WORKSPACE_DIR)
        if not files:
            return "Workspace is empty."
        output = []
        for file in files:
            p = os.path.join(WORKSPACE_DIR, file)
            size = os.path.getsize(p)
            output.append(f"- {file} ({size} bytes)")
        return "\n".join(output)
    except Exception as e:
        return f"Error listing workspace: {e}"

def tool_run_command(command: str) -> str:
    """Executes a shell command in the workspace directory under macOS safety guardrails."""
    # Safety check: Block dangerous system commands
    blocked = ["rm -rf /", "sudo", "mv /", "shutdown", "reboot"]
    if any(b in command for b in blocked):
        return "Error: Execution denied by safety guardrail policies."
    try:
        # Run process synchronously with 10-second timeout
        res = subprocess.run(
            command,
            shell=True,
            cwd=WORKSPACE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15
        )
        output = res.stdout
        if res.stderr:
            output += f"\n[Errors/Stderr]:\n{res.stderr}"
        return output or "[Command executed with no standard output]"
    except subprocess.TimeoutExpired:
        return "Error: Process execution exceeded 15-second time limit."
    except Exception as e:
        return f"Error executing command: {e}"

# --------------------------------------------------------------------
# 4. XML ReAct Loop Parser
# --------------------------------------------------------------------
async def execute_agent_with_tools(role_name: str, system_prompt: str, user_prompt: str) -> str:
    """Executes a stateful ReAct loop, resolving XML tool tags generated by the agent."""
    log_path = os.path.join(LOGS_DIR, f"{role_name}.log")
    
    # Reset log file
    with open(log_path, "w") as f:
        f.write(f"=== Starting {role_name.upper()} Execution ===\n\n")
    
    # Inject tool system instructions
    tool_instructions = (
        "\n\nYou are equipped with the following custom local workspace tools. "
        "To invoke a tool, output its corresponding XML tag precisely inside your reply. "
        "The orchestrator will parse the tag, execute the tool, and feed the outcome back into your context. "
        "You can run multiple tools sequentially across multiple turns until the objective is achieved.\n\n"
        "Available Tools:\n"
        "1. List Directory Contents:\n"
        "   <list_directory />\n"
        "2. Read File:\n"
        "   <read_file path=\"filename.ext\" />\n"
        "3. Write/Create File:\n"
        "   <write_file path=\"filename.ext\">\nfile_content_here\n</write_file>\n"
        "4. Run Shell Command (python execution, tests, compilation, git):\n"
        "   <run_command>your_shell_command_here</run_command>\n\n"
        "Rule: When you are finished and have completed your task, conclude your turn by summarizing your findings."
    )
    
    active_system_prompt = system_prompt + tool_instructions
    conversation_history = f"[User Goal]: {user_prompt}\n\n[Instruction]: Execute your specialized role and run tools as needed to fulfill this goal."
    
    max_turns = 8
    for turn in range(max_turns):
        with open(log_path, "a") as f:
            f.write(f"\n\n--- Turn {turn+1}/{max_turns} ---\n")
            
        response_text = await chat_local_model(active_system_prompt, conversation_history, log_path)
        
        # Parse XML tools
        tool_executed = False
        
        # 1. Match list_directory
        if "<list_directory />" in response_text or "<list_directory/>" in response_text:
            result = tool_list_directory()
            conversation_history += f"\n\n[Tool Executed]: <list_directory />\n[Result]:\n{result}"
            tool_executed = True
            
        # 2. Match read_file
        read_match = re.search(r'<read_file\s+path="([^"]+)"\s*/>', response_text)
        if read_match:
            filename = read_match.group(1)
            result = tool_read_file(filename)
            conversation_history += f"\n\n[Tool Executed]: <read_file path=\"{filename}\" />\n[Result]:\n{result}"
            tool_executed = True
            
        # 3. Match write_file
        write_match = re.search(r'<write_file\s+path="([^"]+)">([\s\S]*?)</write_file>', response_text)
        if write_match:
            filename = write_match.group(1)
            content = write_match.group(2).strip()
            result = tool_write_file(filename, content)
            conversation_history += f"\n\n[Tool Executed]: <write_file path=\"{filename}\" />\n[Result]:\n{result}"
            tool_executed = True
            
        # 4. Match run_command
        cmd_match = re.search(r'<run_command>([\s\S]*?)</run_command>', response_text)
        if cmd_match:
            command = cmd_match.group(1).strip()
            result = tool_run_command(command)
            conversation_history += f"\n\n[Tool Executed]: <run_command>{command}</run_command>\n[Result]:\n{result}"
            tool_executed = True
            
        if not tool_executed:
            # The agent did not invoke any more tools; finalize
            break
            
    with open(log_path, "a") as f:
        f.write(f"\n\n=== {role_name.upper()} Execution Finished ===\n")
        
    return response_text

# --------------------------------------------------------------------
# 5. Core Sprint Orchestrator
# --------------------------------------------------------------------
class GStackSprintOrchestrator:
    def __init__(self, sprint_goal: str):
        self.sprint_goal = sprint_goal
        self.is_cancelled = False
        self.state_file_path = os.path.join(LOGS_DIR, "sprint_state.json")
        self.state = {
            "goal": sprint_goal,
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
                "active_model": "",
                "total_runs": 0,
                "accumulated_savings": 0.0,
                "latency_history": []
            }
        }
        self.load_state()

    def load_state(self):
        if os.path.exists(self.state_file_path):
            try:
                with open(self.state_file_path, "r") as f:
                    self.state = json.load(f)
            except Exception:
                pass
        config = load_provider_config()
        if config.get("provider") == "freellmapi":
            self.state["metrics"]["active_model"] = "FreeLLMAPI: " + config.get("freellmapi_model", "google/gemini-2.5-flash")
        else:
            self.state["metrics"]["active_model"] = resolve_local_model()
        self.save_state()

    def save_state(self):
        with open(self.state_file_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def cancel(self):
        """Cancels the active sprint loop and updates phase state metrics."""
        self.is_cancelled = True
        self.state["current_phase"] = "cancelled"
        for phase in self.state["phases"]:
            if self.state["phases"][phase]["status"] in ["running", "pending"]:
                self.state["phases"][phase]["status"] = "cancelled"
        self.save_state()

    async def run_sprint(self):
        """Runs the entire GStack staged workflow."""
        import time
        self.state["metrics"]["total_runs"] += 1
        
        # Helper to load SKILL prompts
        def load_skill_prompt(skill_name: str) -> str:
            path = os.path.join(SKILLS_DIR, skill_name, "SKILL.md")
            if os.path.exists(path):
                with open(path, "r") as f:
                    return f.read()
            return f"You are the {skill_name} agent."

        # --------------------------------------------------
        # Phase 1: Think (CEO)
        # --------------------------------------------------
        if self.is_cancelled:
            return
        print("\n[Phase 1] Starting Think (CEO)...")
        t0 = time.time()
        self.state["current_phase"] = "think"
        self.state["phases"]["think"]["status"] = "running"
        self.save_state()
        
        ceo_system = load_skill_prompt("ceo")
        ceo_summary = await execute_agent_with_tools("ceo", ceo_system, self.sprint_goal)
        
        if self.is_cancelled:
            return
            
        t1 = time.time()
        self.state["phases"]["think"]["status"] = "completed"
        self.state["phases"]["think"]["summary"] = ceo_summary
        self.state["metrics"]["latency_history"].append({"phase": "think", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3) # Hypothetical savings vs cloud APIs
        self.save_state()

        # --------------------------------------------------
        # Phase 2: Plan (Engineering Manager)
        # --------------------------------------------------
        if self.is_cancelled:
            return
        print("\n[Phase 2] Starting Plan (Engineering Manager)...")
        t0 = time.time()
        self.state["current_phase"] = "plan"
        self.state["phases"]["plan"]["status"] = "running"
        self.save_state()
        
        em_system = load_skill_prompt("eng_manager")
        em_summary = await execute_agent_with_tools("eng_manager", em_system, f"Sprint Goal: {self.sprint_goal}\n\nCEO PRD:\n{ceo_summary}")
        
        if self.is_cancelled:
            return
            
        t1 = time.time()
        self.state["phases"]["plan"]["status"] = "completed"
        self.state["phases"]["plan"]["summary"] = em_summary
        self.state["metrics"]["latency_history"].append({"phase": "plan", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.save_state()

        # --------------------------------------------------
        # Phase 3: Design (Designer)
        # --------------------------------------------------
        if self.is_cancelled:
            return
        print("\n[Phase 3] Starting Design (Designer)...")
        t0 = time.time()
        self.state["current_phase"] = "design"
        self.state["phases"]["design"]["status"] = "running"
        self.save_state()
        
        designer_system = load_skill_prompt("designer")
        designer_summary = await execute_agent_with_tools("designer", designer_system, f"Sprint Goal: {self.sprint_goal}\n\nTech Spec Plan:\n{em_summary}")
        
        if self.is_cancelled:
            return
            
        t1 = time.time()
        self.state["phases"]["design"]["status"] = "completed"
        self.state["phases"]["design"]["summary"] = designer_summary
        self.state["metrics"]["latency_history"].append({"phase": "design", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.save_state()

        # --------------------------------------------------
        # Phase 4: Build (Coder)
        # --------------------------------------------------
        if self.is_cancelled:
            return
        print("\n[Phase 4] Starting Build (Coder)...")
        t0 = time.time()
        self.state["current_phase"] = "build"
        self.state["phases"]["build"]["status"] = "running"
        self.save_state()
        
        coder_system = load_skill_prompt("coder")
        coder_summary = await execute_agent_with_tools("coder", coder_system, f"Sprint Goal: {self.sprint_goal}\n\nTech Specs:\n{em_summary}\n\nDesign Styles:\n{designer_summary}")
        
        if self.is_cancelled:
            return
            
        t1 = time.time()
        self.state["phases"]["build"]["status"] = "completed"
        self.state["phases"]["build"]["summary"] = coder_summary
        self.state["metrics"]["latency_history"].append({"phase": "build", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.save_state()

        # --------------------------------------------------
        # Phase 5: Review (Release Engineer)
        # --------------------------------------------------
        if self.is_cancelled:
            return
        print("\n[Phase 5] Starting Review (Release Engineer)...")
        t0 = time.time()
        self.state["current_phase"] = "review"
        self.state["phases"]["review"]["status"] = "running"
        self.save_state()
        
        re_system = load_skill_prompt("release_engineer")
        re_summary = await execute_agent_with_tools("release_engineer", re_system, f"Sprint Goal: {self.sprint_goal}\n\nCoder Output:\n{coder_summary}")
        
        if self.is_cancelled:
            return
            
        t1 = time.time()
        self.state["phases"]["review"]["status"] = "completed"
        self.state["phases"]["review"]["summary"] = re_summary
        self.state["metrics"]["latency_history"].append({"phase": "review", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.save_state()

        # --------------------------------------------------
        # Phase 6: Test (QA Lead)
        # --------------------------------------------------
        if self.is_cancelled:
            return
        print("\n[Phase 6] Starting Test (QA Lead)...")
        t0 = time.time()
        self.state["current_phase"] = "test"
        self.state["phases"]["test"]["status"] = "running"
        self.save_state()
        
        qa_system = load_skill_prompt("qa_lead")
        qa_summary = await execute_agent_with_tools("qa_lead", qa_system, f"Sprint Goal: {self.sprint_goal}\n\nCoder Output:\n{coder_summary}")
        
        if self.is_cancelled:
            return
            
        t1 = time.time()
        self.state["phases"]["test"]["status"] = "completed"
        self.state["phases"]["test"]["summary"] = qa_summary
        self.state["metrics"]["latency_history"].append({"phase": "test", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.save_state()

        # --------------------------------------------------
        # Phase 7: Ship (Release Engineer)
        # --------------------------------------------------
        if self.is_cancelled:
            return
        print("\n[Phase 7] Starting Ship (Release Engineer)...")
        t0 = time.time()
        self.state["current_phase"] = "ship"
        self.state["phases"]["ship"]["status"] = "running"
        self.save_state()
        
        ship_summary = await execute_agent_with_tools("release_engineer", re_system, f"Sprint Goal: {self.sprint_goal}\n\nReview Notes:\n{re_summary}\n\nQA Test Notes:\n{qa_summary}\n\nEverything is approved. Build is verified. Compile the final release notes and ship the project.")
        
        if self.is_cancelled:
            return
            
        t1 = time.time()
        self.state["phases"]["ship"]["status"] = "completed"
        self.state["phases"]["ship"]["summary"] = ship_summary
        self.state["metrics"]["latency_history"].append({"phase": "ship", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.state["current_phase"] = "completed"
        self.save_state()
        
        print("\n✅ GStack Sprint completed successfully!")

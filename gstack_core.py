import os
import re
import json
import asyncio
import urllib.request
import urllib.parse
import subprocess
from typing import Dict, Any, List, Tuple
import secrets
import time
import threading

def generate_trace_id() -> str:
    return secrets.token_hex(16)

def generate_span_id() -> str:
    return secrets.token_hex(8)

class GStackTracer:
    def __init__(self, endpoint: str = "http://localhost:6006/v1/traces"):
        self.endpoint = endpoint
        self.spans = []
        self.lock = threading.Lock()
        self.resource_attributes = [
            {"key": "service.name", "value": {"stringValue": "gstack-agents"}},
            {"key": "service.version", "value": {"stringValue": "1.0.0"}},
            {"key": "environment", "value": {"stringValue": "local"}}
        ]
        
    def add_span(self, trace_id: str, span_id: str, name: str, start_time_ns: int, end_time_ns: int, parent_span_id: str = None, attributes: dict = None, status_code: int = 1, error_message: str = None):
        span = {
            "traceId": trace_id,
            "spanId": span_id,
            "name": name,
            "kind": 1, # INTERNAL
            "startTimeUnixNano": str(start_time_ns),
            "endTimeUnixNano": str(end_time_ns),
            "attributes": self._format_attributes(attributes or {}),
            "status": {
                "code": status_code
            }
        }
        if parent_span_id:
            span["parentSpanId"] = parent_span_id
        if error_message:
            span["status"]["message"] = error_message
            
        with self.lock:
            self.spans.append(span)
            
    def _format_attributes(self, attrs: dict) -> list:
        formatted = []
        for k, v in attrs.items():
            if isinstance(v, bool):
                formatted.append({"key": k, "value": {"boolValue": v}})
            elif isinstance(v, int):
                formatted.append({"key": k, "value": {"intValue": str(v)}})
            elif isinstance(v, float):
                formatted.append({"key": k, "value": {"doubleValue": v}})
            else:
                formatted.append({"key": k, "value": {"stringValue": str(v)}})
        return formatted
        
    def export(self):
        with self.lock:
            if not self.spans:
                return
            spans_to_export = list(self.spans)
            self.spans.clear()
            
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": self.resource_attributes
                    },
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "gstack.core"
                            },
                            "spans": spans_to_export
                        }
                    ]
                }
            ]
        }
        
        def do_post():
            try:
                import urllib.request
                import json
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    self.endpoint,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=2) as resp:
                    pass
            except Exception:
                pass
                
        t = threading.Thread(target=do_post)
        t.daemon = True
        t.start()

global_tracer = GStackTracer()

from pydantic import BaseModel, Field
from typing import Optional, Literal

class AgentAction(BaseModel):
    thought: str = Field(..., description="Explain the reasoning behind this action.")
    tool: Literal["list_directory", "read_file", "write_file", "run_command", "finish"] = Field(..., description="The name of the tool to invoke.")
    path: Optional[str] = Field(None, description="The target file path for read_file or write_file.")
    content: Optional[str] = Field(None, description="The complete file content to write when using write_file.")
    command: Optional[str] = Field(None, description="The shell command string to run when using run_command.")

def parse_agent_action(text: str) -> AgentAction:
    """Resiliently extracts and parses an AgentAction Pydantic model from model text."""
    # Look for markdown JSON block
    json_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if json_block:
        candidate = json_block.group(1).strip()
    else:
        # Fallback: look for the first '{' and last '}'
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            candidate = text[start_idx:end_idx+1].strip()
        else:
            candidate = text.strip()
            
    # Clean trailing commas inside lists/objects
    candidate = re.sub(r',\s*([\]}])', r'\1', candidate)
    
    return AgentAction.model_validate_json(candidate)

import math

def clean_and_tokenize(text: str) -> List[str]:
    return re.findall(r'\b[a-z0-9]+\b', text.lower())

class LocalSemanticMemory:
    def __init__(self, storage_path: str):
        self.storage_path = storage_path
        self.memories = []
        self.load_memories()

    def load_memories(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    self.memories = json.load(f)
            except Exception:
                self.memories = []
        else:
            self.memories = []

    def save_memories(self):
        try:
            with open(self.storage_path, "w") as f:
                json.dump(self.memories, f, indent=2)
        except Exception as e:
            print(f"Error saving memories: {e}")

    def add_memory(self, content: str, metadata: dict = None):
        memory = {
            "content": content,
            "metadata": metadata or {},
            "timestamp": time.time()
        }
        self.memories.append(memory)
        self.save_memories()

    def search_memories(self, query: str, limit: int = 3) -> List[dict]:
        if not self.memories:
            return []
        
        query_tokens = clean_and_tokenize(query)
        if not query_tokens:
            return self.memories[:limit]

        num_docs = len(self.memories)
        doc_frequencies = {}
        for doc in self.memories:
            tokens = set(clean_and_tokenize(doc["content"]))
            for token in tokens:
                doc_frequencies[token] = doc_frequencies.get(token, 0) + 1

        idfs = {}
        for token, df in doc_frequencies.items():
            idfs[token] = math.log((1 + num_docs) / (1 + df)) + 1.0

        scores = []
        for idx, doc in enumerate(self.memories):
            tokens = clean_and_tokenize(doc["content"])
            if not tokens:
                scores.append((0.0, idx))
                continue
            
            tfs = {}
            for t in tokens:
                tfs[t] = tfs.get(t, 0) + 1
            
            doc_vector = {}
            for token, count in tfs.items():
                tf = count / len(tokens)
                idf = idfs.get(token, 0.0)
                doc_vector[token] = tf * idf
            
            query_vector = {}
            query_tfs = {}
            for t in query_tokens:
                query_tfs[t] = query_tfs.get(t, 0) + 1
            for token, count in query_tfs.items():
                if token in idfs:
                    query_vector[token] = (count / len(query_tokens)) * idfs[token]

            dot_product = 0.0
            for token, val in query_vector.items():
                if token in doc_vector:
                    dot_product += val * doc_vector[token]

            doc_magnitude = math.sqrt(sum(v*v for v in doc_vector.values()))
            query_magnitude = math.sqrt(sum(v*v for v in query_vector.values()))

            if doc_magnitude > 0 and query_magnitude > 0:
                similarity = dot_product / (doc_magnitude * query_magnitude)
            else:
                similarity = 0.0
            
            scores.append((similarity, idx))

        scores.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, idx in scores[:limit]:
            results.append({
                "content": self.memories[idx]["content"],
                "metadata": self.memories[idx]["metadata"],
                "timestamp": self.memories[idx]["timestamp"],
                "score": score
            })
        return results

def get_embedding(text: str) -> Optional[List[float]]:
    config = load_provider_config()
    provider = config.get("provider", "lm_studio")
    
    url = "http://localhost:1234/v1/embeddings"
    headers = {"Content-Type": "application/json"}
    model = "nomic-ai/nomic-embed-text-v1.5-GGUF"
    
    if provider in ["freellmapi", "cloud_first"]:
        base_url = config.get("freellmapi_url", "http://localhost:3001/v1").rstrip("/")
        url = f"{base_url}/embeddings"
        token = config.get("freellmapi_token", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        model = "text-embedding-004"
        
    payload = {
        "model": model,
        "input": text
    }
    
    try:
        import urllib.request
        import json
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            res = json.loads(response.read().decode("utf-8"))
            return res["data"][0]["embedding"]
    except Exception:
        return None

class QdrantClient:
    def __init__(self, url: str = "http://localhost:6333", collection_name: str = "gstack_memory"):
        self.url = url.rstrip("/")
        self.collection_name = collection_name
        
    def is_online(self) -> bool:
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.url}/collections", method="GET")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def init_collection(self, vector_size: int = 1536) -> bool:
        try:
            import urllib.request
            import json
            req = urllib.request.Request(f"{self.url}/collections/{self.collection_name}", method="GET")
            try:
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                pass
                
            payload = {
                "vectors": {
                    "size": vector_size,
                    "distance": "Cosine"
                }
            }
            req = urllib.request.Request(
                f"{self.url}/collections/{self.collection_name}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="PUT"
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except Exception as e:
            print(f"Error initializing Qdrant collection: {e}")
            return False

    def upsert_point(self, point_id: str, vector: List[float], payload: dict) -> bool:
        try:
            import urllib.request
            import json
            body = {
                "points": [
                    {
                        "id": point_id,
                        "vector": vector,
                        "payload": payload
                    }
                ]
            }
            req = urllib.request.Request(
                f"{self.url}/collections/{self.collection_name}/points",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="PUT"
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except Exception as e:
            print(f"Error upserting to Qdrant: {e}")
            return False

    def search_points(self, vector: List[float], limit: int = 3) -> List[dict]:
        try:
            import urllib.request
            import json
            body = {
                "vector": vector,
                "limit": limit,
                "with_payload": True
            }
            req = urllib.request.Request(
                f"{self.url}/collections/{self.collection_name}/points/search",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                results = []
                for hit in res.get("result", []):
                    results.append({
                        "content": hit.get("payload", {}).get("content", ""),
                        "metadata": hit.get("payload", {}).get("metadata", {}),
                        "timestamp": hit.get("payload", {}).get("timestamp", 0.0),
                        "score": hit.get("score", 0.0)
                    })
                return results
        except Exception as e:
            print(f"Error searching Qdrant: {e}")
            return []

class GStackMemoryManager:
    def __init__(self, storage_path: str = None):
        if not storage_path:
            storage_path = os.path.join("/Users/jack/Documents/gstack-agents/logs", "project_memory.json")
        self.local_mem = LocalSemanticMemory(storage_path)
        self.qdrant = QdrantClient()
        self.qdrant_initialized = False

    def add_memory(self, content: str, metadata: dict = None):
        self.local_mem.add_memory(content, metadata)
        if self.qdrant.is_online():
            vector = get_embedding(content)
            if vector:
                if not self.qdrant_initialized:
                    self.qdrant_initialized = self.qdrant.init_collection(len(vector))
                if self.qdrant_initialized:
                    import uuid
                    point_id = str(uuid.uuid4())
                    payload = {
                        "content": content,
                        "metadata": metadata or {},
                        "timestamp": time.time()
                    }
                    self.qdrant.upsert_point(point_id, vector, payload)

    def search_memories(self, query: str, limit: int = 3) -> List[dict]:
        if self.qdrant.is_online():
            vector = get_embedding(query)
            if vector:
                if not self.qdrant_initialized:
                    self.qdrant_initialized = self.qdrant.init_collection(len(vector))
                if self.qdrant_initialized:
                    results = self.qdrant.search_points(vector, limit)
                    if results:
                        return results
        return self.local_mem.search_memories(query, limit)

global_memory = GStackMemoryManager()

def load_webhook_config() -> dict:
    path = os.path.join("/Users/jack/Documents/gstack-agents/logs", "webhook_config.json")
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"slack_webhook": "", "whatsapp_webhook": ""}

def send_webhook_notification(command: str):
    config = load_webhook_config()
    slack_url = config.get("slack_webhook", "").strip()
    if not slack_url:
        return
    payload = {
        "text": f"🚨 *GStack Command Approval Required*\nAn agent is requesting execution of the following terminal command:\n`{command}`\n\nPlease approve or reject this command in your GStack Dashboard."
    }
    try:
        import urllib.request
        import json
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            slack_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            pass
    except Exception as e:
        print(f"Failed to send Slack webhook: {e}")

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
    """Hits the configured LLM endpoint (LM Studio or FreeLLMAPI) with real-time stream logging and fallback."""
    config = load_provider_config()
    provider = config.get("provider", "lm_studio")
    
    async def try_request(url: str, model_name: str, headers: dict) -> Tuple[bool, str]:
        payload = {
            "model": model_name,
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
                # Set a tight 8-second timeout for cloud connections to ensure rapid local fallback
                return urllib.request.urlopen(req, timeout=8)
                
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
            return True, "".join(full_response)
        except Exception as e:
            return False, str(e)

    # 1. Cloud routing (if 'freellmapi' or 'cloud_first')
    if provider in ["freellmapi", "cloud_first"]:
        base_url = config.get("freellmapi_url", "http://localhost:3001/v1").rstrip("/")
        cloud_url = f"{base_url}/chat/completions"
        cloud_model = config.get("freellmapi_model", "google/gemini-2.5-flash")
        cloud_token = config.get("freellmapi_token", "").strip()
        
        cloud_headers = {"Content-Type": "application/json"}
        if cloud_token:
            cloud_headers["Authorization"] = f"Bearer {cloud_token}"
            
        if provider == "cloud_first" and log_file_path:
            with open(log_file_path, "a") as f:
                f.write(f"\n[Attempting Cloud API: {cloud_model}...]\n")
                f.flush()
                
        success, res = await try_request(cloud_url, cloud_model, cloud_headers)
        if success:
            return res
            
        if provider == "freellmapi":
            error_msg = f"\n[LM Link Connection Failure: {res}]\n"
            if log_file_path:
                with open(log_file_path, "a") as f:
                    f.write(error_msg)
                    f.flush()
            return error_msg
            
        # cloud_first fallback
        fallback_msg = f"\n⚠️ [Cloud API Failed ({res}). Falling back to Local Offline Model...]\n"
        print(fallback_msg)
        if log_file_path:
            with open(log_file_path, "a") as f:
                f.write(fallback_msg)
                f.flush()
                
    # 2. Local routing (Direct 'lm_studio' or Fallback from 'cloud_first')
    local_model = resolve_local_model()
    local_url = "http://localhost:1234/v1/chat/completions"
    local_headers = {"Content-Type": "application/json"}
    
    if log_file_path:
        with open(log_file_path, "a") as f:
            f.write(f"\n[Using Local API: {local_model}...]\n")
            f.flush()
            
    success, res = await try_request(local_url, local_model, local_headers)
    if success:
        return res
    else:
        error_msg = f"\n[LM Link Connection Failure: {res}]\n"
        if log_file_path:
            with open(log_file_path, "a") as f:
                f.write(error_msg)
                f.flush()
        return error_msg

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
    """Writes a file in the workspace, preserving subdirectories safely."""
    norm = os.path.normpath(path).lstrip(os.sep)
    safe_path = os.path.join(WORKSPACE_DIR, norm)
    # Prevent path traversal outside the workspace
    if not os.path.abspath(safe_path).startswith(os.path.abspath(WORKSPACE_DIR) + os.sep):
        return f"Error: refusing to write outside workspace: {path}"
    try:
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w") as f:
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

async def tool_run_command(command: str) -> str:
    """Executes a shell command in the workspace directory under macOS safety guardrails and HITL approval."""
    # Safety check: Block dangerous system commands
    blocked = ["rm -rf /", "sudo", "mv /", "shutdown", "reboot"]
    if any(b in command for b in blocked):
        return "Error: Execution denied by safety guardrail policies."
        
    state_file_path = os.path.join(LOGS_DIR, "sprint_state.json")
    
    # 1. Update sprint state to waiting_for_approval
    state = {}
    if os.path.exists(state_file_path):
        try:
            with open(state_file_path, "r") as f:
                state = json.load(f)
        except Exception:
            pass
            
    state["approval_status"] = "waiting_for_approval"
    state["requested_command"] = command
    
    try:
        with open(state_file_path, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Error updating state file: {e}")
        
    # 2. Trigger Slack/WhatsApp webhook notifications
    send_webhook_notification(command)
    
    print(f"\n[HITL Gate] Command approval requested: {command}")
    
    # 3. Poll sprint_state.json for approval/rejection
    try:
        while True:
            await asyncio.sleep(0.5)
            
            if os.path.exists(state_file_path):
                try:
                    with open(state_file_path, "r") as f:
                        current_state = json.load(f)
                except Exception:
                    continue
                    
                # Check for cancellation
                if current_state.get("current_phase") == "cancelled":
                    return "Error: Sprint execution was cancelled."
                    
                status = current_state.get("approval_status", "waiting_for_approval")
                if status == "approved":
                    # Clear approval states
                    current_state["approval_status"] = ""
                    current_state["requested_command"] = ""
                    try:
                        with open(state_file_path, "w") as f:
                            json.dump(current_state, f, indent=2)
                    except Exception:
                        pass
                    break
                elif status == "rejected":
                    # Clear approval states
                    current_state["approval_status"] = ""
                    current_state["requested_command"] = ""
                    try:
                        with open(state_file_path, "w") as f:
                            json.dump(current_state, f, indent=2)
                    except Exception:
                        pass
                    return "Error: Command was explicitly REJECTED by the user via the Human-in-the-Loop gate."
    except Exception as e:
        return f"Error in approval check loop: {e}"
        
    # 4. If approved, run command
    try:
        # Run process in a separate thread so as not to block event loop
        loop = asyncio.get_event_loop()
        def run_proc():
            return subprocess.run(
                command,
                shell=True,
                cwd=WORKSPACE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15
            )
            
        res = await loop.run_in_executor(None, run_proc)
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
async def execute_agent_with_tools(role_name: str, system_prompt: str, user_prompt: str, trace_id: str = None, parent_span_id: str = None) -> str:
    """Executes a stateful ReAct loop, resolving XML tool tags generated by the agent with full tracing."""
    if not trace_id:
        trace_id = generate_trace_id()
        
    log_path = os.path.join(LOGS_DIR, f"{role_name}.log")
    
    # Reset log file
    with open(log_path, "w") as f:
        f.write(f"=== Starting {role_name.upper()} Execution ===\n\n")
    
    # Inject tool system instructions (Pydantic Action format)
    tool_instructions = (
        "\n\nYou are equipped with the following custom local workspace tools. "
        "To invoke a tool, you MUST output a single valid JSON block complying with the schema below. "
        "Do NOT output plain conversational text when calling tools; output ONLY the raw JSON block inside a markdown ```json ``` code block.\n\n"
        "Available Schema (AgentAction):\n"
        "{\n"
        "  \"thought\": \"Detailed explanation of your reasoning behind this action.\",\n"
        "  \"tool\": \"list_directory\" | \"read_file\" | \"write_file\" | \"run_command\" | \"finish\",\n"
        "  \"path\": \"optional target file path (for read_file or write_file)\",\n"
        "  \"content\": \"optional complete file contents (for write_file)\",\n"
        "  \"command\": \"optional terminal shell command string (for run_command)\"\n"
        "}\n\n"
        "Available Tools:\n"
        "1. list_directory: Lists files in the active workspace.\n"
        "2. read_file: Reads a file from workspace (requires 'path').\n"
        "3. write_file: Writes complete file contents to workspace (requires 'path' and 'content').\n"
        "4. run_command: Runs a terminal shell command in the workspace (requires 'command').\n"
        "5. finish: Concludes your agent turn and summarizes final findings.\n\n"
        "Rule: Output your action in EXACT JSON structure inside markdown. Never output multiple JSON blocks. When complete, use 'finish'.\n\n"
        "==================================================\n"
        "🚨 DELIVERY CONTRACT (CRITICAL RULES FOR EVERY SPRINT):\n"
        "- This is an implementation sprint, not a planning phase. Producing only a PRD, spec, design, or README with no working code is a FAILED sprint.\n"
        "- Every sprint must end with a working, runnable artifact written to disk via write_file tool. Put it in a NEW, clearly named file (e.g., game.html, app/main.html). Never overwrite existing platform files (server.py, gstack_core.py, index.html, app.js).\n"
        "- Prefer a single self-contained file (inlined HTML/CSS/JS) with no external stubs, placeholders, TODOs, or truncated code.\n"
        "- Coder Agent MUST call write_file with full, complete contents, then verify by checking it's present and non-empty.\n"
        "- QA Lead/Reviewers MUST verify the file is present, functional, self-contained, and non-empty before finishing.\n"
        "==================================================\n"
    )
    
    active_system_prompt = system_prompt + tool_instructions
    conversation_history = f"[User Goal]: {user_prompt}\n\n[Instruction]: Execute your specialized role and run tools as needed to fulfill this goal."
    
    max_turns = 8
    for turn in range(max_turns):
        with open(log_path, "a") as f:
            f.write(f"\n\n--- Turn {turn+1}/{max_turns} ---\n")
            
        turn_start = time.time_ns()
        turn_span_id = generate_span_id()
        
        response_text = await chat_local_model(active_system_prompt, conversation_history, log_path)
        
        try:
            action = parse_agent_action(response_text)
        except Exception as e:
            # Self-healing parser feedback loop
            error_feedback = (
                f"\n\n[Parser Error]: Your output did not validate against the required JSON schema. Details: {e}\n"
                "Please output ONLY a valid JSON block complying strictly with the schema inside a markdown ```json ``` block."
            )
            conversation_history += error_feedback
            if log_path:
                with open(log_path, "a") as f:
                    f.write(f"\n[Parser Error: {e}]\n")
            # Log turn span with error status
            global_tracer.add_span(
                trace_id=trace_id,
                span_id=turn_span_id,
                name="llm.chat_completion",
                start_time_ns=turn_start,
                end_time_ns=time.time_ns(),
                parent_span_id=parent_span_id,
                attributes={
                    "agent.role": role_name,
                    "llm.turn": turn + 1,
                    "llm.error": str(e)
                },
                status_code=3, # ERROR
                error_message=str(e)
            )
            continue

        tool_executed = False
        tool_start = time.time_ns()
        tool_span_id = generate_span_id()
        
        # 1. list_directory
        if action.tool == "list_directory":
            result = tool_list_directory()
            tool_end = time.time_ns()
            global_tracer.add_span(
                trace_id=trace_id,
                span_id=tool_span_id,
                name="tool.list_directory",
                start_time_ns=tool_start,
                end_time_ns=tool_end,
                parent_span_id=turn_span_id,
                attributes={"tool.name": "list_directory", "tool.input": "", "tool.output": result},
                status_code=2
            )
            conversation_history += f"\n\n[Tool Executed]: list_directory\n[Result]:\n{result}"
            tool_executed = True
            
        # 2. read_file
        elif action.tool == "read_file":
            filename = action.path or ""
            if not filename:
                result = "Error: Missing target 'path' parameter for read_file."
            else:
                result = tool_read_file(filename)
                
            tool_end = time.time_ns()
            global_tracer.add_span(
                trace_id=trace_id,
                span_id=tool_span_id,
                name="tool.read_file",
                start_time_ns=tool_start,
                end_time_ns=tool_end,
                parent_span_id=turn_span_id,
                attributes={"tool.name": "read_file", "tool.input": filename, "tool.output": result},
                status_code=3 if result.startswith("Error:") else 2
            )
            conversation_history += f"\n\n[Tool Executed]: read_file (path=\"{filename}\")\n[Result]:\n{result}"
            tool_executed = True
            
        # 3. write_file
        elif action.tool == "write_file":
            filename = action.path or ""
            content = action.content or ""
            if not filename:
                result = "Error: Missing target 'path' parameter for write_file."
            else:
                result = tool_write_file(filename, content)
                
            tool_end = time.time_ns()
            global_tracer.add_span(
                trace_id=trace_id,
                span_id=tool_span_id,
                name="tool.write_file",
                start_time_ns=tool_start,
                end_time_ns=tool_end,
                parent_span_id=turn_span_id,
                attributes={
                    "tool.name": "write_file",
                    "tool.input": filename,
                    "file.path": filename,
                    "file.size": len(content),
                    "tool.output": result
                },
                status_code=3 if result.startswith("Error:") else 2
            )
            conversation_history += f"\n\n[Tool Executed]: write_file (path=\"{filename}\")\n[Result]:\n{result}"
            tool_executed = True
            
        # 4. run_command
        elif action.tool == "run_command":
            command = action.command or ""
            if not command:
                result = "Error: Missing 'command' parameter for run_command."
            else:
                result = await tool_run_command(command)
                
            tool_end = time.time_ns()
            global_tracer.add_span(
                trace_id=trace_id,
                span_id=tool_span_id,
                name="tool.run_command",
                start_time_ns=tool_start,
                end_time_ns=tool_end,
                parent_span_id=turn_span_id,
                attributes={"tool.name": "run_command", "tool.input": command, "command.output": result},
                status_code=3 if result.startswith("Error:") else 2
            )
            conversation_history += f"\n\n[Tool Executed]: run_command (\"{command}\")\n[Result]:\n{result}"
            tool_executed = True
            
        # 5. finish
        elif action.tool == "finish":
            tool_end = time.time_ns()
            global_tracer.add_span(
                trace_id=trace_id,
                span_id=tool_span_id,
                name="tool.finish",
                start_time_ns=tool_start,
                end_time_ns=tool_end,
                parent_span_id=turn_span_id,
                attributes={"tool.name": "finish", "tool.input": ""},
                status_code=2
            )
            tool_executed = False
            
        turn_end = time.time_ns()
        active_config = load_provider_config()
        if active_config.get("provider") in ["freellmapi", "cloud_first"]:
            model_used = "FreeLLMAPI: " + active_config.get("freellmapi_model", "google/gemini-2.5-flash")
        else:
            model_used = resolve_local_model()
            
        global_tracer.add_span(
            trace_id=trace_id,
            span_id=turn_span_id,
            name="llm.chat_completion",
            start_time_ns=turn_start,
            end_time_ns=turn_end,
            parent_span_id=parent_span_id,
            attributes={
                "agent.role": role_name,
                "llm.turn": turn + 1,
                "llm.model": model_used,
                "llm.prompt": conversation_history[:1000],
                "llm.response": response_text[:1000]
            },
            status_code=2
        )
        
        if not tool_executed and action.tool != "finish":
            if role_name == "coder" and turn == 0:
                conversation_history += (
                    "\n\n[Orchestrator]: You did not invoke any write_file action yet. You must write "
                    "the deliverable file using a valid JSON action block: { \"tool\": \"write_file\", ... }."
                )
                continue
            break
        elif action.tool == "finish":
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
        self.sprint_goal_original = sprint_goal
        self.is_cancelled = False
        self.trace_id = generate_trace_id()
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
        prov = config.get("provider")
        if prov == "freellmapi":
            self.state["metrics"]["active_model"] = "FreeLLMAPI: " + config.get("freellmapi_model", "google/gemini-2.5-flash")
        elif prov == "cloud_first":
            self.state["metrics"]["active_model"] = "Cloud First: " + config.get("freellmapi_model", "google/gemini-2.5-flash")
        else:
            self.state["metrics"]["active_model"] = resolve_local_model()
        self.save_state()

    def save_state(self):
        with open(self.state_file_path, "w") as f:
            json.dump(self.state, f, indent=2)

    def notify_completion(self, status: str, summary: str, deliverable: str = None):
        try:
            import urllib.request
            import json
            url = "http://127.0.0.1:9000/api/sprint/notify"
            payload = {
                "status": status,
                "goal": self.sprint_goal,
                "summary": summary
            }
            if deliverable:
                payload["deliverable"] = deliverable
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            # Standard urllib request with short timeout
            with urllib.request.urlopen(req, timeout=3) as resp:
                pass
        except Exception as e:
            print(f"Failed to send sprint completion notification: {e}")

    def cancel(self):
        """Cancels the active sprint loop and updates phase state metrics."""
        self.is_cancelled = True
        self.state["current_phase"] = "cancelled"
        for phase in self.state["phases"]:
            if self.state["phases"][phase]["status"] in ["running", "pending"]:
                self.state["phases"][phase]["status"] = "cancelled"
        self.save_state()

    async def run_sprint(self):
        """Runs the entire GStack staged workflow with native OTel tracing."""
        import time
        self.state["metrics"]["total_runs"] += 1
        
        # Query memory bank for previous relevant sprints
        try:
            memories = global_memory.search_memories(self.sprint_goal, limit=3)
            if memories:
                memory_context = "\n=== HYBRID MEMORY BANK RETRIEVED CONTEXT ===\n"
                for m in memories:
                    score = m.get("score", 0.0)
                    memory_context += f"- [Memory (Relevance: {score:.2f})]: {m['content']}\n"
                memory_context += "============================================\n\n"
                self.sprint_goal = memory_context + self.sprint_goal
        except Exception as e:
            print(f"Error retrieving memory: {e}")
        
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
            global_tracer.export()
            return
        print("\n[Phase 1] Starting Think (CEO)...")
        t0 = time.time()
        t0_ns = time.time_ns()
        phase_span_id = generate_span_id()
        
        self.state["current_phase"] = "think"
        self.state["phases"]["think"]["status"] = "running"
        self.save_state()
        
        ceo_system = load_skill_prompt("ceo")
        ceo_summary = await execute_agent_with_tools("ceo", ceo_system, self.sprint_goal, trace_id=self.trace_id, parent_span_id=phase_span_id)
        
        t1 = time.time()
        t1_ns = time.time_ns()
        
        global_tracer.add_span(
            trace_id=self.trace_id,
            span_id=phase_span_id,
            name="phase.think",
            start_time_ns=t0_ns,
            end_time_ns=t1_ns,
            attributes={"phase.name": "think", "agent.role": "ceo", "sprint.goal": self.sprint_goal},
            status_code=3 if self.is_cancelled else 2
        )
        
        if self.is_cancelled:
            global_tracer.export()
            return
            
        self.state["phases"]["think"]["status"] = "completed"
        self.state["phases"]["think"]["summary"] = ceo_summary
        self.state["metrics"]["latency_history"].append({"phase": "think", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.save_state()

        # --------------------------------------------------
        # Phase 2: Plan (Engineering Manager)
        # --------------------------------------------------
        if self.is_cancelled:
            global_tracer.export()
            return
        print("\n[Phase 2] Starting Plan (Engineering Manager)...")
        t0 = time.time()
        t0_ns = time.time_ns()
        phase_span_id = generate_span_id()
        
        self.state["current_phase"] = "plan"
        self.state["phases"]["plan"]["status"] = "running"
        self.save_state()
        
        em_system = load_skill_prompt("eng_manager")
        em_summary = await execute_agent_with_tools("eng_manager", em_system, f"Sprint Goal: {self.sprint_goal}\n\nCEO PRD:\n{ceo_summary}", trace_id=self.trace_id, parent_span_id=phase_span_id)
        
        t1 = time.time()
        t1_ns = time.time_ns()
        
        global_tracer.add_span(
            trace_id=self.trace_id,
            span_id=phase_span_id,
            name="phase.plan",
            start_time_ns=t0_ns,
            end_time_ns=t1_ns,
            attributes={"phase.name": "plan", "agent.role": "eng_manager"},
            status_code=3 if self.is_cancelled else 2
        )
        
        if self.is_cancelled:
            global_tracer.export()
            return
            
        self.state["phases"]["plan"]["status"] = "completed"
        self.state["phases"]["plan"]["summary"] = em_summary
        self.state["metrics"]["latency_history"].append({"phase": "plan", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.save_state()
        self.notify_completion("planning_completed", em_summary)

        # --------------------------------------------------
        # Phase 3: Design (Designer)
        # --------------------------------------------------
        if self.is_cancelled:
            global_tracer.export()
            return
        print("\n[Phase 3] Starting Design (Designer)...")
        t0 = time.time()
        t0_ns = time.time_ns()
        phase_span_id = generate_span_id()
        
        self.state["current_phase"] = "design"
        self.state["phases"]["design"]["status"] = "running"
        self.save_state()
        
        designer_system = load_skill_prompt("designer")
        designer_summary = await execute_agent_with_tools("designer", designer_system, f"Sprint Goal: {self.sprint_goal}\n\nTech Spec Plan:\n{em_summary}", trace_id=self.trace_id, parent_span_id=phase_span_id)
        
        t1 = time.time()
        t1_ns = time.time_ns()
        
        global_tracer.add_span(
            trace_id=self.trace_id,
            span_id=phase_span_id,
            name="phase.design",
            start_time_ns=t0_ns,
            end_time_ns=t1_ns,
            attributes={"phase.name": "design", "agent.role": "designer"},
            status_code=3 if self.is_cancelled else 2
        )
        
        if self.is_cancelled:
            global_tracer.export()
            return
            
        self.state["phases"]["design"]["status"] = "completed"
        self.state["phases"]["design"]["summary"] = designer_summary
        self.state["metrics"]["latency_history"].append({"phase": "design", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.save_state()

        # --------------------------------------------------
        # Phase 4: Build (Coder)
        # --------------------------------------------------
        if self.is_cancelled:
            global_tracer.export()
            return
        print("\n[Phase 4] Starting Build (Coder)...")
        t0 = time.time()
        t0_ns = time.time_ns()
        phase_span_id = generate_span_id()
        
        self.state["current_phase"] = "build"
        self.state["phases"]["build"]["status"] = "running"
        self.save_state()
        
        coder_system = load_skill_prompt("coder")

        PROTECTED = {"server.py", "gstack_core.py", "index.html", "index.css",
                     "app.js", "requirements.txt"}

        def _workspace_snapshot():
            snap = {}
            for f in os.listdir(WORKSPACE_DIR):
                p = os.path.join(WORKSPACE_DIR, f)
                if os.path.isfile(p):
                    snap[f] = os.path.getsize(p)
            return snap

        before = _workspace_snapshot()

        coder_summary = ""
        max_build_attempts = 3
        for attempt in range(max_build_attempts):
            extra = "" if attempt == 0 else (
                "\n\nIMPORTANT: The previous attempt did NOT write any runnable file. "
                "You MUST emit a <write_file path=\"...\">...full code...</write_file> tag "
                "with the COMPLETE contents now. Do not just describe it."
            )
            coder_summary = await execute_agent_with_tools(
                "coder", coder_system,
                f"Sprint Goal: {self.sprint_goal}\n\nTech Specs:\n{em_summary}\n\n"
                f"Design Styles:\n{designer_summary}{extra}",
                trace_id=self.trace_id, parent_span_id=phase_span_id
            )

            after = _workspace_snapshot()
            new_files = [f for f in after
                         if f not in PROTECTED and not f.lower().endswith(".md")
                         and (f not in before or after[f] != before.get(f))
                         and after[f] > 0]
            if new_files:
                self.state["phases"]["build"]["deliverable"] = new_files[0]
                break
        else:
            self.state["phases"]["build"]["status"] = "failed"
            self.state["phases"]["build"]["error"] = (
                "Coder produced no runnable file (likely emitted prose instead of a "
                "<write_file> tag). Deliverable missing."
            )
            self.save_state()

        t1 = time.time()
        t1_ns = time.time_ns()
        
        global_tracer.add_span(
            trace_id=self.trace_id,
            span_id=phase_span_id,
            name="phase.build",
            start_time_ns=t0_ns,
            end_time_ns=t1_ns,
            attributes={"phase.name": "build", "agent.role": "coder"},
            status_code=3 if self.state["phases"]["build"]["status"] == "failed" else 2
        )

        if self.state["phases"]["build"]["status"] == "failed":
            self.state["current_phase"] = "failed"
            self.save_state()
            print("\n❌ Build failed. Stopping sprint execution.")
            self.notify_completion("failed", "Build phase failed because the coder did not produce a valid deliverable file.")
            global_tracer.export()
            return

        if self.is_cancelled:
            global_tracer.export()
            return
            
        self.state["phases"]["build"]["status"] = "completed"
        self.state["phases"]["build"]["summary"] = coder_summary
        self.state["metrics"]["latency_history"].append({"phase": "build", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.save_state()
        self.notify_completion("build_completed", coder_summary)

        # --------------------------------------------------
        # Phase 5: Review (Release Engineer)
        # --------------------------------------------------
        if self.is_cancelled:
            global_tracer.export()
            return
        print("\n[Phase 5] Starting Review (Release Engineer)...")
        t0 = time.time()
        t0_ns = time.time_ns()
        phase_span_id = generate_span_id()
        
        self.state["current_phase"] = "review"
        self.state["phases"]["review"]["status"] = "running"
        self.save_state()
        
        re_system = load_skill_prompt("release_engineer")
        re_summary = await execute_agent_with_tools("release_engineer", re_system, f"Sprint Goal: {self.sprint_goal}\n\nCoder Output:\n{coder_summary}", trace_id=self.trace_id, parent_span_id=phase_span_id)
        
        t1 = time.time()
        t1_ns = time.time_ns()
        
        global_tracer.add_span(
            trace_id=self.trace_id,
            span_id=phase_span_id,
            name="phase.review",
            start_time_ns=t0_ns,
            end_time_ns=t1_ns,
            attributes={"phase.name": "review", "agent.role": "release_engineer"},
            status_code=3 if self.is_cancelled else 2
        )
        
        if self.is_cancelled:
            global_tracer.export()
            return
            
        self.state["phases"]["review"]["status"] = "completed"
        self.state["phases"]["review"]["summary"] = re_summary
        self.state["metrics"]["latency_history"].append({"phase": "review", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.save_state()

        # --------------------------------------------------
        # Phase 6: Test (QA Lead)
        # --------------------------------------------------
        if self.is_cancelled:
            global_tracer.export()
            return
        print("\n[Phase 6] Starting Test (QA Lead)...")
        t0 = time.time()
        t0_ns = time.time_ns()
        phase_span_id = generate_span_id()
        
        self.state["current_phase"] = "test"
        self.state["phases"]["test"]["status"] = "running"
        self.save_state()
        
        qa_system = load_skill_prompt("qa_lead")
        qa_summary = await execute_agent_with_tools("qa_lead", qa_system, f"Sprint Goal: {self.sprint_goal}\n\nCoder Output:\n{coder_summary}", trace_id=self.trace_id, parent_span_id=phase_span_id)
        
        t1 = time.time()
        t1_ns = time.time_ns()
        
        global_tracer.add_span(
            trace_id=self.trace_id,
            span_id=phase_span_id,
            name="phase.test",
            start_time_ns=t0_ns,
            end_time_ns=t1_ns,
            attributes={"phase.name": "test", "agent.role": "qa_lead"},
            status_code=3 if self.is_cancelled else 2
        )
        
        if self.is_cancelled:
            global_tracer.export()
            return
            
        self.state["phases"]["test"]["status"] = "completed"
        self.state["phases"]["test"]["summary"] = qa_summary
        self.state["metrics"]["latency_history"].append({"phase": "test", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.save_state()

        # --------------------------------------------------
        # Phase 7: Ship (Release Engineer)
        # --------------------------------------------------
        if self.is_cancelled:
            global_tracer.export()
            return
        print("\n[Phase 7] Starting Ship (Release Engineer)...")
        t0 = time.time()
        t0_ns = time.time_ns()
        phase_span_id = generate_span_id()
        
        self.state["current_phase"] = "ship"
        self.state["phases"]["ship"]["status"] = "running"
        self.save_state()
        
        ship_summary = await execute_agent_with_tools("release_engineer", re_system, f"Sprint Goal: {self.sprint_goal}\n\nReview Notes:\n{re_summary}\n\nQA Test Notes:\n{qa_summary}\n\nEverything is approved. Build is verified. Compile the final release notes and ship the project.", trace_id=self.trace_id, parent_span_id=phase_span_id)
        
        t1 = time.time()
        t1_ns = time.time_ns()
        
        global_tracer.add_span(
            trace_id=self.trace_id,
            span_id=phase_span_id,
            name="phase.ship",
            start_time_ns=t0_ns,
            end_time_ns=t1_ns,
            attributes={"phase.name": "ship", "agent.role": "release_engineer"},
            status_code=3 if self.is_cancelled else 2
        )
        
        if self.is_cancelled:
            global_tracer.export()
            return
            
        self.state["phases"]["ship"]["status"] = "completed"
        self.state["phases"]["ship"]["summary"] = ship_summary
        self.state["metrics"]["latency_history"].append({"phase": "ship", "duration": round(t1 - t0, 1)})
        self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
        self.state["current_phase"] = "completed"
        self.save_state()
        
        print("\n✅ GStack Sprint completed successfully!")
        deliverable_file = self.state["phases"]["build"].get("deliverable")
        self.notify_completion("completed", ship_summary, deliverable=deliverable_file)
        
        # Save completion summary to Memory Bank
        try:
            memory_content = f"Sprint Goal: {self.sprint_goal_original}\nDeliverable: {deliverable_file}\nRelease Summary: {ship_summary}"
            global_memory.add_memory(memory_content, {"goal": self.sprint_goal_original, "deliverable": deliverable_file})
        except Exception as e:
            print(f"Error saving to memory bank: {e}")
            
        global_tracer.export()

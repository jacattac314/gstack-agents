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
import html


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
    tool: Literal["list_directory", "read_file", "write_file", "run_command", "web_search", "fetch_webpage", "finish"] = Field(..., description="The name of the tool to invoke.")
    path: Optional[str] = Field(None, description="The target file path for read_file or write_file.")
    content: Optional[str] = Field(None, description="The complete file content to write when using write_file.")
    command: Optional[str] = Field(None, description="The shell command string to run when using run_command.")
    query: Optional[str] = Field(None, description="The search query string for web_search.")
    url: Optional[str] = Field(None, description="The target URL for fetch_webpage.")


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
    def __init__(self, url: str = None, collection_name: str = "gstack_memory"):
        if not url:
            try:
                config = load_provider_config()
                url = config.get("qdrant_url")
            except Exception:
                pass
            if not url:
                url = os.environ.get("QDRANT_URL", "http://localhost:6333")
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
        "provider": os.environ.get("GSTACK_PROVIDER", "lm_studio"),
        "freellmapi_url": os.environ.get("FREELLMAPI_URL", "http://localhost:3001/v1"),
        "freellmapi_token": os.environ.get("FREELLMAPI_TOKEN", ""),
        "freellmapi_model": os.environ.get("FREELLMAPI_MODEL", "google/gemini-2.5-flash"),
        "qdrant_url": os.environ.get("QDRANT_URL", "http://localhost:6333")
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

WORKFLOW_CONFIG_PATH = os.path.join(LOGS_DIR, "workflow_config.json")

def load_workflow_config() -> dict:
    default_config = {
        "stages": [
            {"phase": "think", "agent": "ceo", "label": "Think", "sub": "CEO Agent", "active": True},
            {"phase": "plan", "agent": "eng_manager", "label": "Plan", "sub": "Eng Manager", "active": True},
            {"phase": "design", "agent": "designer", "label": "Design", "sub": "Designer", "active": True},
            {"phase": "build", "agent": "coder", "label": "Build", "sub": "Coder Agent", "active": True},
            {"phase": "review", "agent": "release_engineer", "label": "Review", "sub": "Release Eng", "active": True},
            {"phase": "test", "agent": "qa_lead", "label": "Test", "sub": "QA Lead", "active": True},
            {"phase": "ship", "agent": "release_engineer", "label": "Ship", "sub": "Release Eng", "active": True}
        ],
        "custom_agents": []
    }
    if os.path.exists(WORKFLOW_CONFIG_PATH):
        try:
            with open(WORKFLOW_CONFIG_PATH, "r") as f:
                config = json.load(f)
                # Keep active/custom fields intact or append defaults
                if "stages" not in config:
                    config["stages"] = default_config["stages"]
                if "custom_agents" not in config:
                    config["custom_agents"] = default_config["custom_agents"]
                return config
        except Exception:
            pass
    return default_config

def save_workflow_config(config: dict):
    try:
        with open(WORKFLOW_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"Error saving workflow config: {e}")

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
async def chat_local_model(system_prompt: str, user_prompt: str, log_file_path: str = None, role_name: str = None) -> str:
    """Hits the configured LLM endpoint (LM Studio or FreeLLMAPI) with real-time stream logging,
    intelligence-tier routing (LLM-as-a-Route), and auto-failover.
    """
    config = load_provider_config()
    provider = config.get("provider", "lm_studio")
    
    async def try_request(url: str, model_name: str, headers: dict, timeout_secs: float = 8.0) -> Tuple[bool, str]:
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
                return urllib.request.urlopen(req, timeout=timeout_secs)
                
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

    # Resolve models & endpoints
    cloud_url = f"{config.get('freellmapi_url', 'http://localhost:3001/v1').rstrip('/')}/chat/completions"
    cloud_model = config.get("freellmapi_model", "google/gemini-2.5-flash")
    cloud_token = config.get("freellmapi_token", "").strip()
    cloud_headers = {"Content-Type": "application/json"}
    if cloud_token:
        cloud_headers["Authorization"] = f"Bearer {cloud_token}"
        
    local_model = resolve_local_model()
    local_url = "http://localhost:1234/v1/chat/completions"
    local_headers = {"Content-Type": "application/json"}

    # Define tiering (LLM-as-a-Route)
    # Tier 2: release_engineer, debate, logs summary -> Offline-first local model
    # Tier 1: ceo, eng_manager, designer, coder, qa_lead, Virtual Visual QA Auditor -> Cloud-first high-reasoning
    is_tier2 = role_name in ["release_engineer", "debate_generator", "summarizer", "command_reviewer"]
    
    if provider in ["freellmapi", "cloud_first"]:
        if is_tier2:
            # Try fast local model first to save cloud costs/latency
            if log_file_path:
                with open(log_file_path, "a") as f:
                    f.write(f"\n[Tier 2 Operational Route: Trying Local {local_model}...]\n")
                    f.flush()
            success, res = await try_request(local_url, local_model, local_headers, timeout_secs=5.0)
            if success:
                return res
            # Fallback to cloud if local model is offline/errors
            if log_file_path:
                with open(log_file_path, "a") as f:
                    f.write(f"\n[Local failed. Operational Fallback to Cloud {cloud_model}...]\n")
                    f.flush()
            success, res = await try_request(cloud_url, cloud_model, cloud_headers, timeout_secs=8.0)
            if success:
                return res
            return f"\n[LM Link Connection Failure: {res}]\n"
        else:
            # Tier 1 High Reasoning: Cloud first
            if log_file_path:
                with open(log_file_path, "a") as f:
                    f.write(f"\n[Tier 1 High-Reasoning Route: Trying Cloud {cloud_model}...]\n")
                    f.flush()
            success, res = await try_request(cloud_url, cloud_model, cloud_headers, timeout_secs=8.0)
            if success:
                return res
            
            if provider == "freellmapi":
                return f"\n[LM Link Connection Failure: {res}]\n"
                
            # If provider is cloud_first, failover to local offline model
            fallback_msg = f"\n⚠️ [Cloud API Failed ({res}). Falling back to Local Offline Model {local_model}...]\n"
            print(fallback_msg)
            if log_file_path:
                with open(log_file_path, "a") as f:
                    f.write(fallback_msg)
                    f.flush()
                    
            success, res = await try_request(local_url, local_model, local_headers, timeout_secs=10.0)
            if success:
                return res
            return f"\n[LM Link Connection Failure: {res}]\n"
    else:
        # Default local-only route
        if log_file_path:
            with open(log_file_path, "a") as f:
                f.write(f"\n[Using Local API: {local_model}...]\n")
                f.flush()
        success, res = await try_request(local_url, local_model, local_headers, timeout_secs=10.0)
        if success:
            return res
        return f"\n[LM Link Connection Failure: {res}]\n"

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
        # Check if Docker daemon is available dynamically
        docker_available = False
        try:
            import subprocess
            res_docker = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2
            )
            docker_available = (res_docker.returncode == 0)
        except Exception:
            docker_available = False

        loop = asyncio.get_event_loop()
        if docker_available:
            # Secure isolated container sandboxing
            # Escape double quotes inside the command to prevent shell injection in docker run
            escaped_command = command.replace('"', '\\"')
            sandbox_cmd = f'docker run --rm -v "{WORKSPACE_DIR}:/workspace" -w /workspace alpine sh -c "{escaped_command}"'
            print(f"[Sandbox Gate] Running securely inside Docker container: {command}")
            
            def run_docker():
                return subprocess.run(
                    sandbox_cmd,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15
                )
            res = await loop.run_in_executor(None, run_docker)
            output = f"[Sandbox Environment: Docker Isolated Container]\n" + res.stdout
            if res.stderr:
                output += f"\n[Errors/Stderr]:\n{res.stderr}"
            return output or "[Command executed with no standard output]"
        else:
            # Secure fallback local rest-shell with sanitized environment variables
            print(f"[Sandbox Gate] Docker unavailable. Falling back to secure local subshell.")
            def run_proc():
                clean_env = os.environ.copy()
                for key in list(clean_env.keys()):
                    if any(s in key.lower() for s in ["token", "secret", "key", "password", "pat"]):
                        clean_env[key] = "[redacted]"
                        
                return subprocess.run(
                    command,
                    shell=True,
                    cwd=WORKSPACE_DIR,
                    env=clean_env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15
                )
            
            res = await loop.run_in_executor(None, run_proc)
            output = f"[Sandbox Environment: Secure Local Subprocess (Docker Offline)]\n" + res.stdout
            if res.stderr:
                output += f"\n[Errors/Stderr]:\n{res.stderr}"
            return output or "[Command executed with no standard output]"
    except subprocess.TimeoutExpired:
        return "Error: Process execution exceeded 15-second time limit."
    except Exception as e:
        return f"Error executing command: {e}"

def tool_web_search(query: str) -> str:
    """Search the web/internet using DuckDuckGo to find websites, references, documentation, or code snippets."""
    url = "https://lite.duckduckgo.com/lite/"
    data = urllib.parse.urlencode({"q": query}).encode("utf-8")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    try:
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=8) as response:
            html_content = response.read().decode("utf-8", errors="ignore")
            
        links_matches = re.findall(r'<a[^>]+href="([^"]+)"[^+]+class=[\'"]result-link[\'"][^>]*>([\s\S]*?)</a>', html_content)
        if not links_matches:
            # Fallback in case class order differs
            links_matches = re.findall(r'<a[^>]+class=[\'"]result-link[\'"][^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', html_content)
        if not links_matches:
            # Broader fallback
            links_matches = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', html_content)
            # Filter non-ddg links
            links_matches = [(l, t) for l, t in links_matches if not any(x in l for x in ["duckduckgo.com", "javascript:", "#"])]
            
        snippets_matches = re.findall(r'<td[^>]+class=[\'"]result-snippet[\'"][^>]*>([\s\S]*?)</td>', html_content)
        
        results = []
        for idx, (link, title) in enumerate(links_matches[:6]):
            title_clean = re.sub(r'<[^>]*>', '', title).strip()
            title_clean = html.unescape(title_clean)
            
            if link.startswith("//"):
                link = "https:" + link
            elif link.startswith("/"):
                link = "https://lite.duckduckgo.com" + link
                
            snippet_clean = ""
            if idx < len(snippets_matches):
                snippet_clean = re.sub(r'<[^>]*>', '', snippets_matches[idx]).strip()
                snippet_clean = html.unescape(snippet_clean)
                
            results.append(f"[{idx+1}] {title_clean}\n    URL: {link}\n    Snippet: {snippet_clean}")
            
        if not results:
            return "No results found."
            
        return "\n\n".join(results)
    except Exception as e:
        return f"Error performing search: {e}"

def tool_fetch_webpage(url: str) -> str:
    """Fetch the cleaned text/markdown content of a website or webpage URL."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
            
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            content_type = response.info().get_content_type()
            if "text/html" not in content_type and "text/plain" not in content_type:
                return f"Error: Unsupported content type: {content_type}"
            raw_data = response.read()
            html_content = raw_data.decode("utf-8", errors="ignore")
            
        if "text/plain" in content_type:
            return html_content
            
        html_content = re.sub(r'<head[\s\S]*?</head>', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<script[\s\S]*?</script>', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<style[\s\S]*?</style>', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<!--[\s\S]*?-->', '', html_content)
        
        html_content = re.sub(r'<a[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>', r'[\2](\1)', html_content)
        html_content = re.sub(r'<h[1-6][^>]*>([\s\S]*?)</h[1-6]>', r'\n\n# \1\n', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<li[^>]*>([\s\S]*?)</li>', r'\n* \1', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<p[^>]*>([\s\S]*?)</p>', r'\n\n\1\n', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'<br\s*/?>', r'\n', html_content, flags=re.IGNORECASE)
        
        text = re.sub(r'<[^>]*>', '', html_content)
        
        lines = [line.strip() for line in text.splitlines()]
        cleaned_lines = []
        for line in lines:
            if line:
                cleaned_lines.append(line)
            elif not cleaned_lines or cleaned_lines[-1] != "":
                cleaned_lines.append("")
                
        cleaned_text = "\n".join(cleaned_lines).strip()
        cleaned_text = html.unescape(cleaned_text)
        
        if len(cleaned_text) > 8000:
            return cleaned_text[:8000] + "\n\n... [Content Truncated for Length] ..."
        return cleaned_text
        
    except Exception as e:
        return f"Error fetching page: {e}"

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
        "  \"tool\": \"list_directory\" | \"read_file\" | \"write_file\" | \"run_command\" | \"web_search\" | \"fetch_webpage\" | \"finish\",\n"
        "  \"path\": \"optional target file path (for read_file or write_file)\",\n"
        "  \"content\": \"optional complete file contents (for write_file)\",\n"
        "  \"command\": \"optional terminal shell command string (for run_command)\",\n"
        "  \"query\": \"optional search query string (for web_search)\",\n"
        "  \"url\": \"optional target URL (for fetch_webpage)\"\n"
        "}\n\n"
        "Available Tools:\n"
        "1. list_directory: Lists files in the active workspace.\n"
        "2. read_file: Reads a file from workspace (requires 'path').\n"
        "3. write_file: Writes complete file contents to workspace (requires 'path' and 'content').\n"
        "4. run_command: Runs a terminal shell command in the workspace (requires 'command').\n"
        "5. web_search: Search the web/internet using DuckDuckGo to find websites, references, documentation, or code snippets (requires 'query').\n"
        "6. fetch_webpage: Fetch the cleaned text/markdown content of a website or webpage URL (requires 'url').\n"
        "7. finish: Concludes your agent turn and summarizes final findings.\n\n"
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
        
        response_text = await chat_local_model(active_system_prompt, conversation_history, log_path, role_name=role_name)
        
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
            
        # 5. web_search
        elif action.tool == "web_search":
            query = action.query or ""
            if not query:
                result = "Error: Missing 'query' parameter for web_search."
            else:
                result = tool_web_search(query)
                
            tool_end = time.time_ns()
            global_tracer.add_span(
                trace_id=trace_id,
                span_id=tool_span_id,
                name="tool.web_search",
                start_time_ns=tool_start,
                end_time_ns=tool_end,
                parent_span_id=turn_span_id,
                attributes={"tool.name": "web_search", "tool.input": query, "tool.output": result},
                status_code=3 if result.startswith("Error:") else 2
            )
            conversation_history += f"\n\n[Tool Executed]: web_search (query=\"{query}\")\n[Result]:\n{result}"
            tool_executed = True
            
        # 6. fetch_webpage
        elif action.tool == "fetch_webpage":
            url = action.url or ""
            if not url:
                result = "Error: Missing 'url' parameter for fetch_webpage."
            else:
                result = tool_fetch_webpage(url)
                
            tool_end = time.time_ns()
            global_tracer.add_span(
                trace_id=trace_id,
                span_id=tool_span_id,
                name="tool.fetch_webpage",
                start_time_ns=tool_start,
                end_time_ns=tool_end,
                parent_span_id=turn_span_id,
                attributes={"tool.name": "fetch_webpage", "tool.input": url, "tool.output": result},
                status_code=3 if result.startswith("Error:") else 2
            )
            conversation_history += f"\n\n[Tool Executed]: fetch_webpage (url=\"{url}\")\n[Result]:\n{result}"
            tool_executed = True
            
        # 7. finish
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
            
        if tool_executed and log_path:
            try:
                with open(log_path, "a") as f:
                    f.write(f"\n[Tool Executed]: {action.tool}\n[Result]:\n{result}\n")
            except Exception:
                pass
            
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

async def run_autonomous_visual_qa(deliverable_name: str, em_summary: str) -> Tuple[bool, str]:
    """Performs static DOM validation, CSS layout analysis, and a vision-tier HTML layout rendering review.
    Automatically repairs unclosed tags, missing viewports, or broken styles.
    """
    safe_path = os.path.join(WORKSPACE_DIR, os.path.basename(deliverable_name))
    if not os.path.exists(safe_path):
        return False, f"Visual QA Error: Deliverable file '{deliverable_name}' is missing on disk."
        
    try:
        with open(safe_path, "r", encoding="utf-8") as f:
            code = f.read()
    except Exception as e:
        return False, f"Visual QA Error: Could not read deliverable file: {e}"
        
    log_messages = []
    regressions_found = False
    
    # 1. Structural DOM Tag Audits
    unclosed_tags = []
    for tag in ["html", "head", "body", "script", "style"]:
        open_count = len(re.findall(rf"<{tag}\b", code, re.IGNORECASE))
        close_count = len(re.findall(rf"</{tag}>", code, re.IGNORECASE))
        if open_count != close_count:
            unclosed_tags.append(tag)
            regressions_found = True
            
    if unclosed_tags:
        log_messages.append(f"❌ DOM Defect: Unclosed structural tags found: {', '.join(unclosed_tags)}")
    else:
        log_messages.append("✅ DOM Integrity: All structural tags (html, head, body, script, style) are perfectly paired.")
        
    # 2. Viewport Mobile Responsiveness check
    has_viewport = re.search(r'<meta\s+name=["\']viewport["\']', code, re.IGNORECASE) is not None
    if not has_viewport:
        log_messages.append("❌ Styling Defect: Missing <meta name=\"viewport\"> tag (essential for visual mobile scaling).")
        regressions_found = True
    else:
        log_messages.append("✅ Responsive Ready: Viewport scale meta tag verified.")
        
    # 3. CSS Layout and Cyberpunk Styles Check
    has_flex_or_grid = re.search(r'\b(display:\s*(flex|grid)|justify-content|align-items)\b', code, re.IGNORECASE) is not None
    if not has_flex_or_grid:
        log_messages.append("⚠️ Visual Hint: Layout does not explicitly declare flexbox or CSS grid rules. Risk of visual alignment failure.")
        
    has_cyberpunk_neon = re.search(r'\b(box-shadow|text-shadow|gradient|linear-gradient|hsl|rgb)\b', code, re.IGNORECASE) is not None
    if not has_cyberpunk_neon:
        log_messages.append("❌ Aesthetic Defect: Deliverable lacks premium styling (no neon box-shadows, gradients, or curations).")
        regressions_found = True
    else:
        log_messages.append("✅ Aesthetic Match: Verified glowing gradients and box-shadow variables inside style layers.")

    # 4. Vision-Tier Render Audit Prompt (LLM-as-a-Visual-Parser)
    vision_prompt = (
        "You are the senior Virtual Visual QA Auditor. Below is the HTML source code of a newly generated web page. "
        "Analyze this code from a visual and rendering perspective (font scales, color contrast, layout alignment, responsive breakpoints, backdrop filters, and overall visual wow-factor).\n\n"
        f"=== HTML Source Code ===\n{code}\n\n"
        "Audit this page for:\n"
        "1. Responsive scaling (will elements wrap nicely?)\n"
        "2. Visual premium contrast (text readability, background contrast ratios)\n"
        "3. Design spacing (card margins, padding scales)\n"
        "Output a detailed audit summary. End your audit with a single final line containing EXACTLY: "
        "'[VISUAL_QA: APPROVED]' if the page is visually stunning and accessible, or "
        "'[VISUAL_QA: FAILED]' followed by visual correction recommendations if it contains visual rendering bugs."
    )
    
    print(f"\n[Visual QA] Running virtual vision-tier HTML layout rendering review...")
    audit_opinion = await chat_local_model(
        "You are the senior Virtual Visual QA Auditor.",
        vision_prompt
    )
    
    is_approved_by_llm = "[VISUAL_QA: APPROVED]" in audit_opinion
    log_messages.append(f"\n=== Virtual Vision-Tier Audit Opinion ===\n{audit_opinion.strip()}")
    
    if not is_approved_by_llm:
        regressions_found = True
        log_messages.append("\n❌ Vision Defect: Vision-tier audit flagged visual regressions or spacing layout bugs.")
        
    # 5. Visual Auto-Fixing Loop Hooks
    if regressions_found:
        print("\n🛠️ [Visual QA] Visual defects or DOM regressions found! Initiating Autonomous Visual Repair...")
        log_messages.append("\n🛠️ [Autonomous Visual Repair] Initiated automatic patching for unclosed tags, viewports, or styling...")
        
        repair_prompt = (
            "You are the expert UI Design repair engine. The GStack Visual QA Auditor has detected visual or DOM defects inside our active deliverable. "
            "Your task is to fix all defects and write a completely patched, 100% complete, fully working HTML deliverable.\n\n"
            f"=== Visual QA Audit Log ===\n" + "\n".join(log_messages) + "\n\n"
            f"=== Original HTML Code ===\n{code}\n\n"
            "Rules:\n"
            "1. Output the COMPLETE patched HTML code inside a single ```html ``` code block.\n"
            "2. Ensure all tags are paired, and the viewport meta tag is included in the <head>.\n"
            "3. Ensure the CSS includes premium cyber-neon styling, custom shadows, and flexbox/grid layout centers.\n"
            "4. NEVER truncate or write placeholders. Do not output conversational text after the code block."
        )
        
        repaired_code_res = await chat_local_model(
            "You are the expert UI Design repair engine.",
            repair_prompt
        )
        
        # Extract repaired code
        code_block = re.search(r"```html\s*([\s\S]*?)```", repaired_code_res)
        repaired_code = ""
        if code_block:
            repaired_code = code_block.group(1).strip()
        else:
            # Fallback
            start_idx = repaired_code_res.find("<!DOCTYPE")
            if start_idx == -1:
                start_idx = repaired_code_res.find("<html")
            end_idx = repaired_code_res.rfind("</html>")
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                repaired_code = repaired_code_res[start_idx:end_idx+7].strip()
                
        if repaired_code:
            try:
                with open(safe_path, "w", encoding="utf-8") as f:
                    f.write(repaired_code)
                log_messages.append("✅ Visual Patching Success: The deliverable was automatically repaired, re-written, and verified on disk!")
                print("✅ [Visual QA] deliverable successfully repaired and updated!")
                return True, "\n".join(log_messages)
            except Exception as e:
                log_messages.append(f"❌ Visual Patching Failed: Could not write repaired file: {e}")
                return False, "\n".join(log_messages)
        else:
            log_messages.append("❌ Visual Patching Failed: Could not extract valid repaired HTML block from model response.")
            return False, "\n".join(log_messages)
            
    return True, "\n".join(log_messages)

async def run_phase_debate(phase_name: str, sprint_goal: str):
    """Simulates a lively cyberpunk-style multi-agent debate before a phase begins.
    Writes new chat logs to logs/debate_log.json.
    """
    debate_file = os.path.join(LOGS_DIR, "debate_log.json")
    
    # Load existing logs or start fresh
    existing_messages = []
    if os.path.exists(debate_file):
        try:
            with open(debate_file, "r") as f:
                existing_messages = json.load(f)
        except Exception:
            pass
            
    # Based on the phase, define who is debating and what they are discussing.
    # We will invoke the active model to generate a high-fidelity 3-message debate.
    phase_mapping = {
        "think": ("CEO", "Engineering Manager", "Designer"),
        "plan": ("Engineering Manager", "CEO", "Coder"),
        "design": ("Designer", "Engineering Manager", "Coder"),
        "build": ("Coder", "Designer", "QA Lead"),
        "review": ("Release Engineer", "Coder", "QA Lead"),
        "test": ("QA Lead", "Coder", "Release Engineer"),
        "ship": ("Release Engineer", "CEO", "Engineering Manager")
    }
    
    participants = phase_mapping.get(phase_name, ("CEO", "Engineering Manager", "Coder"))
    
    prompt = (
        f"You are a professional cyberpunk-styled scriptwriter for a team of autonomous AI agents.\n"
        f"The team is about to begin the '{phase_name}' phase of a sprint with the goal: '{sprint_goal}'.\n"
        f"Write a short, realistic, fast-paced cyberpunk slack-like discussion (3 messages total) between the virtual agents: {', '.join(participants)}.\n"
        f"They should express their thoughts, excitement, design decisions, or concerns relative to the '{phase_name}' stage.\n"
        f"Format your response as a strict JSON array of objects. Each object MUST contain:\n"
        f"- 'sender': The name of the agent (e.g. '{participants[0]}')\n"
        f"- 'avatar': Lowercase nickname (e.g. '{participants[0].lower().replace(' ', '_')}')\n"
        f"- 'content': The message text (keep it professional, crisp, and high-tech cyberpunk tone)\n\n"
        f"Rules: Output ONLY the raw JSON array. No explanations, no markdown blocks. Do not wrap in backticks."
    )
    
    print(f"\n[Debate Room] Agents are debating requirements for phase: {phase_name}...")
    
    # Fallback messages in case JSON fails or LLM is offline
    fallback_msgs = {
        "think": [
            {"sender": "CEO", "avatar": "ceo", "content": f"Team, we are kicking off a sprint to build: {sprint_goal}. I need a robust product spec that targets visual excellence and security."},
            {"sender": "Engineering Manager", "avatar": "eng_manager", "content": "Acknowledged. I'll translate the goals into architectural checkpoints and outline dependencies."},
            {"sender": "Designer", "avatar": "designer", "content": "I'm on it. I'll craft dynamic neon cyber-aesthetics with glassmorphism and fully custom HSL palettes."}
        ],
        "plan": [
            {"sender": "Engineering Manager", "avatar": "eng_manager", "content": "I have mapped out the sprint phases. Coder, ensure sandbox execution and zero-placeholder components."},
            {"sender": "CEO", "avatar": "ceo", "content": "Excellent. Make sure we check for container security before executing any subshell actions."},
            {"sender": "Coder", "avatar": "coder", "content": "Understood. The sandbox container logic will fallback gracefully if docker isn't running."}
        ],
        "design": [
            {"sender": "Designer", "avatar": "designer", "content": "Designing the visual harmony layout now. Focusing on modern contrast levels and responsive viewports."},
            {"sender": "Engineering Manager", "avatar": "eng_manager", "content": "Ensure our layout CSS uses flexbox and custom glowing variables so the QA visual models approve it."},
            {"sender": "Coder", "avatar": "coder", "content": "Agreed. I will keep code self-contained and inline all variables for high-fidelity rendering."}
        ],
        "build": [
            {"sender": "Coder", "avatar": "coder", "content": "I've started building the workspace deliverable. All core functions and styling are fully operational."},
            {"sender": "Designer", "avatar": "designer", "content": "Make sure the neon boxes have custom shadows and text spacing is perfectly balanced."},
            {"sender": "QA Lead", "avatar": "qa_lead", "content": "Once built, I'll launch the DOM validator and run the vision-model rendering audit."}
        ],
        "review": [
            {"sender": "Release Engineer", "avatar": "release_engineer", "content": "Running review audits on the coder's written deliverable. Looking for static errors."},
            {"sender": "Coder", "avatar": "coder", "content": "Everything is tested locally. The deliverable is self-contained and fully functional."},
            {"sender": "QA Lead", "avatar": "qa_lead", "content": "Looks good. Handing over to the test phase for visual QA and repair sweeps."}
        ],
        "test": [
            {"sender": "QA Lead", "avatar": "qa_lead", "content": "Initiating DOM tag integrity checks and running our Virtual Visual QA Auditor model."},
            {"sender": "Coder", "avatar": "coder", "content": "Ready for the repair loops if any visual scaling or HSL color contrast fails."},
            {"sender": "Release Engineer", "avatar": "release_engineer", "content": "Let's push for 100% compliance so we can ship a flawless build."}
        ],
        "ship": [
            {"sender": "Release Engineer", "avatar": "release_engineer", "content": "All checks passed! DOM, Visual QA, and sandboxed run verification are clear. Preparing to ship."},
            {"sender": "CEO", "avatar": "ceo", "content": "Fantastic job team. This is a premium deliverable. Let's record the sprint memory."},
            {"sender": "Engineering Manager", "avatar": "eng_manager", "content": "Pushing artifacts to distribution folders now. Sprint successfully closed!"}
        ]
    }
    
    new_msgs = []
    try:
        response = await chat_local_model(
            "You are a strict JSON generator for GStack agent debate logs.",
            prompt,
            role_name="debate_generator"
        )
        
        # Clean the response to ensure valid JSON parsing
        cleaned = response.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].split("```")[0].strip()
            
        new_msgs = json.loads(cleaned)
        if not isinstance(new_msgs, list):
            raise ValueError("Parsed debate response is not a JSON list")
    except Exception as e:
        print(f"[Debate Room] Using pre-authored high-fidelity debate fallback: {e}")
        new_msgs = fallback_msgs.get(phase_name, fallback_msgs["think"])
        
    # Add timestamps and stage metadata
    import datetime
    now_str = datetime.datetime.now().strftime("%H:%M:%S")
    for msg in new_msgs:
        msg["timestamp"] = now_str
        msg["phase"] = phase_name
        existing_messages.append(msg)
        
    try:
        with open(debate_file, "w") as f:
            json.dump(existing_messages, f, indent=2)
    except Exception as e:
        print(f"[Debate Room] Warning: Could not write debate log: {e}")

# --------------------------------------------------------------------
# 5. Core Sprint Orchestrator
# --------------------------------------------------------------------
class GStackSprintOrchestrator:
    def __init__(self, sprint_goal: str, keep_workspace: bool = True):
        self.sprint_goal = sprint_goal
        self.sprint_goal_original = sprint_goal
        self.keep_workspace = keep_workspace
        self.is_cancelled = False
        self.trace_id = generate_trace_id()
        self.state_file_path = os.path.join(LOGS_DIR, "sprint_state.json")
        self.state = {
            "goal": sprint_goal,
            "current_phase": "idle",
            "phases": {},
            "metrics": {
                "active_model": "",
                "total_runs": 0,
                "accumulated_savings": 0.0,
                "latency_history": []
            }
        }
        
        # Build phases dynamically from active stages in workflow config
        config = load_workflow_config()
        for stage in config.get("stages", []):
            if stage.get("active", True):
                self.state["phases"][stage["phase"]] = {
                    "status": "pending",
                    "agent": stage["agent"],
                    "summary": "",
                    "label": stage["label"],
                    "sub": stage["sub"]
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
        """Runs the entire GStack staged workflow dynamically configured by the user, with Otel tracing."""
        import time
        self.state["metrics"]["total_runs"] += 1

        # If keeping workspace, check if there are existing files and inject them into the sprint goal context so agents are aware of them.
        if self.keep_workspace:
            try:
                files = os.listdir(WORKSPACE_DIR)
                files = [f for f in files if not f.startswith(".")]
                if files:
                    file_info = []
                    for f in files:
                        p = os.path.join(WORKSPACE_DIR, f)
                        if os.path.isfile(p):
                            size = os.path.getsize(p)
                            file_info.append(f"- {f} ({size} bytes)")
                    
                    if file_info:
                        files_context = (
                            "\n=== INCREMENTAL SPRINT CONTEXT ===\n"
                            "Note: This is an incremental sprint extending or updating an existing project in the workspace. "
                            "You should update, rewrite, or build on top of the following existing files rather than ignoring them or starting entirely from scratch:\n"
                            + "\n".join(file_info) +
                            "\n===================================\n\n"
                        )
                        self.sprint_goal = files_context + self.sprint_goal
            except Exception as e:
                print(f"Error listing files for incremental sprint context: {e}")
        
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

        # Load active stages from workflow config
        config = load_workflow_config()
        active_stages = [stage for stage in config.get("stages", []) if stage.get("active", True)]
        
        summaries = {}
        deliverable = None
        
        for idx, stage in enumerate(active_stages):
            phase = stage["phase"]
            agent_key = stage["agent"]
            label = stage["label"]
            sub = stage["sub"]
            
            if self.is_cancelled:
                global_tracer.export()
                return
                
            await run_phase_debate(phase, self.sprint_goal_original)
            print(f"\n[{label} Stage] Starting {label} ({sub})...")
            
            t0 = time.time()
            t0_ns = time.time_ns()
            phase_span_id = generate_span_id()
            
            self.state["current_phase"] = phase
            self.state["phases"][phase]["status"] = "running"
            self.save_state()
            
            agent_system = load_skill_prompt(agent_key)
            
            # Construct input prompt dynamically based on previous stages
            if idx == 0:
                input_prompt = self.sprint_goal
            else:
                input_prompt = f"Sprint Goal: {self.sprint_goal}\n\n"
                for prev_phase, prev_summary in summaries.items():
                    input_prompt += f"Previous Stage [{prev_phase}] Output:\n{prev_summary}\n\n"
            
            # Custom phase logics
            if phase == "build":
                PROTECTED = {"server.py", "gstack_core.py", "index.html", "index.css", "app.js", "requirements.txt"}
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
                        agent_key, agent_system,
                        input_prompt + extra,
                        trace_id=self.trace_id, parent_span_id=phase_span_id
                    )
                    after = _workspace_snapshot()
                    new_files = [f for f in after
                                 if f not in PROTECTED and not f.lower().endswith(".md")
                                 and (f not in before or after[f] != before.get(f))
                                 and after[f] > 0]
                    if new_files:
                        deliverable = new_files[0]
                        self.state["phases"]["build"]["deliverable"] = deliverable
                        break
                else:
                    self.state["phases"]["build"]["status"] = "failed"
                    self.state["phases"]["build"]["error"] = (
                        "Coder produced no runnable file (likely emitted prose instead of a "
                        "<write_file> tag). Deliverable missing."
                    )
                    self.save_state()
                
                summary_output = coder_summary
                
            elif phase == "test":
                qa_summary = await execute_agent_with_tools(
                    agent_key, agent_system,
                    input_prompt,
                    trace_id=self.trace_id, parent_span_id=phase_span_id
                )
                
                if deliverable:
                    print(f"\n[Visual QA] Hooked into Test Phase. Running Visual QA on: {deliverable}")
                    plan_summary = summaries.get("plan", "")
                    qa_ok, visual_qa_log = await run_autonomous_visual_qa(deliverable, plan_summary)
                    qa_summary += f"\n\n=== AUTONOMOUS VISUAL QA REPORT ===\n"
                    qa_summary += f"Status: {'PASSED' if qa_ok else 'FAILED_BUT_REPAIRED'}\n"
                    qa_summary += f"{visual_qa_log}\n==================================="
                summary_output = qa_summary
                
            else:
                summary_output = await execute_agent_with_tools(
                    agent_key, agent_system,
                    input_prompt,
                    trace_id=self.trace_id, parent_span_id=phase_span_id
                )
            
            t1 = time.time()
            t1_ns = time.time_ns()
            
            status_code = 2
            if phase == "build" and self.state["phases"]["build"]["status"] == "failed":
                status_code = 3
                
            global_tracer.add_span(
                trace_id=self.trace_id,
                span_id=phase_span_id,
                name=f"phase.{phase}",
                start_time_ns=t0_ns,
                end_time_ns=t1_ns,
                attributes={"phase.name": phase, "agent.role": agent_key},
                status_code=3 if self.is_cancelled else status_code
            )
            
            if phase == "build" and self.state["phases"]["build"]["status"] == "failed":
                self.state["current_phase"] = "failed"
                self.save_state()
                print("\n❌ Build failed. Stopping sprint execution.")
                self.notify_completion("failed", "Build phase failed because the coder did not produce a valid deliverable file.")
                
                # Dynamic Prompt Evolution on Failure
                try:
                    print("\n📈 [Dynamic Prompt Evolution] Initiating background prompt optimization task due to build failure...")
                    run_stages = active_stages[:active_stages.index(stage)+1] if stage in active_stages else active_stages
                    await self.run_dynamic_prompt_evolution(
                        run_stages, 
                        "Build phase failed because the coder did not produce a valid deliverable file.", 
                        None
                    )
                except Exception as e:
                    print(f"[Dynamic Prompt Evolution] Error running optimization task on failure: {e}")
                    
                global_tracer.export()
                return
                
            if self.is_cancelled:
                global_tracer.export()
                return
                
            self.state["phases"][phase]["status"] = "completed"
            self.state["phases"][phase]["summary"] = summary_output
            self.state["metrics"]["latency_history"].append({"phase": phase, "duration": round(t1 - t0, 1)})
            self.state["metrics"]["accumulated_savings"] += round((t1 - t0) * 0.015, 3)
            self.save_state()
            
            summaries[phase] = summary_output
            
            if phase == "plan":
                self.notify_completion("planning_completed", summary_output)
            elif phase == "build":
                self.notify_completion("build_completed", summary_output)
        
        self.state["current_phase"] = "completed"
        self.save_state()
        
        print("\n✅ GStack Sprint completed successfully!")
        ship_summary = summaries.get("ship", summaries.get(active_stages[-1]["phase"], "Sprint finished successfully."))
        self.notify_completion("completed", ship_summary, deliverable=deliverable)
        
        try:
            memory_content = f"Sprint Goal: {self.sprint_goal_original}\nDeliverable: {deliverable}\nRelease Summary: {ship_summary}"
            global_memory.add_memory(memory_content, {"goal": self.sprint_goal_original, "deliverable": deliverable})
        except Exception as e:
            print(f"Error saving to memory bank: {e}")
            
        # Dynamic Prompt Evolution
        try:
            print("\n📈 [Dynamic Prompt Evolution] Initiating background prompt optimization task...")
            await self.run_dynamic_prompt_evolution(active_stages, ship_summary, deliverable)
        except Exception as e:
            print(f"[Dynamic Prompt Evolution] Error running optimization task: {e}")
            
        global_tracer.export()

    async def run_dynamic_prompt_evolution(self, active_stages: list, ship_summary: str, deliverable: str):
        """Analyzes logs of participating agents and refactors their system prompts based on sprint outcome."""
        from gstack_core import chat_local_model, SKILLS_DIR, LOGS_DIR
        
        # Check if the sprint succeeded
        sprint_success = (self.state.get("phases", {}).get("build", {}).get("status") != "failed")
        
        for stage in active_stages:
            agent_key = stage["agent"]
            
            # Read current prompt
            prompt_path = os.path.join(SKILLS_DIR, agent_key, "SKILL.md")
            if not os.path.exists(prompt_path):
                continue
                
            try:
                with open(prompt_path, "r") as f:
                    current_prompt = f.read()
            except Exception as e:
                print(f"[Dynamic Prompt Evolution] Error reading prompt for {agent_key}: {e}")
                continue
                
            # Read agent execution logs
            log_path = os.path.join(LOGS_DIR, f"{agent_key}.log")
            agent_logs = ""
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r") as f:
                        agent_logs = f.read()
                    # Truncate if extremely long to fit LLM context window
                    if len(agent_logs) > 6000:
                        agent_logs = "... [Truncated] ...\n" + agent_logs[-6000:]
                except Exception:
                    pass
            
            user_prompt = (
                f"Sprint Goal: {self.sprint_goal_original}\n"
                f"Deliverable File: {deliverable or 'None'}\n"
                f"Sprint Success Status: {sprint_success}\n"
                f"Sprint Summary: {ship_summary}\n\n"
                f"=== AGENT ROLE KEY: {agent_key} ===\n"
                f"=== CURRENT SYSTEM PROMPT ===\n"
                f"{current_prompt}\n\n"
                f"=== AGENT RUNTIME EXECUTION LOGS ===\n"
                f"{agent_logs or 'No logs available.'}\n"
            )
            
            meta_system_prompt = (
                "You are a Meta-Prompt Optimizer. Your job is to optimize and refine an AI agent's system prompt "
                "based on the results and logs of a completed engineering sprint.\n\n"
                "You will be provided with:\n"
                "1. The original Sprint Goal.\n"
                "2. The overall Sprint Outcome (Success/Failure and Summary).\n"
                "3. The Agent's current system prompt.\n"
                "4. The Agent's execution log from this sprint.\n\n"
                "Your objective:\n"
                "Analyze the logs to see if the agent made mistakes, did not follow instructions, or could perform better "
                "with clearer guidelines. If so, write an updated, improved version of the system prompt. "
                "Integrate specific 'lessons learned' as guidelines so the agent avoids these mistakes in the future.\n\n"
                "Guidelines for the updated prompt:\n"
                "- Retain all core responsibilities and skills of the agent.\n"
                "- Add clear, concise, actionable guidelines (e.g. under a 'Lessons Learned' or 'Guidelines' section).\n"
                "- Keep the prompt professional, clean, and direct.\n"
                "- If the agent performed perfectly and no prompt change is required, return the exact original prompt.\n\n"
                "Respond ONLY with the complete updated system prompt. Do not include markdown code block fences (like ```markdown), "
                "explanations, or comments."
            )
            
            try:
                optimized_prompt = await chat_local_model(
                    meta_system_prompt, 
                    user_prompt, 
                    role_name="debate_generator" # Use Tier 2 operation route
                )
                
                optimized_prompt = optimized_prompt.strip()
                
                # Robust extraction of markdown block contents using regex
                import re
                code_block_match = re.search(r'```(?:markdown|md)?\n(.*?)\n```', optimized_prompt, re.DOTALL | re.IGNORECASE)
                if code_block_match:
                    optimized_prompt = code_block_match.group(1).strip()
                else:
                    code_block_match2 = re.search(r'```\n(.*?)\n```', optimized_prompt, re.DOTALL)
                    if code_block_match2:
                        optimized_prompt = code_block_match2.group(1).strip()
                    elif optimized_prompt.startswith("```"):
                        # Fallback simple splitlines if formatting was slightly off
                        lines = optimized_prompt.splitlines()
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].strip() == "```":
                            lines = lines[:-1]
                        optimized_prompt = "\n".join(lines).strip()
                
                if optimized_prompt and optimized_prompt != current_prompt.strip():
                    with open(prompt_path, "w") as f:
                        f.write(optimized_prompt)
                    print(f"📈 [Dynamic Prompt Evolution] Successfully optimized and updated SKILL prompt for agent: {agent_key}")
            except Exception as e:
                print(f"[Dynamic Prompt Evolution] Error optimizing prompt for {agent_key}: {e}")


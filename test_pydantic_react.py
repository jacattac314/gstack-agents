import os
import sys
import json
import asyncio
import unittest

# Adjust path to find gstack_core
sys.path.append("/Users/jack/Documents/gstack-agents")

from gstack_core import (
    parse_agent_action,
    AgentAction,
    LocalSemanticMemory,
    get_embedding,
    tool_run_command,
    LOGS_DIR
)

class TestGStackEngine(unittest.TestCase):
    
    # --------------------------------------------------
    # 1. Pydantic Action Parser Tests
    # --------------------------------------------------
    def test_clean_json_markdown(self):
        text = """Here is my action:
```json
{
  "thought": "Let's read the workspace configuration.",
  "tool": "read_file",
  "path": "server.py"
}
```
Is there anything else?"""
        action = parse_agent_action(text)
        self.assertEqual(action.tool, "read_file")
        self.assertEqual(action.path, "server.py")
        self.assertEqual(action.thought, "Let's read the workspace configuration.")

    def test_raw_json_no_markdown(self):
        text = """{
  "thought": "Conclude the sprint.",
  "tool": "finish"
}"""
        action = parse_agent_action(text)
        self.assertEqual(action.tool, "finish")
        self.assertIsNone(action.path)

    def test_trailing_comma_resilience(self):
        text = """```json
{
  "thought": "Running git status,",
  "tool": "run_command",
  "command": "git status",
}
```"""
        action = parse_agent_action(text)
        self.assertEqual(action.tool, "run_command")
        self.assertEqual(action.command, "git status")

    def test_schema_validation_failure(self):
        # Missing required field 'tool' or bad action name
        text = """```json
{
  "thought": "Invalid action name",
  "tool": "bad_tool_name"
}
```"""
        with self.assertRaises(Exception):
            parse_agent_action(text)

    # --------------------------------------------------
    # 2. Local TF-IDF Vector Memory Matcher Tests
    # --------------------------------------------------
    def test_local_semantic_tfidf_matcher(self):
        test_db_path = os.path.join(LOGS_DIR, "test_project_memory.json")
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
            
        try:
            mem = LocalSemanticMemory(test_db_path)
            
            # Store some unique sample memories
            mem.add_memory("Implement neon color timer countdown UI utilizing linear gradients", {"phase": "ship"})
            mem.add_memory("Setup local SQLite connection logic with transaction fallback", {"phase": "build"})
            mem.add_memory("Optimize LCP performance by inlining CSS styles", {"phase": "review"})
            
            self.assertEqual(len(mem.memories), 3)
            
            # Search query matching neon UI
            results = mem.search_memories("looking for neon gradient timer counts", limit=2)
            self.assertGreater(len(results), 0)
            # The first result must be the neon countdown UI
            self.assertIn("Implement neon color timer", results[0]["content"])
            self.assertGreater(results[0]["score"], 0.0)
            
            # Search query matching database sqlite
            results_db = mem.search_memories("sqlite fallback logic", limit=1)
            self.assertIn("SQLite connection", results_db[0]["content"])
            
        finally:
            if os.path.exists(test_db_path):
                os.remove(test_db_path)

    # --------------------------------------------------
    # 3. Human-in-the-Loop Gating Tests
    # --------------------------------------------------
    def test_hitl_approval_gate(self):
        state_file = os.path.join(LOGS_DIR, "sprint_state.json")
        
        # Backup existing state
        state_exists = os.path.exists(state_file)
        state_backup = None
        if state_exists:
            with open(state_file, "r") as f:
                state_backup = f.read()
                
        try:
            # 1. Reject Case Simulation
            async def run_reject_sim():
                # Write command approval, simulate background reject in 1s
                async def simulate_user_reject():
                    await asyncio.sleep(0.5)
                    with open(state_file, "r") as f:
                        s = json.load(f)
                    s["approval_status"] = "rejected"
                    with open(state_file, "w") as f:
                        json.dump(s, f, indent=2)
                
                t1 = asyncio.create_task(simulate_user_reject())
                res = await tool_run_command("echo 'gstack'")
                await t1
                return res
                
            res_reject = asyncio.run(run_reject_sim())
            self.assertIn("explicitly REJECTED by the user via the Human-in-the-Loop gate", res_reject)
            
            # 2. Approve Case Simulation
            async def run_approve_sim():
                async def simulate_user_approve():
                    await asyncio.sleep(0.5)
                    with open(state_file, "r") as f:
                        s = json.load(f)
                    s["approval_status"] = "approved"
                    with open(state_file, "w") as f:
                        json.dump(s, f, indent=2)
                
                t2 = asyncio.create_task(simulate_user_approve())
                res = await tool_run_command("echo 'GStack Engine Gated'")
                await t2
                return res
                
            res_approve = asyncio.run(run_approve_sim())
            self.assertIn("GStack Engine Gated", res_approve)
            
        finally:
            # Restore state backup
            if state_exists and state_backup:
                with open(state_file, "w") as f:
                    f.write(state_backup)
            elif os.path.exists(state_file):
                os.remove(state_file)

if __name__ == "__main__":
    unittest.main()

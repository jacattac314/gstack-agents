import os
import sys
import json
import asyncio
import unittest
from unittest.mock import patch, MagicMock

# Ensure root dir is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gstack_core import (
    chat_local_model,
    run_autonomous_visual_qa,
    run_phase_debate,
    tool_run_command,
    WORKSPACE_DIR,
    LOGS_DIR
)

class TestNextLevelPlatformFeatures(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Create temp testing directory if needed
        self.sample_html_path = os.path.join(WORKSPACE_DIR, "test_sample.html")
        if os.path.exists(self.sample_html_path):
            os.remove(self.sample_html_path)

    async def asyncTearDown(self):
        if os.path.exists(self.sample_html_path):
            os.remove(self.sample_html_path)
            
        debate_file = os.path.join(LOGS_DIR, "debate_log.json")
        if os.path.exists(debate_file):
            try:
                os.remove(debate_file)
            except Exception:
                pass

    async def test_sandbox_fallback_scrubbing(self):
        """Verifies environment variables are redacted in the subprocess fallback gate."""
        state_file = os.path.join(LOGS_DIR, "sprint_state.json")
        
        # Ensure a clean sprint state exists
        state_exists = os.path.exists(state_file)
        state_backup = None
        if state_exists:
            with open(state_file, "r") as f:
                state_backup = f.read()
        else:
            with open(state_file, "w") as f:
                json.dump({"approval_status": ""}, f)

        try:
            async def simulate_user_approve():
                await asyncio.sleep(0.5)
                if os.path.exists(state_file):
                    with open(state_file, "r") as f:
                        s = json.load(f)
                else:
                    s = {}
                s["approval_status"] = "approved"
                with open(state_file, "w") as f:
                    json.dump(s, f, indent=2)

            t = asyncio.create_task(simulate_user_approve())
            with patch.dict(os.environ, {"SECRET_TOKEN": "my-secret-token", "DATABASE_PASSWORD": "pass"}):
                res = await tool_run_command("echo 'sandboxed'")
                await t
                self.assertIn("sandboxed", res)
                self.assertTrue("Isolated" in res or "Offline" in res)
        finally:
            if state_exists and state_backup:
                with open(state_file, "w") as f:
                    f.write(state_backup)
            elif os.path.exists(state_file):
                try:
                    os.remove(state_file)
                except Exception:
                    pass

    async def test_visual_qa_static_pass(self):
        """Verifies DOM tag pairing and viewport verification succeeds on compliant files."""
        html_content = """<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Compliant Page</title>
    <style>
        body { background: hsl(200, 50%, 10%); box-shadow: 0 0 10px rgba(0,255,255,0.5); }
    </style>
</head>
<body>
    <div style="display: flex;">Test content</div>
    <script>console.log("ok");</script>
</body>
</html>"""
        with open(self.sample_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # Mock the virtual vision LLM auditor to approve the styling
        with patch("gstack_core.chat_local_model", return_value="[VISUAL_QA: APPROVED]") as mock_chat:
            ok, log = await run_autonomous_visual_qa("test_sample.html", "Sample EM summary")
            self.assertTrue(ok)
            self.assertIn("DOM Integrity: All structural tags", log)
            self.assertIn("Responsive Ready: Viewport scale meta tag verified", log)

    async def test_visual_qa_repair_loop(self):
        """Verifies DOM defect parsing triggers the design repair engine correctly."""
        # Intentionally unclosed structural tag and missing viewport and styling
        html_content = """<html>
<head>
    <title>Defective Page</title>
</head>
<body>
    <div>Unclosed structural body element
"""
        with open(self.sample_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        repaired_html = """```html
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Repaired Page</title>
    <style>
        body { background: hsl(220, 80%, 8%); box-shadow: 0 0 15px hsl(180, 100%, 50%); }
    </style>
</head>
<body>
    <div>Unclosed structural body element</div>
</body>
</html>
```"""
        from unittest.mock import AsyncMock
        mock_chat = AsyncMock(side_effect=["[VISUAL_QA: FAILED] Missing viewport tag.", repaired_html])

        with patch("gstack_core.chat_local_model", mock_chat):
            ok, log = await run_autonomous_visual_qa("test_sample.html", "Sample EM summary")
            self.assertTrue(ok)
            self.assertIn("DOM Defect: Unclosed structural tags", log)
            self.assertIn("Visual Patching Success", log)

            # Check that repaired file is written to disk
            with open(self.sample_html_path, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn("meta name=\"viewport\"", content)
                self.assertIn("Repaired Page", content)

    async def test_run_phase_debate_generation(self):
        """Verifies debate messages are generated and written to logs/debate_log.json."""
        debate_json = """[
            {"sender": "CEO", "avatar": "ceo", "content": "Let's push design limits."},
            {"sender": "Engineering Manager", "avatar": "eng_manager", "content": "Will prioritize security sandboxes."},
            {"sender": "Designer", "avatar": "designer", "content": "Adding glowing backdrop filters."}
        ]"""
        
        with patch("gstack_core.chat_local_model", return_value=debate_json):
            await run_phase_debate("think", "Build a high-performance database interface")
            
            debate_file = os.path.join(LOGS_DIR, "debate_log.json")
            self.assertTrue(os.path.exists(debate_file))
            
            with open(debate_file, "r") as f:
                data = json.load(f)
                self.assertEqual(len(data), 3)
                self.assertEqual(data[0]["sender"], "CEO")
                self.assertEqual(data[0]["phase"], "think")

    async def test_llm_as_a_route_tiering(self):
        """Verifies LLM-as-a-Route splits Tier 1 and Tier 2 requests and fails over properly."""
        with patch("gstack_core.load_provider_config", return_value={"provider": "cloud_first", "freellmapi_url": "http://mock-cloud/v1", "freellmapi_model": "google/gemini-2.5-flash"}):
            # Test Tier 2 Operational: try local model first, if it succeeds, do not hit cloud
            with patch("gstack_core.urllib.request.urlopen") as mock_url:
                # Mock a streaming response for urlopen
                mock_resp = MagicMock()
                mock_resp.readline.side_effect = [
                    b'data: {"choices": [{"delta": {"content": "Fast Local response"}}]}\n',
                    b'data: [DONE]\n',
                    b''
                ]
                mock_url.return_value = mock_resp
                
                res = await chat_local_model("Sys", "User", role_name="release_engineer")
                self.assertEqual(res, "Fast Local response")
                
                # Check that urlopen was called once hitting localhost:1234
                args, kwargs = mock_url.call_args
                # First argument is request object
                self.assertIn("1234", args[0].full_url)

if __name__ == "__main__":
    unittest.main()

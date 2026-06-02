#!/usr/bin/env python3
import os
import re
import sys
import secrets
import json
import urllib.request

# Ensure we import generation utilities
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from gstack_core import generate_trace_id, generate_span_id, GStackTracer

def migrate_historical_logs(logs_dir="/Users/jack/Documents/gstack-agents/logs", endpoint="http://localhost:6006/v1/traces"):
    print(f"=== GStack Historical Log Migrator (OTLP) ===")
    print(f"Scanning directory: {logs_dir}")
    
    if not os.path.exists(logs_dir):
        print(f"Error: Logs directory '{logs_dir}' does not exist.")
        return
        
    log_files = [f for f in os.listdir(logs_dir) if f.endswith(".log") and f != "test_fallback_run.log"]
    if not log_files:
        print("No historical log files found to migrate.")
        return
        
    print(f"Found {len(log_files)} log files: {log_files}")
    
    # 1. Generate a single unified trace_id representing this consolidated historical sprint
    trace_id = generate_trace_id()
    print(f"Assigned Trace ID: {trace_id}")
    
    tracer = GStackTracer(endpoint=endpoint)
    
    # Define phase execution patterns to parse
    # Flat logs look like:
    # --- Turn 1/8 ---
    # [Attempting Cloud API: ...] / [Using Local API: ...]
    # <XML Tag>
    # [Tool Executed]: ...
    # [Result]: ...
    
    # Simple regex to split turns
    turn_regex = re.compile(r"--- Turn (\d+)/(\d+) ---\n")
    
    total_spans_created = 0
    
    for log_file in log_files:
        agent_role = log_file.replace(".log", "")
        file_path = os.path.join(logs_dir, log_file)
        
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            print(f"Failed to read {log_file}: {e}")
            continue
            
        print(f"Processing {log_file} ({len(content)} bytes)...")
        
        # Create a parent span for this Agent/Phase
        phase_span_id = generate_span_id()
        # Simulated timestamps (using sequence offsets to generate realistic span visual order)
        base_time_ns = 1700000000000000000 + secrets.randbelow(1000000000)
        
        # Parse turns
        splits = turn_regex.split(content)
        # splits looks like: [header, turn_num, max_turns, turn_content, turn_num, max_turns, turn_content, ...]
        
        turns = []
        if len(splits) > 1:
            for idx in range(1, len(splits), 3):
                turn_num = int(splits[idx])
                turn_content = splits[idx+2]
                turns.append((turn_num, turn_content))
                
        phase_start = base_time_ns
        phase_end = base_time_ns
        
        for turn_idx, (turn_num, turn_content) in enumerate(turns):
            turn_span_id = generate_span_id()
            turn_start = base_time_ns + (turn_idx * 10 * 1000000000) # 10s step offsets
            turn_end = turn_start + (5 * 1000000000) # 5s duration
            
            # Look for tool calls inside this turn
            # list_directory
            if "<list_directory />" in turn_content or "<list_directory/>" in turn_content:
                tool_span_id = generate_span_id()
                tracer.add_span(
                    trace_id=trace_id,
                    span_id=tool_span_id,
                    name="tool.list_directory",
                    start_time_ns=turn_start + 1000000000,
                    end_time_ns=turn_start + 2000000000,
                    parent_span_id=turn_span_id,
                    attributes={"tool.name": "list_directory", "tool.input": ""},
                    status_code=2
                )
                total_spans_created += 1
                
            # read_file
            read_match = re.search(r'<read_file\s+path="([^"]+)"\s*/?>', turn_content)
            if read_match:
                filename = read_match.group(1)
                tool_span_id = generate_span_id()
                tracer.add_span(
                    trace_id=trace_id,
                    span_id=tool_span_id,
                    name="tool.read_file",
                    start_time_ns=turn_start + 1000000000,
                    end_time_ns=turn_start + 2000000000,
                    parent_span_id=turn_span_id,
                    attributes={"tool.name": "read_file", "tool.input": filename},
                    status_code=2
                )
                total_spans_created += 1
                
            # write_file
            write_match = re.search(r'<write_file\s+path="([^"]+)">([\s\S]*?)</write_file>', turn_content)
            if write_match:
                filename = write_match.group(1)
                file_size = len(write_match.group(2))
                tool_span_id = generate_span_id()
                tracer.add_span(
                    trace_id=trace_id,
                    span_id=tool_span_id,
                    name="tool.write_file",
                    start_time_ns=turn_start + 1000000000,
                    end_time_ns=turn_start + 3000000000,
                    parent_span_id=turn_span_id,
                    attributes={
                        "tool.name": "write_file",
                        "tool.input": filename,
                        "file.path": filename,
                        "file.size": file_size
                    },
                    status_code=2
                )
                total_spans_created += 1
                
            # run_command
            cmd_match = re.search(r'<run_command>([\s\S]*?)</run_command>', turn_content)
            if cmd_match:
                command = cmd_match.group(1).strip()
                tool_span_id = generate_span_id()
                tracer.add_span(
                    trace_id=trace_id,
                    span_id=tool_span_id,
                    name="tool.run_command",
                    start_time_ns=turn_start + 1000000000,
                    end_time_ns=turn_start + 4000000000,
                    parent_span_id=turn_span_id,
                    attributes={"tool.name": "run_command", "tool.input": command},
                    status_code=2
                )
                total_spans_created += 1
                
            # Log turn span
            tracer.add_span(
                trace_id=trace_id,
                span_id=turn_span_id,
                name="llm.chat_completion",
                start_time_ns=turn_start,
                end_time_ns=turn_end,
                parent_span_id=phase_span_id,
                attributes={
                    "agent.role": agent_role,
                    "llm.turn": turn_num,
                    "llm.prompt": "Historical migrated context...",
                    "llm.response": turn_content[:500] + "..." if len(turn_content) > 500 else turn_content
                },
                status_code=2
            )
            total_spans_created += 1
            phase_end = max(phase_end, turn_end)
            
        # Log phase span
        tracer.add_span(
            trace_id=trace_id,
            span_id=phase_span_id,
            name=f"phase.{agent_role}",
            start_time_ns=phase_start,
            end_time_ns=phase_end if phase_end > phase_start else phase_start + 5000000000,
            attributes={"phase.name": agent_role, "agent.role": agent_role},
            status_code=2
        )
        total_spans_created += 1
        
    print(f"Migration parsed {total_spans_created} OTel spans successfully.")
    print("Exporting payload asynchronously to Arize Phoenix...")
    tracer.export()
    print("✅ Migration export initiated! Check your self-hosted Phoenix dashboard at http://localhost:6006.")

if __name__ == "__main__":
    migrate_historical_logs()

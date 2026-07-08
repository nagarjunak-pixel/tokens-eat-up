import os
import json
import time
import logging
import threading
import httpx
from typing import List, Dict, Any, Callable, Tuple
from backend.sandbox import Sandbox
from backend.analyzer import analyze_code

logger = logging.getLogger("agents")

# Ollama configuration
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.5:4b")

# Check if Ollama is available
OLLAMA_AVAILABLE = False

class MultiAgentSystem:
    def __init__(self, sandbox: Sandbox, broadcast_fn: Callable[[str, Dict[str, Any]], None], api_key: str = None):
        self.sandbox = sandbox
        self.broadcast_fn = broadcast_fn
        self.model = None
        self.use_vertex = False  # reused as "llm available" flag
        
        # Human-in-the-loop synchronization
        self.hitl_event = threading.Event()
        self.user_response = ""
        
        # Check API client setup
        self._init_llm()

    def _init_llm(self):
        # Try to connect to local Ollama
        try:
            resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5.0)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                model_names = [m["name"] for m in models]
                if any(OLLAMA_MODEL in name for name in model_names):
                    self.model = OLLAMA_MODEL
                    self.use_vertex = True  # reuse flag as "llm available"
                    OLLAMA_AVAILABLE = True
                    self.log("System", f"Connected to Ollama at {OLLAMA_URL}, using model '{OLLAMA_MODEL}'.", "success")
                    return
                else:
                    available = ", ".join(model_names) if model_names else "none"
                    self.log("System", f"Ollama found but model '{OLLAMA_MODEL}' not available. Available: {available}. Falling back to simulation.", "warning")
            else:
                self.log("System", f"Ollama returned status {resp.status_code}. Falling back to simulation.", "warning")
        except Exception as e:
            self.log("System", f"Could not connect to Ollama at {OLLAMA_URL}: {e}. Falling back to simulation.", "warning")
        
        self.model = None
        self.use_vertex = False

    def log(self, agent_name: str, message: str, level: str = "info", details: Any = None):
        """Broadcasts logs to WebSocket and prints to terminal."""
        logger.info(f"[{agent_name}] {message}")
        self.broadcast_fn("log", {
            "agent": agent_name,
            "message": message,
            "level": level,
            "details": details,
            "timestamp": time.time()
        })

    def send_state(self, current_agent: str, status: str, file_list: List[str] = None):
        """Updates the frontend on the agent system state."""
        self.broadcast_fn("state", {
            "current_agent": current_agent,
            "status": status,
            "files": file_list or self.sandbox.list_files(),
            "timestamp": time.time()
        })

    def save_and_analyze(self, filename: str, content: str, commit_msg: str):
        """Writes code file, runs static analysis, commits, and broadcasts updates."""
        self.sandbox.write_file(filename, content)
        
        # Git Commit
        self.sandbox.commit(commit_msg)
        self.broadcast_git_history()
        
        # Static Code Analysis
        try:
            analysis = analyze_code(filename, content)
            self.broadcast_fn("analysis", {
                "analysis": analysis,
                "timestamp": time.time()
            })
            self.log("Reviewer", f"Static analysis of {filename}: Risk level {analysis['risk'].upper()} ({analysis['loc']} LOC, {analysis['functions']} functions, {analysis['classes']} classes, {len(analysis['warnings'])} warnings).", "info")
        except Exception as e:
            logger.error(f"Error running analysis on {filename}: {e}")

    def wait_for_user_approval(self, agent_name: str, question: str) -> str:
        """Pauses execution and blocks until the user replies via WebSocket."""
        self.log(agent_name, f"Checkpoint: {question}", "warning")
        self.broadcast_fn("hitl_prompt", {
            "agent": agent_name,
            "message": question,
            "timestamp": time.time()
        })
        self.send_state(agent_name, "waiting_user")
        
        # Block until thread is released by Websocket handler setting self.hitl_event
        self.hitl_event.clear()
        self.hitl_event.wait()
        
        self.log(agent_name, f"User responded: '{self.user_response}'", "info")
        self.send_state(agent_name, "running")
        return self.user_response

    def broadcast_git_history(self):
        """Fetches git log from sandbox and broadcasts to UI."""
        commits = self.sandbox.get_git_log()
        self.broadcast_fn("git_history", {
            "commits": commits,
            "timestamp": time.time()
        })

    def collaborate_chat(self, from_agent: str, to_agent: str, message: str):
        """Logs collaborative chats between agents in the UI."""
        logger.info(f"[{from_agent} -> {to_agent}] {message}")
        self.broadcast_fn("agent_chat", {
            "from": from_agent,
            "to": to_agent,
            "message": message,
            "timestamp": time.time()
        })
        time.sleep(1.2) # Make discussion readable

    def call_llm(self, system_instruction: str, prompt: str, json_mode: bool = False) -> str:
        """Helper to invoke Ollama API for LLM generation."""
        if not self.use_vertex or not self.model:
            raise RuntimeError("Ollama LLM not initialized")
        
        try:
            # Note: qwen3.5:4b returns empty response with format="json",
            # so we rely on prompt instructions to produce JSON instead.
            payload = {
                "model": self.model,
                "system": system_instruction,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                },
            }
            
            resp = httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json=payload,
                timeout=120.0,
            )
            resp.raise_for_status()
            result = resp.json()
            response_text = result.get("response", "")
            
            if json_mode:
                # Strip markdown fences if present
                response_text = self._strip_markdown_fences(response_text).strip()
            
            return response_text
        except Exception as e:
            logger.error(f"Ollama API generation error: {e}")
            raise e

    def run_task(self, prompt: str, use_simulation: bool = False, auto_approve: bool = False):
        """Main execution flow representing the Multi-Agent SDLC.
        
        auto_approve=True will automatically approve HITL checkpoints
        (useful for quick testing / headless mode).
        """
        self.sandbox.reset()
        self.sandbox.init_git()
        self.broadcast_git_history()
        
        self.log("System", f"Starting task: '{prompt}'", "info")
        self.send_state("Planner", "running")

        # Force simulation if LLM not available
        if not self.use_vertex or not self.model:
            use_simulation = True
            self.log("System", "Ollama LLM not available. Running in simulation mode.", "warning")

        # Run collaborative agent discussion first
        self.collaborate_chat("Planner Agent", "Coder Agent", f"Task initialized: '{prompt}'. Let's align on structure.")
        self.collaborate_chat("Coder Agent", "Planner Agent", "Awesome. I recommend creating modular source files and a comprehensive test suite.")
        self.collaborate_chat("Planner Agent", "Coder Agent", "Agreed. I will now generate the plan detailing files and dependencies.")

        if use_simulation:
            self._run_simulation_mode(prompt, auto_approve=auto_approve)
        else:
            self._run_llm_mode(prompt, auto_approve=auto_approve)

    def _auto_or_manual_approve(self, agent_name: str, question: str, auto_approve: bool) -> str:
        """If auto_approve, return 'yes' immediately; otherwise block for human input."""
        if auto_approve:
            self.log(agent_name, f"Auto-approved: {question}", "info")
            return "yes"
        return self.wait_for_user_approval(agent_name, question)

    def _run_llm_mode(self, prompt: str, auto_approve: bool = False):
        # --- PHASE 1: PLANNING ---
        self.log("Planner", "Analyzing prompt and building implementation plan...", "info")
        time.sleep(1.5)
        
        planner_instruction = (
            "You are a Senior Software Architect. Analyze the user request and generate a plan.\n"
            "Respond ONLY with a JSON object. Format:\n"
            "{\n"
            "  \"project_name\": \"Name\",\n"
            "  \"files\": [\"file1.py\", \"file2.py\"],\n"
            "  \"description\": {\"file1.py\": \"Description\"},\n"
            "  \"dependencies\": [\"file1.py\", \"file2.py\"],\n"
            "  \"test_command\": \"python -m unittest test_file.py\"\n"
            "}"
        )
        
        try:
            plan_raw = self.call_llm(planner_instruction, f"User Request: {prompt}", json_mode=True)
            plan = json.loads(plan_raw)
            self.log("Planner", f"Generated project plan: {plan['project_name']}", "success", plan)
        except Exception as e:
            self.log("Planner", f"Planning failed: {e}. Aborting.", "error")
            self.send_state("Planner", "failed")
            return

        # HUMAN-IN-THE-LOOP CHECKPOINT: PLAN APPROVAL
        question = f"Planner has designed the project '{plan['project_name']}'. Do you approve files: {plan['files']}?"
        response = self._auto_or_manual_approve("Planner", question, auto_approve)
        
        if "no" in response.lower() or "reject" in response.lower():
            self.log("Planner", "Plan was rejected by user. Aborting execution loop.", "error")
            self.send_state("Completed", "failed")
            return

        files_to_build = plan.get("dependencies", plan.get("files", []))
        test_command = plan.get("test_command", "python3 -m unittest")
        generated_code = {}

        # --- PHASE 2: CODING & REVIEW ---
        for filename in files_to_build:
            self.send_state("Coder", "running")
            self.log("Coder", f"Writing code for file: {filename}...", "info")
            time.sleep(1.5)

            coder_instruction = (
                f"You are a Coder Agent. Write the complete code for: {filename}.\n"
                f"Project details:\n{json.dumps(plan)}\n"
                f"Already written files:\n{json.dumps(generated_code)}\n"
                "Return ONLY the raw file contents. Do not wrap in markdown blocks like ```python. Just the code."
            )
            
            try:
                code = self.call_llm(coder_instruction, f"Generate {filename}")
                code = self._strip_markdown_fences(code)
                
                self.log("Coder", f"Code generated for {filename}.", "success")
                generated_code[filename] = code
                
                # Save, analyze complexity and safety metrics, and commit to Git!
                self.save_and_analyze(filename, code, f"feat: generate {filename}")
                self.send_state("Reviewer", "running")
            except Exception as e:
                self.log("Coder", f"Failed generating code for {filename}: {e}", "error")
                self.send_state("Coder", "failed")
                return

            # Review code
            self.log("Reviewer", f"Reviewing code of {filename} for syntax and best practices...", "info")
            time.sleep(1.5)
            
            reviewer_instruction = (
                "You are a QA / Code Reviewer. Analyze the code and check for any syntax/compilation issues.\n"
                "Respond ONLY with a JSON object. Format:\n"
                "{\n"
                "  \"approved\": true/false,\n"
                "  \"feedback\": \"Reason for rejection or 'Looks good!'\"\n"
                "}"
            )
            
            try:
                review_raw = self.call_llm(reviewer_instruction, f"File: {filename}\nContent:\n{code}", json_mode=True)
                review = json.loads(review_raw)
                
                if not review.get("approved", False):
                    self.log("Reviewer", f"File {filename} rejected! Feedback: {review.get('feedback')}", "warning")
                    
                    hitl_q = f"Code Reviewer rejected '{filename}' due to: {review.get('feedback')}. Should we trigger the Debugger Agent?"
                    hitl_resp = self._auto_or_manual_approve("Reviewer", hitl_q, auto_approve)
                    
                    if "no" in hitl_resp.lower():
                        self.log("Reviewer", "User elected not to run debugger. Aborting.", "error")
                        self.send_state("Completed", "failed")
                        return

                    self.send_state("Debugger", "running")
                    self.log("Debugger", "Fixing code based on reviewer feedback...", "info")
                    time.sleep(1.5)
                    
                    debugger_instruction = (
                        f"You are a Debugger. Correct the following code for: {filename}.\n"
                        f"Reviewer Feedback: {review.get('feedback')}\n"
                        f"Original Code:\n{code}\n"
                        "Return ONLY the raw fixed file contents. Do not wrap in markdown."
                    )
                    code_fixed = self.call_llm(debugger_instruction, "Fix the code")
                    code_fixed = self._strip_markdown_fences(code_fixed)
                    
                    self.log("Debugger", f"Debugger applied fix for {filename}.", "success")
                    code = code_fixed
                    generated_code[filename] = code
                    
                    self.save_and_analyze(filename, code, f"fix: resolve reviewer issues in {filename}")
                else:
                    self.log("Reviewer", f"File {filename} approved: {review.get('feedback')}", "success")
            except Exception as e:
                self.log("Reviewer", f"Review process failed: {e}. Proceeding anyway.", "warning")

        # --- PHASE 3: EXECUTION & TEST LOOP ---
        max_test_iterations = 4
        for iteration in range(max_test_iterations):
            self.send_state("Executor", "running")
            self.log("Executor", f"Running test command inside sandbox: `{test_command}` (Attempt {iteration + 1})", "info")
            time.sleep(1.5)

            exit_code, stdout, stderr = self.sandbox.run_command(test_command)
            self.broadcast_fn("terminal", {
                "command": test_command,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr
            })

            if exit_code == 0:
                self.log("Executor", "All tests passed successfully!", "success")
                self.sandbox.commit("test: all unit tests passing successfully")
                self.broadcast_git_history()
                self.send_state("Completed", "success")
                return
            else:
                self.log("Executor", f"Tests failed with exit code {exit_code}.", "error")
                
                hitl_q = f"Sandbox test failed. Do you want the Debugger Agent to analyze the stderr traceback?"
                hitl_resp = self._auto_or_manual_approve("Executor", hitl_q, auto_approve)
                
                if "no" in hitl_resp.lower():
                    self.log("Executor", "Debugging cancelled by user. Terminating process.", "error")
                    self.send_state("Completed", "failed")
                    return

                if iteration == max_test_iterations - 1:
                    self.log("System", "Max debugging iterations reached. Execution failed.", "error")
                    self.send_state("Completed", "failed")
                    return

                # Debug Phase
                self.send_state("Debugger", "running")
                self.log("Debugger", "Analyzing traceback error to resolve issues...", "info")
                time.sleep(1.8)

                target_file = files_to_build[0]
                original_content = self.sandbox.read_file(target_file)

                debugger_prompt = (
                    f"Command run: {test_command}\n"
                    f"Exit code: {exit_code}\n"
                    f"Stdout: {stdout}\n"
                    f"Stderr: {stderr}\n"
                    f"File to debug: {target_file}\n"
                    f"Current Content:\n{original_content}"
                )

                debugger_instruction = (
                    "You are a Debugger Agent. A Python command failed in the sandbox.\n"
                    "Analyze the code and the error trace, identify the bug, and output the corrected version of the file.\n"
                    "Return ONLY the raw corrected file contents. Do not wrap in markdown code blocks."
                )

                try:
                    fixed_code = self.call_llm(debugger_instruction, debugger_prompt)
                    fixed_code = self._strip_markdown_fences(fixed_code)
                    
                    self.save_and_analyze(target_file, fixed_code, f"fix: debug patch for test failures in {target_file}")
                    self.log("Debugger", f"Applied fix to `{target_file}`. Re-triggering execution.", "success")
                except Exception as e:
                    self.log("Debugger", f"Debugging generation failed: {e}", "error")
                    self.send_state("Completed", "failed")
                    return

    def _run_simulation_mode(self, prompt: str, auto_approve: bool = False):
        """Simulates the multi-agent loop with detailed outputs if no API keys are loaded."""
        self.log("Planner", "Analyzing prompt and building plan in simulation mode...", "info")
        time.sleep(1.5)

        plan = {
            "project_name": "Math Operations Library",
            "files": ["math_lib.py", "test_math_lib.py"],
            "description": {
                "math_lib.py": "Contains advanced arithmetic operations including factorial and exponentiation.",
                "test_math_lib.py": "Unit tests verifying math formulas and corner cases."
            },
            "dependencies": ["math_lib.py", "test_math_lib.py"],
            "test_command": "python3 -m unittest test_math_lib.py"
        }
        self.log("Planner", f"Generated project plan: {plan['project_name']}", "success", plan)

        # HUMAN-IN-THE-LOOP: PLAN APPROVAL
        question = "Planner has created the plan for 'Math Operations Library'. Do you approve it to proceed to coding?"
        user_resp = self._auto_or_manual_approve("Planner", question, auto_approve)
        
        if "reject" in user_resp.lower() or "no" in user_resp.lower():
            self.log("Planner", "Execution rejected by user. Aborting.", "error")
            self.send_state("Completed", "failed")
            return

        self.send_state("Coder", "running")
        time.sleep(1.5)

        self.log("Coder", "Writing code for file: math_lib.py...", "info")
        time.sleep(1.0)
        
        buggy_math = (
            "import os\n" # Intentional import to trigger medium security warning!
            "def add(a, b):\n"
            "    return a + b\n\n"
            "def subtract(a, b):\n"
            "    return a - b\n\n"
            "def multiply(a, b):\n"
            "    return a * b\n\n"
            "def divide(a, b):\n"
            "    # INTENTIONAL BUG FOR DEMONSTRATION\n"
            "    return a - b\n"
        )
        # Save math_lib.py, run static analysis and commit!
        self.save_and_analyze("math_lib.py", buggy_math, "feat: generate math_lib.py")
        self.log("Coder", "Code generated for math_lib.py.", "success")
        
        self.send_state("Reviewer", "running")
        time.sleep(1.2)
        self.log("Reviewer", "Reviewing code of math_lib.py... Approved.", "success")
        
        self.send_state("Coder", "running")
        time.sleep(1.2)
        self.log("Coder", "Writing code for file: test_math_lib.py...", "info")
        
        test_code = (
            "import unittest\n"
            "from math_lib import add, subtract, multiply, divide\n\n"
            "class TestMathLib(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n"
            "    def test_subtract(self):\n"
            "        self.assertEqual(subtract(5, 2), 3)\n"
            "    def test_multiply(self):\n"
            "        self.assertEqual(multiply(3, 4), 12)\n"
            "    def test_divide(self):\n"
            "        self.assertEqual(divide(10, 2), 5)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )
        self.save_and_analyze("test_math_lib.py", test_code, "feat: generate test_math_lib.py")
        self.log("Coder", "Code generated for test_math_lib.py.", "success")
        
        self.send_state("Reviewer", "running")
        time.sleep(1.0)
        self.log("Reviewer", "Reviewing code of test_math_lib.py... Approved.", "success")

        # EXECUTION ATTEMPT 1: FAILS
        self.send_state("Executor", "running")
        test_cmd = "python3 -m unittest test_math_lib.py"
        self.log("Executor", f"Running test command inside sandbox: `{test_cmd}` (Attempt 1)", "info")
        time.sleep(1.8)

        exit_code, stdout, stderr = self.sandbox.run_command(test_cmd)
        
        self.broadcast_fn("terminal", {
            "command": test_cmd,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr
        })
        self.log("Executor", f"Tests failed with exit code {exit_code}.", "error")

        # HUMAN-IN-THE-LOOP: TEST FAILURE
        question = "Tests failed inside the sandbox workspace. Trigger Debugger Agent to fix 'math_lib.py'?"
        user_resp = self._auto_or_manual_approve("Executor", question, auto_approve)
        
        if "reject" in user_resp.lower() or "no" in user_resp.lower():
            self.log("Executor", "Debugging aborted by user.", "error")
            self.send_state("Completed", "failed")
            return

        # DEBUGGER
        self.send_state("Debugger", "running")
        self.log("Debugger", "Analyzing traceback error to resolve issues...", "info")
        time.sleep(2.0)
        self.log("Debugger", "Detected logic failure in `math_lib.py:divide`. Expected division output, found subtraction logic.", "warning")
        
        # Apply fix
        fixed_math = (
            "def add(a, b):\n"
            "    return a + b\n\n"
            "def subtract(a, b):\n"
            "    return a - b\n\n"
            "def multiply(a, b):\n"
            "    return a * b\n\n"
            "def divide(a, b):\n"
            "    if b == 0:\n"
            "        raise ValueError('Cannot divide by zero')\n"
            "    return a / b\n"
        )
        self.save_and_analyze("math_lib.py", fixed_math, "fix: resolve division logic in math_lib.py")
        self.log("Debugger", "Applied fix to `math_lib.py`. Re-triggering execution.", "success")

        # EXECUTION ATTEMPT 2: PASSES
        self.send_state("Executor", "running")
        self.log("Executor", f"Running test command inside sandbox: `{test_cmd}` (Attempt 2)", "info")
        time.sleep(1.5)
        
        exit_code, stdout, stderr = self.sandbox.run_command(test_cmd)
        
        self.broadcast_fn("terminal", {
            "command": test_cmd,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr
        })
        
        if exit_code == 0:
            self.log("Executor", "All tests passed successfully!", "success")
            self.sandbox.commit("test: unit tests complete and passing")
            self.broadcast_git_history()
            self.send_state("Completed", "success")
        else:
            self.log("Executor", "Tests failed again in simulation.", "error")
            self.send_state("Completed", "failed")

    @staticmethod
    def _strip_markdown_fences(code: str) -> str:
        """Strips ```lang ... ``` wrapping from LLM responses."""
        if code.startswith("```"):
            lines = code.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            code = "\n".join(lines)
        return code

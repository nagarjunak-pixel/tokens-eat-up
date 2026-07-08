import os
import sys

# Ensure backend can import relative modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.sandbox import Sandbox
from backend.agents import MultiAgentSystem

def mock_broadcast(msg_type: str, data: dict):
    """Mock websocket broadcast callback that prints to stdout."""
    print(f"\n[WS BROADCAST] {msg_type.upper()}:")
    if msg_type == "log":
        print(f"  Agent: {data.get('agent')}")
        print(f"  Level: {data.get('level')}")
        print(f"  Message: {data.get('message')}")
    elif msg_type == "state":
        print(f"  Current Agent: {data.get('current_agent')}")
        print(f"  Status: {data.get('status')}")
        print(f"  Files in Sandbox: {data.get('files')}")
    elif msg_type == "terminal":
        print(f"  Command: {data.get('command')}")
        print(f"  Exit Code: {data.get('exit_code')}")
        print(f"  Stdout lines: {len(data.get('stdout', '').splitlines())}")
        print(f"  Stderr lines: {len(data.get('stderr', '').splitlines())}")

def run_test():
    print("=== STARTING BACKEND VERIFICATION TEST ===")
    sandbox = Sandbox(workspace_dir="test_sandbox_workspace")
    
    print("\n--- Testing Sandbox write and list ---")
    sandbox.write_file("dummy.py", "print('hello from sandbox')")
    files = sandbox.list_files()
    print(f"Files: {files}")
    assert "dummy.py" in files, "dummy.py was not written successfully"

    print("\n--- Testing Sandbox execution ---")
    exit_code, stdout, stderr = sandbox.run_command("python dummy.py")
    print(f"Exit code: {exit_code}")
    print(f"Stdout: {stdout.strip()}")
    assert exit_code == 0, "dummy.py execution failed"
    assert stdout.strip() == "hello from sandbox", "dummy.py output mismatch"

    print("\n--- Testing Agent System in Simulation Mode ---")
    system = MultiAgentSystem(sandbox=sandbox, broadcast_fn=mock_broadcast)
    system.run_task("Build simple math functions with tests", use_simulation=True)
    
    print("\n=== BACKEND VERIFICATION SUCCESSFUL ===")

if __name__ == "__main__":
    run_test()

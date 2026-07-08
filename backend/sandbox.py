import os
import subprocess
import shutil
import sys
from typing import Dict, List, Tuple

class Sandbox:
    def __init__(self, workspace_dir: str = "sandbox_workspace"):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.reset()

    def reset(self) -> None:
        """Cleans and recreates the sandbox workspace."""
        if os.path.exists(self.workspace_dir):
            shutil.rmtree(self.workspace_dir)
        os.makedirs(self.workspace_dir, exist_ok=True)

    def write_file(self, filename: str, content: str) -> str:
        """Writes a file to the sandbox workspace."""
        filepath = os.path.join(self.workspace_dir, filename)
        # Ensure any subfolders are created
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return filepath

    def read_file(self, filename: str) -> str:
        """Reads a file from the sandbox workspace."""
        filepath = os.path.join(self.workspace_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filename}")
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()

    def list_files(self) -> List[str]:
        """Lists all files in the sandbox workspace recursively."""
        file_list = []
        for root, _, files in os.walk(self.workspace_dir):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), self.workspace_dir)
                file_list.append(rel_path)
        return sorted(file_list)

    def run_command(self, cmd: str, timeout: float = 15.0) -> Tuple[int, str, str]:
        """Runs a command inside the sandbox workspace and returns (exit_code, stdout, stderr)."""
        # Run using the same python binary as the current environment to have dependencies
        python_executable = sys.executable
        
        # Replace python or python3 in command with the current python executable to ensure consistency
        cmd_parts = cmd.split()
        if cmd_parts and cmd_parts[0] in ("python", "python3"):
            cmd_parts[0] = f'"{python_executable}"'
            cmd = " ".join(cmd_parts)

        try:
            # We run in a shell for ease of command formatting
            process = subprocess.run(
                cmd,
                shell=True,
                cwd=self.workspace_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout
            )
            return process.returncode, process.stdout, process.stderr
        except subprocess.TimeoutExpired as e:
            stdout = e.stdout.decode("utf-8") if isinstance(e.stdout, bytes) else (e.stdout or "")
            stderr = e.stderr.decode("utf-8") if isinstance(e.stderr, bytes) else (e.stderr or "")
            stderr += f"\n[TimeoutExpired: Command timed out after {timeout} seconds]"
            return -1, stdout, stderr
        except Exception as e:
            return -1, "", str(e)

    def init_git(self) -> None:
        """Initializes a git repository in the workspace."""
        ret, _, _ = self.run_command("git init")
        if ret == 0:
            self.run_command("git config user.name 'Devin-Lite Agent'")
            self.run_command("git config user.email 'agent@devin-lite.local'")
            self.write_file(".gitignore", "__pycache__/\n*.pyc\n")
            self.run_command("git add .gitignore")
            self.run_command("git commit -m 'Initial commit'")

    def commit(self, message: str) -> bool:
        """Creates a git commit of the current workspace state."""
        msg_escaped = message.replace("'", "'\"'\"'")
        self.run_command("git add .")
        ret, _, _ = self.run_command(f"git commit -m '{msg_escaped}'")
        return ret == 0

    def get_git_log(self) -> List[Dict[str, str]]:
        """Retrieves history of commits."""
        ret, stdout, _ = self.run_command("git log --pretty=format:'%h|%s'")
        if ret != 0 or not stdout.strip():
            return []
        
        commits = []
        for line in stdout.strip().split("\n"):
            line = line.strip("'")
            if "|" in line:
                h, m = line.split("|", 1)
                commits.append({"hash": h, "message": m})
        return commits

import os
import json
import logging
import asyncio
import threading
from typing import List, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from backend.sandbox import Sandbox
from backend.agents import MultiAgentSystem

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

app = FastAPI(title="Devin-Lite API")

# Enable CORS for the frontend server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared active websocket connections
active_connections: Set[WebSocket] = set()

# Store a reference to the running event loop for cross-thread broadcasts
_main_loop: asyncio.AbstractEventLoop = None

# Initialize Sandbox and MultiAgentSystem
sandbox = Sandbox(workspace_dir=os.path.join(os.path.dirname(__file__), "..", "sandbox_workspace"))

# WebSocket broadcast function (thread-safe: callable from any thread)
def broadcast_to_websockets(msg_type: str, data: dict):
    payload = json.dumps({"type": msg_type, "data": data})
    loop = _main_loop
    if loop is None:
        logger.warning("Event loop not ready, skipping broadcast")
        return
    if loop.is_running():
        asyncio.run_coroutine_threadsafe(send_payload_to_all(payload), loop)
    else:
        logger.warning("Event loop not running, skipping broadcast")

async def send_payload_to_all(payload: str):
    if not active_connections:
        return
    # Make a copy to avoid modification during iteration
    for connection in list(active_connections):
        try:
            await connection.send_text(payload)
        except Exception as e:
            logger.error(f"Error sending message to websocket: {e}")
            active_connections.discard(connection)

agent_system = MultiAgentSystem(
    sandbox=sandbox,
    broadcast_fn=broadcast_to_websockets
)

class TaskRequest(BaseModel):
    prompt: str
    simulation: bool = False
    auto_approve: bool = False

@app.on_event("startup")
async def startup_event():
    global _main_loop
    _main_loop = asyncio.get_running_loop()

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "active_connections": len(active_connections),
        "llm_available": agent_system.use_vertex,
        "model": agent_system.model,
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    logger.info(f"New client connected. Total clients: {len(active_connections)}")
    
    # Send initial status
    try:
        await websocket.send_text(json.dumps({
            "type": "state",
            "data": {
                "current_agent": "Idle",
                "status": "waiting",
                "files": sandbox.list_files()
            }
        }))
        while True:
            data = await websocket.receive_text()
            logger.info(f"Received message from client: {data}")
            try:
                msg = json.loads(data)
                if msg.get("type") == "user_response":
                    resp_val = msg.get("data", {}).get("response", "")
                    agent_system.user_response = resp_val
                    agent_system.hitl_event.set()
                    logger.info(f"Released HITL blocking event with response: {resp_val}")
            except Exception as ex:
                logger.error(f"Error parsing client websocket message: {ex}")
    except WebSocketDisconnect:
        active_connections.discard(websocket)
        logger.info(f"Client disconnected. Remaining: {len(active_connections)}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        active_connections.discard(websocket)

@app.post("/api/start")
def start_agent_task(request: TaskRequest):
    """Triggers the Multi-Agent system to solve a task."""
    logger.info(f"Triggering task: {request.prompt} (Simulation: {request.simulation}, AutoApprove: {request.auto_approve})")
    
    # Run the agent run_task in a separate background thread so FastAPI remains responsive
    thread = threading.Thread(
        target=agent_system.run_task,
        args=(request.prompt, request.simulation, request.auto_approve),
        daemon=True
    )
    thread.start()
    return {"status": "started", "message": "Multi-agent loop triggered."}

@app.get("/api/files")
def list_sandbox_files():
    """Lists files in the sandbox workspace."""
    try:
        return {"files": sandbox.list_files()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/files/{filename:path}")
def get_sandbox_file(filename: str):
    """Retrieves content of a specific file in the sandbox."""
    try:
        content = sandbox.read_file(filename)
        return {"filename": filename, "content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File {filename} not found.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/reset")
def reset_sandbox():
    """Resets the sandbox workspace."""
    try:
        sandbox.reset()
        broadcast_to_websockets("state", {
            "current_agent": "Idle",
            "status": "waiting",
            "files": []
        })
        return {"status": "success", "message": "Sandbox workspace reset."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/git/log")
def get_git_log():
    """Retrieves sandbox git commit log history."""
    try:
        return {"commits": sandbox.get_git_log()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8001, reload=True)

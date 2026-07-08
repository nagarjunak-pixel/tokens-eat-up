import React, { useState, useEffect, useRef } from 'react';

function App() {
  const [currentAgent, setCurrentAgent] = useState('Idle');
  const [status, setStatus] = useState('waiting');
  const [files, setFiles] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState('');
  const [logs, setLogs] = useState([]);
  const [terminal, setTerminal] = useState(null);
  const [prompt, setPrompt] = useState('');
  const [simulation, setSimulation] = useState(true);
  const [autoApprove, setAutoApprove] = useState(true);
  const [running, setRunning] = useState(false);

  // Phase 2 states
  const [gitCommits, setGitCommits] = useState([]);
  const [agentChatLogs, setAgentChatLogs] = useState([]);
  const [hitlPrompt, setHitlPrompt] = useState(null);
  const [userResponse, setUserResponse] = useState('');

  // Phase 3 states
  const [theme, setTheme] = useState('space-dark');
  const [analysisReport, setAnalysisReport] = useState(null);

  const socketRef = useRef(null);
  const logFeedEndRef = useRef(null);
  const terminalEndRef = useRef(null);
  const chatFeedEndRef = useRef(null);

  // Connect to backend WebSocket
  useEffect(() => {
    connectWebSocket();
    return () => {
      if (socketRef.current) socketRef.current.close();
    };
  }, []);

  // Update theme tag on HTML element
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  const connectWebSocket = () => {
    const wsUrl = `ws://${window.location.hostname}:8001/ws`;
    console.log(`Connecting to WebSocket: ${wsUrl}`);
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      const { type, data } = message;

      if (type === 'state') {
        setCurrentAgent(data.current_agent);
        setStatus(data.status);
        if (data.files) {
          setFiles(data.files);
        }
        if (data.status === 'success' || data.status === 'failed') {
          setRunning(false);
          setHitlPrompt(null);
        }
      } else if (type === 'log') {
        setLogs((prev) => [...prev, data]);
      } else if (type === 'terminal') {
        setTerminal(data);
      } else if (type === 'git_history') {
        setGitCommits(data.commits || []);
      } else if (type === 'agent_chat') {
        setAgentChatLogs((prev) => [...prev, data]);
      } else if (type === 'hitl_prompt') {
        setHitlPrompt(data);
      } else if (type === 'analysis') {
        setAnalysisReport(data.analysis);
      }
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected. Reconnecting in 3s...');
      setTimeout(connectWebSocket, 3000);
    };

    socketRef.current = ws;
  };

  // Scroll views to bottom
  useEffect(() => {
    logFeedEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [terminal]);

  useEffect(() => {
    chatFeedEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [agentChatLogs]);

  // Fetch file content when file is selected
  useEffect(() => {
    if (selectedFile) {
      fetchFileContent(selectedFile);
    } else {
      setFileContent('');
    }
  }, [selectedFile]);

  // Auto-select first/newest file if files list changes
  useEffect(() => {
    if (files.length > 0 && !selectedFile) {
      setSelectedFile(files[0]);
    }
  }, [files]);

  const fetchFileContent = async (filename) => {
    try {
      const res = await fetch(`http://${window.location.hostname}:8001/api/files/${encodeURIComponent(filename)}`);
      if (res.ok) {
        const data = await res.json();
        setFileContent(data.content);
      }
    } catch (e) {
      console.error('Error fetching file:', e);
    }
  };

  const handleStartTask = async (e) => {
    e.preventDefault();
    if (!prompt.trim() || running) return;

    setRunning(true);
    setLogs([]);
    setTerminal(null);
    setSelectedFile(null);
    setFiles([]);
    setGitCommits([]);
    setAgentChatLogs([]);
    setHitlPrompt(null);
    setUserResponse('');
    setAnalysisReport(null);

    try {
      const res = await fetch(`http://${window.location.hostname}:8001/api/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, simulation, auto_approve: autoApprove }),
      });
      if (!res.ok) {
        setRunning(false);
      }
    } catch (e) {
      console.error('Failed starting task:', e);
      setRunning(false);
    }
  };

  const handleSendHitlResponse = (responseVal) => {
    if (!socketRef.current || !hitlPrompt) return;
    
    socketRef.current.send(JSON.stringify({
      type: 'user_response',
      data: { response: responseVal }
    }));
    
    setHitlPrompt(null);
    setUserResponse('');
  };

  const handleReset = async () => {
    try {
      const res = await fetch(`http://${window.location.hostname}:8001/api/reset`, { method: 'POST' });
      if (res.ok) {
        setLogs([]);
        setTerminal(null);
        setSelectedFile(null);
        setFiles([]);
        setGitCommits([]);
        setAgentChatLogs([]);
        setHitlPrompt(null);
        setAnalysisReport(null);
        setCurrentAgent('Idle');
        setStatus('waiting');
        setRunning(false);
      }
    } catch (e) {
      console.error('Failed to reset:', e);
    }
  };

  const getNodeClass = (nodeName) => {
    if (currentAgent === nodeName) {
      return status === 'waiting_user' ? 'agent-node paused' : 'agent-node active';
    }
    if (currentAgent === 'Completed' && status === 'success') return 'agent-node success';
    if (currentAgent === 'Completed' && status === 'failed') return 'agent-node failed';

    const sequence = ['Planner', 'Coder', 'Reviewer', 'Executor', 'Debugger', 'Completed'];
    const currentIndex = sequence.indexOf(currentAgent);
    const nodeIndex = sequence.indexOf(nodeName);

    if (nodeIndex < currentIndex) {
      return 'agent-node success';
    }
    return 'agent-node';
  };

  return (
    <div className="app-container">
      <header>
        <div className="brand">
          <div className="brand-logo"></div>
          <div className="brand-title">Devin-Lite Sandbox</div>
        </div>
        
        <div style={{display: 'flex', gap: '1rem', alignItems: 'center'}}>
          {/* Theme Selector */}
          <div style={{display: 'flex', alignItems: 'center', gap: '0.4rem'}}>
            <span style={{fontSize: '0.75rem', color: 'var(--text-secondary)'}}>Theme:</span>
            <select
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              style={{
                background: 'var(--terminal-bg)',
                color: '#fff',
                border: '1px solid var(--border-glow)',
                padding: '0.3rem 0.5rem',
                borderRadius: '8px',
                cursor: 'pointer',
                fontSize: '0.8rem',
                outline: 'none'
              }}
            >
              <option value="space-dark">🌌 Space Dark</option>
              <option value="cyberpunk">🦄 Cyberpunk Glow</option>
              <option value="matrix">📟 Matrix Green</option>
            </select>
          </div>
          
          <button onClick={handleReset} className="status-badge idle" style={{border: 'none', cursor: 'pointer'}}>
            Reset Workspace
          </button>
          
          <div className={`status-badge ${running ? (status === 'waiting_user' ? 'failed' : 'running') : status}`}>
            <span className="dot"></span>
            {running 
              ? (status === 'waiting_user' ? `PAUSED: HITL` : `Running: ${currentAgent}`) 
              : `Status: ${status.toUpperCase()}`}
          </div>
        </div>
      </header>

      <main className="main-dashboard">
        {/* LEFT SIDEBAR: File List, Code Metrics & Git History */}
        <div className="sidebar-files" style={{display: 'flex', flexDirection: 'column', gap: '1.2rem'}}>
          
          {/* Workspace Files */}
          <div style={{height: '30%', display: 'flex', flexDirection: 'column', overflow: 'hidden'}}>
            <h3 className="sidebar-title">Workspace Files</h3>
            <ul className="file-list">
              {files.length === 0 ? (
                <li style={{padding: '0.8rem', color: 'var(--text-muted)', fontSize: '0.8rem', textAlign: 'center'}}>
                  Workspace Empty
                </li>
              ) : (
                files.map((file) => (
                  <li
                    key={file}
                    className={`file-item ${selectedFile === file ? 'active' : ''}`}
                    onClick={() => setSelectedFile(file)}
                  >
                    📄 {file}
                  </li>
                ))
              )}
            </ul>
          </div>
          
          {/* Code Analytics Widget */}
          <div style={{height: '35%', display: 'flex', flexDirection: 'column', overflow: 'hidden', borderTop: '1px solid var(--border-glow)', paddingTop: '0.8rem'}}>
            <h3 className="sidebar-title">Code Analytics</h3>
            {analysisReport ? (
              <div style={{fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '0.5rem', padding: '0 0.5rem', overflowY: 'auto'}}>
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                  <span>File: <b>{analysisReport.filename}</b></span>
                  <span style={{
                    padding: '0.1rem 0.4rem',
                    borderRadius: '4px',
                    fontWeight: 700,
                    fontSize: '0.65rem',
                    background: analysisReport.risk === 'Safe' ? 'rgba(0, 242, 96, 0.2)' :
                                analysisReport.risk === 'Warning' ? 'rgba(255, 159, 67, 0.2)' : 'rgba(255, 56, 56, 0.2)',
                    color: analysisReport.risk === 'Safe' ? 'var(--accent-green)' :
                           analysisReport.risk === 'Warning' ? 'var(--accent-orange)' : 'var(--accent-red)'
                  }}>{analysisReport.risk} Risk</span>
                </div>
                
                <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.4rem', textAlign: 'center', margin: '0.2rem 0'}}>
                  <div style={{background: 'rgba(255,255,255,0.02)', padding: '0.4rem', borderRadius: '6px', border: '1px solid var(--border-glow)'}}>
                    <div style={{color: '#fff', fontWeight: 'bold', fontSize: '0.9rem'}}>{analysisReport.loc}</div>
                    <div style={{fontSize: '0.6rem', color: 'var(--text-muted)'}}>LOC</div>
                  </div>
                  <div style={{background: 'rgba(255,255,255,0.02)', padding: '0.4rem', borderRadius: '6px', border: '1px solid var(--border-glow)'}}>
                    <div style={{color: '#fff', fontWeight: 'bold', fontSize: '0.9rem'}}>{analysisReport.functions}</div>
                    <div style={{fontSize: '0.6rem', color: 'var(--text-muted)'}}>Funcs</div>
                  </div>
                  <div style={{background: 'rgba(255,255,255,0.02)', padding: '0.4rem', borderRadius: '6px', border: '1px solid var(--border-glow)'}}>
                    <div style={{color: '#fff', fontWeight: 'bold', fontSize: '0.9rem'}}>{analysisReport.classes}</div>
                    <div style={{fontSize: '0.6rem', color: 'var(--text-muted)'}}>Classes</div>
                  </div>
                </div>
                
                {analysisReport.warnings.length > 0 && (
                  <div style={{display: 'flex', flexDirection: 'column', gap: '0.4rem', marginTop: '0.2rem'}}>
                    <div style={{fontWeight: 700, fontSize: '0.65rem', textTransform: 'uppercase', color: 'var(--accent-orange)'}}>Security Alerts:</div>
                    <ul style={{listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.3rem', maxHeight: '70px', overflowY: 'auto'}}>
                      {analysisReport.warnings.map((w, idx) => (
                        <li key={idx} style={{
                          padding: '0.3rem',
                          background: 'rgba(255, 159, 67, 0.05)',
                          borderRadius: '4px',
                          borderLeft: '2px solid ' + (w.severity === 'medium' ? 'var(--accent-orange)' : 'var(--accent-red)'),
                          fontSize: '0.68rem',
                          lineHeight: '1.2'
                        }}>
                          Line {w.line}: {w.message}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            ) : (
              <div style={{color: 'var(--text-muted)', fontSize: '0.75rem', fontStyle: 'italic', textAlign: 'center', padding: '0.8rem'}}>
                Awaiting code analysis...
              </div>
            )}
          </div>
          
          {/* Git History */}
          <div style={{height: '35%', display: 'flex', flexDirection: 'column', overflow: 'hidden', borderTop: '1px solid var(--border-glow)', paddingTop: '0.8rem'}}>
            <h3 className="sidebar-title">Git History</h3>
            <ul className="git-list" style={{overflowY: 'auto', listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.5rem', padding: '0 0.5rem'}}>
              {gitCommits.length === 0 ? (
                <li style={{padding: '0.8rem', color: 'var(--text-muted)', fontSize: '0.8rem', textAlign: 'center', fontStyle: 'italic'}}>
                  No commits yet
                </li>
              ) : (
                gitCommits.map((commit, idx) => (
                  <li key={idx} style={{fontFamily: 'JetBrains Mono, monospace', fontSize: '0.72rem', display: 'flex', gap: '0.5rem', alignItems: 'baseline'}}>
                    <span style={{color: 'var(--accent-cyan)', fontWeight: 'bold'}}>{commit.hash}</span>
                    <span style={{color: 'var(--text-secondary)'}}>{commit.message}</span>
                  </li>
                ))
              )}
            </ul>
          </div>
        </div>

        {/* CENTER CONTENT: flowchart, code editor/HITL, terminal */}
        <div className="center-content">
          <div className="flow-graph-panel glass-panel">
            <div className={getNodeClass('Planner')}>
              <div className="agent-circle">Planner</div>
              <div className="agent-name">Plan</div>
            </div>
            <div className={getNodeClass('Coder')}>
              <div className="agent-circle">Coder</div>
              <div className="agent-name">Build</div>
            </div>
            <div className={getNodeClass('Reviewer')}>
              <div className="agent-circle">Reviewer</div>
              <div className="agent-name">QA</div>
            </div>
            <div className={getNodeClass('Executor')}>
              <div className="agent-circle">Executor</div>
              <div className="agent-name">Run</div>
            </div>
            <div className={getNodeClass('Debugger')}>
              <div className="agent-circle">Debugger</div>
              <div className="agent-name">Fix</div>
            </div>
            <div className={getNodeClass('Completed')}>
              <div className="agent-circle">Done</div>
              <div className="agent-name">Done</div>
            </div>
          </div>

          {/* Editor Panel with Human-in-the-loop popup overlay */}
          <div className="editor-panel glass-panel" style={{position: 'relative'}}>
            {hitlPrompt && (
              <div className="hitl-overlay" style={{
                position: 'absolute',
                top: 0, left: 0, right: 0, bottom: 0,
                background: 'rgba(7, 8, 13, 0.9)',
                zIndex: 100,
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                alignItems: 'center',
                padding: '2rem',
                textAlign: 'center',
                backdropFilter: 'blur(4px)'
              }}>
                <div className="glass-panel" style={{padding: '2rem', maxWidth: '500px', display: 'flex', flexDirection: 'column', gap: '1.2rem', borderColor: 'var(--accent-orange)'}}>
                  <div style={{fontSize: '1.8rem'}}>⚠️</div>
                  <h3 style={{fontWeight: 700, fontSize: '1.1rem', color: 'var(--accent-orange)'}}>
                    Awaiting Human Review ({hitlPrompt.agent} Agent)
                  </h3>
                  <p style={{fontSize: '0.85rem', color: 'var(--text-primary)', lineHeight: 1.5}}>
                    {hitlPrompt.message}
                  </p>
                  <input
                    type="text"
                    value={userResponse}
                    onChange={(e) => setUserResponse(e.target.value)}
                    placeholder="Provide feedback (e.g. Approved, or make subtraction divide...)"
                    style={{
                      background: 'var(--terminal-bg)',
                      border: '1px solid var(--border-glow)',
                      borderRadius: '8px',
                      color: '#fff',
                      padding: '0.6rem 0.8rem',
                      fontSize: '0.85rem',
                      width: '100%',
                      outline: 'none'
                    }}
                  />
                  <div style={{display: 'flex', gap: '1rem', justifyContent: 'center'}}>
                    <button
                      onClick={() => handleSendHitlResponse(userResponse || 'Approved')}
                      className="submit-btn"
                      style={{padding: '0.5rem 1.2rem', minWidth: '100px'}}
                    >
                      Approve & Resume
                    </button>
                    <button
                      onClick={() => handleSendHitlResponse(userResponse || 'Rejected')}
                      className="status-badge failed"
                      style={{padding: '0.5rem 1.2rem', border: 'none', cursor: 'pointer', borderRadius: '8px', fontWeight: 700}}
                    >
                      Reject
                    </button>
                  </div>
                </div>
              </div>
            )}

            <div className="editor-header">
              <span className="editor-filename">
                {selectedFile ? `editing: ${selectedFile}` : 'no file selected'}
              </span>
            </div>
            <div className="code-container">
              {selectedFile ? (
                <pre className="code-view">
                  <code>{fileContent}</code>
                </pre>
              ) : (
                <div className="empty-editor">
                  <svg fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
                  </svg>
                  <span>Select a generated file to view its code</span>
                </div>
              )}
            </div>
          </div>

          <div className="terminal-panel">
            <div className="terminal-header">
              <span className="terminal-title">Sandbox Console Terminal</span>
              {terminal && (
                <span style={{
                  fontSize: '0.75rem',
                  padding: '0.1rem 0.4rem',
                  borderRadius: '4px',
                  background: terminal.exit_code === 0 ? 'rgba(0, 242, 96, 0.2)' : 'rgba(255, 56, 56, 0.2)',
                  color: terminal.exit_code === 0 ? 'var(--accent-green)' : 'var(--accent-red)'
                }}>
                  exit code: {terminal.exit_code}
                </span>
              )}
            </div>
            <div className="terminal-body">
              {terminal ? (
                <div>
                  <div className="terminal-command">{terminal.command}</div>
                  {terminal.stdout && <div className="terminal-stdout">{terminal.stdout}</div>}
                  {terminal.stderr && <div className="terminal-stderr">{terminal.stderr}</div>}
                  <div ref={terminalEndRef} />
                </div>
              ) : (
                <div style={{color: 'var(--text-muted)', fontStyle: 'italic'}}>Terminal inactive. Ready for commands...</div>
              )}
            </div>
          </div>
        </div>

        {/* RIGHT SIDEBAR: Agent Discussion & Log Feed */}
        <div className="sidebar-logs">
          {/* Agent discussion bubble feed (top half of right sidebar) */}
          <div style={{flex: '1.2', display: 'flex', flexDirection: 'column', overflow: 'hidden', borderBottom: '1px solid var(--border-glow)', paddingBottom: '0.5rem'}}>
            <div className="logs-header" style={{paddingBottom: '0.5rem'}}>
              <h3 className="sidebar-title" style={{margin: 0}}>Agent Discussion</h3>
            </div>
            <div className="chat-feed" style={{flexGrow: 1, overflowY: 'auto', padding: '0.5rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.8rem'}}>
              {agentChatLogs.length === 0 ? (
                <div style={{color: 'var(--text-muted)', fontSize: '0.8rem', fontStyle: 'italic', textAlign: 'center', marginTop: '1.5rem'}}>
                  Agent communication quiet.
                </div>
              ) : (
                agentChatLogs.map((chat, idx) => (
                  <div key={idx} style={{
                    alignSelf: chat.from.includes('Planner') ? 'flex-start' : 'flex-end',
                    background: chat.from.includes('Planner') ? 'rgba(79, 172, 254, 0.08)' : 'rgba(0, 242, 96, 0.08)',
                    border: '1px solid ' + (chat.from.includes('Planner') ? 'rgba(79, 172, 254, 0.2)' : 'rgba(0, 242, 96, 0.2)'),
                    borderRadius: '12px',
                    padding: '0.5rem 0.8rem',
                    maxWidth: '85%',
                    fontSize: '0.8rem'
                  }}>
                    <div style={{fontWeight: 700, fontSize: '0.7rem', color: chat.from.includes('Planner') ? 'var(--accent-blue)' : 'var(--accent-green)', marginBottom: '0.2rem'}}>
                      {chat.from}
                    </div>
                    <div style={{color: 'var(--text-primary)', lineHeight: '1.3'}}>{chat.message}</div>
                  </div>
                ))
              )}
              <div ref={chatFeedEndRef} />
            </div>
          </div>

          {/* Standard Agent Logs (bottom half of right sidebar) */}
          <div style={{flex: '1.5', display: 'flex', flexDirection: 'column', overflow: 'hidden'}}>
            <div className="logs-header" style={{padding: '0.8rem 1rem 0.4rem 1rem'}}>
              <h3 className="sidebar-title" style={{margin: 0}}>Agent Output Log</h3>
            </div>
            <div className="log-feed">
              {logs.length === 0 ? (
                <div style={{color: 'var(--text-muted)', fontSize: '0.8rem', fontStyle: 'italic', textAlign: 'center', marginTop: '1.5rem'}}>
                  Awaiting logs...
                </div>
              ) : (
                logs.map((log, idx) => (
                  <div key={idx} className={`log-card ${log.level}`}>
                    <div className="log-meta">
                      <span className="log-agent">🤖 {log.agent}</span>
                      <span className="log-level" style={{
                        color: log.level === 'success' ? 'var(--accent-green)' :
                               log.level === 'error' ? 'var(--accent-red)' :
                               log.level === 'warning' ? 'var(--accent-orange)' :
                               'var(--accent-blue)'
                      }}>{log.level.toUpperCase()}</span>
                    </div>
                    <div className="log-body" style={{lineHeight: 1.4}}>{log.message}</div>
                  </div>
                ))
              )}
              <div ref={logFeedEndRef} />
            </div>

            <div className="control-panel">
              <form className="control-form" onSubmit={handleStartTask}>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Describe your coding task (e.g. Build an operations library with tests)..."
                  className="control-textarea"
                  disabled={running}
                />
                <div className="options-row">
                  <div style={{display: 'flex', flexDirection: 'column', gap: '0.4rem'}}>
                    <label className="toggle-container">
                      <input
                        type="checkbox"
                        checked={simulation}
                        onChange={(e) => setSimulation(e.target.checked)}
                        className="toggle-input"
                        disabled={running}
                      />
                      <span>Simulation Mode</span>
                    </label>
                    <label className="toggle-container">
                      <input
                        type="checkbox"
                        checked={autoApprove}
                        onChange={(e) => setAutoApprove(e.target.checked)}
                        className="toggle-input"
                        disabled={running}
                      />
                      <span>Auto-Approve (HITL)</span>
                    </label>
                  </div>
                  <button type="submit" disabled={running || !prompt.trim()} className="submit-btn">
                    {running ? 'Agent Working...' : 'Launch Agents'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;

// --------------------------------------------------------------------
// GStack Local Console - Client Logic Controller
// --------------------------------------------------------------------

const API_BASE = "http://127.0.0.1:8000";

let state = {
  currentPhase: "idle",
  phases: {},
  metrics: {
    active_model: "nvidia/nemotron-3-nano-omni",
    total_runs: 0,
    accumulated_savings: 0.0,
    latency_history: []
  }
};

let activeAgent = "ceo";
let activeFile = null;
let pollers = [];

// DOM Elements
const activeModelEl = document.getElementById("active-model-id");
const composerTextarea = document.getElementById("composer-textarea");
const sprintStartBtn = document.getElementById("sprint-start-btn");
const terminalOutput = document.getElementById("terminal-output");
const terminalName = document.getElementById("terminal-name");
const terminalPulse = document.getElementById("terminal-pulse");
const workspaceTree = document.getElementById("workspace-tree");
const previewFileTitle = document.getElementById("preview-file-title");
const previewFileContent = document.getElementById("preview-file-content");

const metricRuns = document.getElementById("metric-runs");
const metricSavings = document.getElementById("metric-savings");

const tabButtons = document.querySelectorAll(".tab-btn");

// --------------------------------------------------------------------
// 1. Initial Handshake & Setup
// --------------------------------------------------------------------
async function initializeDashboard() {
  try {
    const res = await fetch(`${API_BASE}/api/models`);
    const data = await res.json();
    if (data.active_model) {
      activeModelEl.textContent = data.active_model.split("/").pop();
    }
  } catch (e) {
    activeModelEl.textContent = "Offline (Check Server)";
  }
  
  setupEventListeners();
  startPollers();
}

// --------------------------------------------------------------------
// 2. Tab Bar & Action Event Listeners
// --------------------------------------------------------------------
function setupEventListeners() {
  // Tab Bar Switching
  tabButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      tabButtons.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeAgent = btn.getAttribute("data-agent");
      terminalName.textContent = `TERMINAL: ${activeAgent}_agent`;
      fetchAgentLog(); // Immediate fetch on switch
    });
  });

  // Launch Sprint Button
  sprintStartBtn.addEventListener("click", launchSprint);
}

// --------------------------------------------------------------------
// 3. Launch Sprint
// --------------------------------------------------------------------
async function launchSprint() {
  const goalText = composerTextarea.value.trim();
  if (!goalText) {
    alert("Please enter a software sprint goal!");
    return;
  }

  sprintStartBtn.disabled = true;
  sprintStartBtn.textContent = "Orchestrating... ⚡";
  
  terminalOutput.textContent = "🚀 Launching sprint. Bootstrapping YC-style gStack team agents...\n";

  try {
    const res = await fetch(`${API_BASE}/api/sprint/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goal: goalText })
    });
    const data = await res.json();
    
    if (data.status === "success") {
      terminalOutput.textContent += `⚡ Sprint successfully triggered in the background!\n` +
                                   `🤖 Connecting to local model via LM Link: nvidia/nemotron-3-nano-omni...\n` +
                                   `🧠 Phase 1 (Think/CEO) started!\n`;
    } else {
      alert(`Error starting sprint: ${data.message}`);
      sprintStartBtn.disabled = false;
      sprintStartBtn.textContent = "Launch Sprint ⚡";
    }
  } catch (e) {
    alert(`Failed to contact FastAPI server: ${e}`);
    sprintStartBtn.disabled = false;
    sprintStartBtn.textContent = "Launch Sprint ⚡";
  }
}

// --------------------------------------------------------------------
// 4. Background Data Pollers
// --------------------------------------------------------------------
function startPollers() {
  // Poll overall sprint status
  pollers.push(setInterval(fetchSprintStatus, 1500));
  // Poll current agent terminal logs
  pollers.push(setInterval(fetchAgentLog, 1000));
  // Poll workspace files tree
  pollers.push(setInterval(fetchWorkspaceFiles, 2000));
}

async function fetchSprintStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/sprint/status`);
    const data = await res.json();
    if (data && data.current_phase) {
      state = data;
      updateUIState();
    }
  } catch (e) {}
}

async function fetchAgentLog() {
  try {
    const res = await fetch(`${API_BASE}/api/agent/log?agent=${activeAgent}`);
    const data = await res.json();
    if (data && data.log) {
      // Auto scroll terminal if user is at bottom
      const shouldScroll = terminalOutput.scrollHeight - terminalOutput.clientHeight <= terminalOutput.scrollTop + 40;
      terminalOutput.textContent = data.log;
      if (shouldScroll) {
        terminalOutput.scrollTop = terminalOutput.scrollHeight;
      }
    }
  } catch (e) {}
}

async function fetchWorkspaceFiles() {
  try {
    const res = await fetch(`${API_BASE}/api/workspace/files`);
    const data = await res.json();
    if (data && data.files) {
      renderWorkspaceTree(data.files);
    }
  } catch (e) {}
}

// --------------------------------------------------------------------
// 5. Dynamic UI Updates (Timeline Nodes, Metrics, Sparkline)
// --------------------------------------------------------------------
function updateUIState() {
  // 1. Update Metrics
  metricRuns.textContent = state.metrics.total_runs || 0;
  metricSavings.textContent = `$${(state.metrics.accumulated_savings || 0).toFixed(2)}`;

  if (state.metrics.active_model) {
    activeModelEl.textContent = state.metrics.active_model.split("/").pop();
  }

  // 2. Sprint Start button state
  if (state.current_phase === "idle" || state.current_phase === "completed") {
    sprintStartBtn.disabled = false;
    sprintStartBtn.textContent = "Launch Sprint ⚡";
    terminalPulse.style.display = "none";
  } else {
    sprintStartBtn.disabled = true;
    sprintStartBtn.textContent = "Sprint Running... ⚡";
    terminalPulse.style.display = "block";
  }

  // 3. Update Timeline Stages Nodes
  const phasesOrder = ["think", "plan", "design", "build", "review", "test", "ship"];
  const currentIdx = phasesOrder.indexOf(state.current_phase);

  phasesOrder.forEach((phase, idx) => {
    // Map timeline node id
    const nodeId = `node-${phase}`;
    const nodeEl = document.getElementById(nodeId);
    if (!nodeEl) return;

    // Reset styles
    nodeEl.classList.remove("active", "completed");

    // Connectors mapping
    const connector = nodeEl.nextElementSibling;

    if (state.current_phase === phase) {
      nodeEl.classList.add("active");
    } else if (idx < currentIdx && currentIdx !== -1) {
      nodeEl.classList.add("completed");
      if (connector && connector.classList.contains("timeline-connector")) {
        connector.classList.add("completed");
      }
    } else if (state.current_phase === "completed") {
      nodeEl.classList.add("completed");
      if (connector && connector.classList.contains("timeline-connector")) {
        connector.classList.add("completed");
      }
    } else {
      if (connector && connector.classList.contains("timeline-connector")) {
        connector.classList.remove("completed");
      }
    }
  });

  // 4. Update Latency SVG Sparkline Graph
  renderLatencyChart(state.metrics.latency_history || []);
}

function renderWorkspaceTree(files) {
  if (!files || files.length === 0) {
    workspaceTree.innerHTML = `<span class="empty-state">No files built in workspace yet.</span>`;
    return;
  }

  let html = "";
  files.forEach(file => {
    const isActive = activeFile === file.name ? "active" : "";
    html += `
      <div class="file-item ${isActive}" onclick="inspectFile('${file.name}')">
        <span class="file-name">📄 ${file.name}</span>
        <span class="file-size">${file.size} B</span>
      </div>
    `;
  });
  workspaceTree.innerHTML = html;
}

async function inspectFile(filename) {
  activeFile = filename;
  previewFileTitle.textContent = `File Inspector: ${filename}`;
  previewFileContent.textContent = "Loading file content...";
  
  // Re-render files to highlight active class selection
  fetchWorkspaceFiles();

  try {
    const res = await fetch(`${API_BASE}/api/workspace/file?path=${filename}`);
    const data = await res.json();
    if (data && data.content) {
      previewFileContent.textContent = data.content;
    } else {
      previewFileContent.textContent = "Error: Could not read file content.";
    }
  } catch (e) {
    previewFileContent.textContent = `Error fetching file contents: ${e}`;
  }
}

// Make inspectFile globally accessible
window.inspectFile = inspectFile;

// --------------------------------------------------------------------
// 6. SVG Latency Chart Sparkline Render
// --------------------------------------------------------------------
function renderLatencyChart(history) {
  const svgPlaceholder = document.getElementById("chart-placeholder");
  const pathEl = document.getElementById("sparkline-path");
  const areaEl = document.getElementById("sparkline-area");

  if (!history || history.length === 0) {
    svgPlaceholder.style.display = "block";
    pathEl.setAttribute("d", "");
    areaEl.setAttribute("d", "");
    return;
  }

  svgPlaceholder.style.display = "none";

  const padding = 15;
  const chartWidth = 300;
  const chartHeight = 120;
  const drawWidth = chartWidth - padding * 2;
  const drawHeight = chartHeight - padding * 2;

  const pointsCount = history.length;
  const maxVal = Math.max(...history.map(d => d.duration), 10); // Minimum scale floor of 10s

  const points = history.map((item, idx) => {
    const x = padding + (idx / Math.max(pointsCount - 1, 1)) * drawWidth;
    const y = padding + drawHeight - (item.duration / maxVal) * drawHeight;
    return { x, y };
  });

  // Build sparkline SVG Path string
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length; i++) {
    d += ` L ${points[i].x} ${points[i].y}`;
  }
  pathEl.setAttribute("d", d);

  // Build enclosed SVG Area Path string
  let dArea = `${d} L ${points[points.length - 1].x} ${chartHeight - padding} L ${points[0].x} ${chartHeight - padding} Z`;
  areaEl.setAttribute("d", dArea);
}

// Launch initialization
document.addEventListener("DOMContentLoaded", initializeDashboard);

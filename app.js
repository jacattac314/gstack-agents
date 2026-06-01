// --------------------------------------------------------------------
// GStack Local Console - Client Logic Controller
// --------------------------------------------------------------------

const API_BASE = window.location.protocol.startsWith("http") ? window.location.origin : "http://127.0.0.1:8000";

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
let isInitialLoad = true;
let lastObservedPhase = null;

// DOM Elements
const activeModelEl = document.getElementById("active-model-id");
const composerTextarea = document.getElementById("composer-textarea");
const sprintActionBtn = document.getElementById("sprint-action-btn");
const sprintLaunchAppBtn = document.getElementById("sprint-launch-app-btn");
const drawerToggleBtn = document.getElementById("drawer-toggle-btn");

const providerSelect = document.getElementById("provider-select");
const freellmapiConfigSection = document.getElementById("freellmapi-config-section");
const freellmapiUrlInput = document.getElementById("freellmapi-url");
const freellmapiTokenInput = document.getElementById("freellmapi-token");
const freellmapiModelSelect = document.getElementById("freellmapi-model-select");
const providerSaveBtn = document.getElementById("provider-save-btn");
const gridContainer = document.querySelector(".dashboard-grid");
const pipelineNodes = document.querySelectorAll(".timeline-nodes .node");
const terminalOutput = document.getElementById("terminal-output");
const terminalName = document.getElementById("terminal-name");
const terminalPulse = document.getElementById("terminal-pulse");
const workspaceTree = document.getElementById("workspace-tree");
const previewFileTitle = document.getElementById("preview-file-title");
const previewFileContent = document.getElementById("preview-file-content");

const metricRuns = document.getElementById("metric-runs");
const metricSavings = document.getElementById("metric-savings");

// GitHub DOM Elements
const githubStatusDot = document.getElementById("github-status-dot");
const githubStatusText = document.getElementById("github-status-text");
const githubRepoName = document.getElementById("github-repo-name");
const githubRepoSelect = document.getElementById("github-repo-select");
const githubRepoSearch = document.getElementById("github-repo-search");
const githubRepoDesc = document.getElementById("github-repo-desc");
const githubSyncAction = document.getElementById("github-sync-action");
const githubSyncBtn = document.getElementById("github-sync-btn");
const githubFeedback = document.getElementById("github-feedback");

const githubLoginSection = document.getElementById("github-login-section");
const githubLoginBtn = document.getElementById("github-login-btn");
const githubPatToken = document.getElementById("github-pat-token");
const githubSyncSection = document.getElementById("github-sync-section");
const githubDivider = document.getElementById("github-divider");

// --------------------------------------------------------------------
// 1. Initial Handshake & Setup
// --------------------------------------------------------------------
async function initializeDashboard() {
  try {
    const res = await fetch(`${API_BASE}/api/models?_=${Date.now()}`);
    const data = await res.json();
    if (data.active_model) {
      activeModelEl.textContent = data.active_model.split("/").pop();
    }
  } catch (e) {
    activeModelEl.textContent = "Offline (Check Server)";
  }
  
  setupEventListeners();
  startPollers();
  
  // Initial loads
  fetchGitHubStatus();
  fetchWorkspaceFiles();
  fetchProviderConfig();
}

// --------------------------------------------------------------------
// 2. Tab Bar & Action Event Listeners & Repositories Fetcher
// --------------------------------------------------------------------
let fetchedRepos = [];
let repoToSelectAfterFetch = null;

async function fetchUserRepositories() {
  try {
    const res = await fetch(`${API_BASE}/api/github/repos?_=${Date.now()}`);
    const data = await res.json();
    if (data && data.repos) {
      fetchedRepos = data.repos;
      populateRepoDropdown();
    }
  } catch (e) {
    console.error("Failed to fetch user repositories:", e);
  }
}

function populateRepoDropdown(filteredList = null) {
  const currentVal = githubRepoSelect.value;
  const listToUse = filteredList !== null ? filteredList : fetchedRepos;
  
  if (listToUse.length === 0) {
    githubRepoSelect.innerHTML = `<option value="">No matching repositories</option>`;
    return;
  }
  
  let html = listToUse.map(repo => {
    const isPrivate = repo.private ? "🔒" : "🌐";
    return `<option value="${repo.name}">${isPrivate} ${repo.full_name}</option>`;
  }).join("");
  
  githubRepoSelect.innerHTML = html;
  
  // Auto-select the newly synced/created repository if registered
  if (repoToSelectAfterFetch && listToUse.some(r => r.name === repoToSelectAfterFetch)) {
    githubRepoSelect.value = repoToSelectAfterFetch;
    repoToSelectAfterFetch = null; // Reset single-shot trigger
  } else if (currentVal && listToUse.some(r => r.name === currentVal)) {
    githubRepoSelect.value = currentVal;
  }
}

function filterUserRepositories() {
  const query = githubRepoSearch.value.trim().toLowerCase();
  if (!query) {
    populateRepoDropdown();
    return;
  }
  
  const filtered = fetchedRepos.filter(repo => {
    return repo.name.toLowerCase().includes(query) || 
           repo.full_name.toLowerCase().includes(query);
  });
  
  populateRepoDropdown(filtered);
}

function toggleSyncActionFields() {
  const action = githubSyncAction.value;
  if (action === "connect") {
    githubRepoSearch.style.display = "block";
    githubRepoSelect.style.display = "block";
    githubRepoName.style.display = "none";
    githubRepoDesc.style.display = "none";
  } else {
    githubRepoSearch.style.display = "none";
    githubRepoSelect.style.display = "none";
    githubRepoName.style.display = "block";
    githubRepoDesc.style.display = "block";
  }
}

function setupEventListeners() {
  // Collapsible Control Panel Drawer Toggle
  drawerToggleBtn.addEventListener("click", () => {
    gridContainer.classList.toggle("drawer-collapsed");
    const isCollapsed = gridContainer.classList.contains("drawer-collapsed");
    drawerToggleBtn.textContent = isCollapsed ? "▶" : "◀";
    drawerToggleBtn.title = isCollapsed ? "Show Control Panel" : "Hide Control Panel";
  });

  // Clickable Pipeline Nodes Tab Switching
  pipelineNodes.forEach(node => {
    node.addEventListener("click", () => {
      activeAgent = node.getAttribute("data-agent");
      terminalName.textContent = `TERMINAL: ${activeAgent}_agent`;
      
      // Update visual active-tab class
      pipelineNodes.forEach(n => n.classList.remove("active-tab"));
      node.classList.add("active-tab");
      
      fetchAgentLog(); // Immediate fetch on switch
    });
  });

  // Sprint Toggle Action Button (Launch/Stop)
  sprintActionBtn.addEventListener("click", handleSprintAction);

  // Launch App Button
  sprintLaunchAppBtn.addEventListener("click", () => {
    const deliverable = state.phases && state.phases.build && state.phases.build.deliverable;
    if (deliverable) {
      window.open(`/workspace/app/${deliverable}`, "_blank");
    } else {
      window.open("/workspace/app/index.html", "_blank");
    }
  });

  // GitHub Sync Button
  githubSyncBtn.addEventListener("click", syncGitHubProject);

  // GitHub Login Button
  githubLoginBtn.addEventListener("click", loginGitHub);

  // Toggle sync fields based on action dropdown
  githubSyncAction.addEventListener("change", toggleSyncActionFields);

  // Handle typing inside the repository search bar for smart filtering
  githubRepoSearch.addEventListener("input", filterUserRepositories);

  // LLM Provider Dropdown change
  providerSelect.addEventListener("change", toggleProviderConfigFields);
  
  // Save LLM config button click
  providerSaveBtn.addEventListener("click", saveLLMProviderConfig);

  // Dynamic model loading when URL or Token is updated
  const refreshModelsList = () => {
    if (providerSelect.value === "freellmapi") {
      fetchFreeLLMAPIModels(
        freellmapiModelSelect.value || null,
        freellmapiUrlInput.value.trim() || null,
        freellmapiTokenInput.value.trim() || null
      );
    }
  };
  freellmapiUrlInput.addEventListener("blur", refreshModelsList);
  freellmapiUrlInput.addEventListener("change", refreshModelsList);
  freellmapiTokenInput.addEventListener("blur", refreshModelsList);
  freellmapiTokenInput.addEventListener("change", refreshModelsList);

  // Workspace Tab buttons
  const tabCodeBtn = document.getElementById("tab-code-btn");
  const tabPreviewBtn = document.getElementById("tab-preview-btn");
  const livePreviewRefresh = document.getElementById("live-preview-refresh");

  if (tabCodeBtn && tabPreviewBtn) {
    tabCodeBtn.addEventListener("click", () => switchTab("code"));
    tabPreviewBtn.addEventListener("click", () => switchTab("preview"));
  }

  if (livePreviewRefresh) {
    livePreviewRefresh.addEventListener("click", () => {
      const iframe = document.getElementById("live-preview-iframe");
      if (iframe) {
        // Force refresh iframe by resetting its src
        const currentSrc = iframe.src;
        iframe.src = "about:blank";
        setTimeout(() => {
          iframe.src = currentSrc;
        }, 50);
      }
    });
  }
}

function toggleProviderConfigFields() {
  const provider = providerSelect.value;
  if (provider === "freellmapi") {
    freellmapiConfigSection.style.display = "flex";
    // Fetch models automatically if provider is active
    fetchFreeLLMAPIModels(
      freellmapiModelSelect.value || null,
      freellmapiUrlInput.value.trim() || null,
      freellmapiTokenInput.value.trim() || null
    );
  } else {
    freellmapiConfigSection.style.display = "none";
  }
}

async function fetchFreeLLMAPIModels(selectedModel = null, url = null, token = null) {
  try {
    freellmapiModelSelect.innerHTML = `<option value="">Loading models list... ⏳</option>`;
    let fetchUrl = `${API_BASE}/api/config/freellmapi/models?_=${Date.now()}`;
    if (url) {
      fetchUrl += `&url=${encodeURIComponent(url)}`;
    }
    if (token) {
      fetchUrl += `&token=${encodeURIComponent(token)}`;
    }
    const res = await fetch(fetchUrl);
    const data = await res.json();
    
    if (data && data.data) {
      let html = "";
      data.data.forEach(model => {
        const nameLabel = model.name ? `${model.name} (${model.owned_by || 'proxy'})` : model.id;
        html += `<option value="${model.id}">${nameLabel}</option>`;
      });
      freellmapiModelSelect.innerHTML = html;
      
      if (selectedModel) {
        const exactMatch = data.data.some(m => m.id === selectedModel);
        if (exactMatch) {
          freellmapiModelSelect.value = selectedModel;
        } else {
          const flexibleMatch = data.data.find(m => m.id.endsWith('/' + selectedModel) || selectedModel.endsWith('/' + m.id));
          if (flexibleMatch) {
            freellmapiModelSelect.value = flexibleMatch.id;
          } else {
            // Append as fallback option to ensure it's selected and not lost
            const opt = document.createElement("option");
            opt.value = selectedModel;
            opt.textContent = `${selectedModel} (current)`;
            freellmapiModelSelect.appendChild(opt);
            freellmapiModelSelect.value = selectedModel;
          }
        }
      }
    } else {
      freellmapiModelSelect.innerHTML = `<option value="">No models resolved</option>`;
    }
  } catch (e) {
    console.error("Failed to fetch FreeLLMAPI models list:", e);
    freellmapiModelSelect.innerHTML = `<option value="">Error loading models</option>`;
  }
}

async function fetchProviderConfig() {
  try {
    const res = await fetch(`${API_BASE}/api/config/provider?_=${Date.now()}`);
    const data = await res.json();
    if (data) {
      providerSelect.value = data.provider || "lm_studio";
      freellmapiUrlInput.value = data.freellmapi_url || "http://localhost:3001/v1";
      freellmapiTokenInput.value = data.freellmapi_token || "";
      
      // Load the models list dynamically, and then select the active model
      await fetchFreeLLMAPIModels(data.freellmapi_model, data.freellmapi_url, data.freellmapi_token);
      
      toggleProviderConfigFields();
    }
  } catch (e) {
    console.error("Failed to fetch provider configuration:", e);
  }
}

async function saveLLMProviderConfig() {
  const provider = providerSelect.value;
  const url = freellmapiUrlInput.value.trim();
  const token = freellmapiTokenInput.value.trim();
  const model = freellmapiModelSelect.value;
  
  providerSaveBtn.disabled = true;
  providerSaveBtn.textContent = "Saving... 💾";
  
  try {
    const res = await fetch(`${API_BASE}/api/config/provider?_=${Date.now()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider,
        freellmapi_url: url,
        freellmapi_token: token,
        freellmapi_model: model
      })
    });
    const data = await res.json();
    
    if (data.status === "success") {
      alert("LLM Provider Configuration saved successfully!");
      // Instantly refresh model name badge
      const modelRes = await fetch(`${API_BASE}/api/models?_=${Date.now()}`);
      const modelData = await modelRes.json();
      if (modelData.active_model) {
        activeModelEl.textContent = modelData.active_model.split("/").pop();
      }
    } else {
      alert(`Failed to save configuration: ${data.message}`);
    }
  } catch (e) {
    alert(`Error communicating with FastAPI server: ${e}`);
  } finally {
    providerSaveBtn.disabled = false;
    providerSaveBtn.textContent = "Save LLM Config 💾";
  }
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

  // Clear progress bar and reset state immediately
  state = {
    goal: goalText,
    current_phase: "idle",
    phases: {
      think: {status: "pending", agent: "ceo", summary: ""},
      plan: {status: "pending", agent: "eng_manager", summary: ""},
      design: {status: "pending", agent: "designer", summary: ""},
      build: {status: "pending", agent: "coder", summary: ""},
      review: {status: "pending", agent: "release_engineer", summary: ""},
      test: {status: "pending", agent: "qa_lead", summary: ""},
      ship: {status: "pending", agent: "release_engineer", summary: ""}
    },
    metrics: {
      active_model: state.metrics?.active_model || "nvidia/nemotron-3-nano-omni",
      total_runs: state.metrics?.total_runs || 0,
      accumulated_savings: state.metrics?.accumulated_savings || 0.0,
      latency_history: state.metrics?.latency_history || []
    }
  };
  updateUIState();

  sprintActionBtn.disabled = true;
  sprintActionBtn.textContent = "Orchestrating... ⚡";
  
  terminalOutput.textContent = "🚀 Launching sprint. Bootstrapping YC-style gStack team agents...\n";

  try {
    const res = await fetch(`${API_BASE}/api/sprint/start?_=${Date.now()}`, {
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
      sprintActionBtn.disabled = false;
      sprintActionBtn.textContent = "Launch Sprint ⚡";
    }
  } catch (e) {
    alert(`Failed to contact FastAPI server: ${e}`);
    sprintActionBtn.disabled = false;
    sprintActionBtn.textContent = "Launch Sprint ⚡";
  }
}

// --------------------------------------------------------------------
// 4. GitHub Actions (Login & Sync)
// --------------------------------------------------------------------
async function loginGitHub() {
  const token = githubPatToken.value.trim();
  if (!token) {
    githubFeedback.textContent = "Error: Please enter a Personal Access Token!";
    githubFeedback.style.color = "var(--color-red)";
    return;
  }

  githubLoginBtn.disabled = true;
  githubLoginBtn.textContent = "Authenticating... ⚡";
  githubFeedback.textContent = "Verifying token credentials...";
  githubFeedback.style.color = "var(--color-yellow)";

  try {
    const res = await fetch(`${API_BASE}/api/github/login?_=${Date.now()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token })
    });
    const data = await res.json();

    if (data.status === "success") {
      githubFeedback.textContent = `Linked successfully! Connected as @${data.username}`;
      githubFeedback.style.color = "var(--color-green)";
      githubPatToken.value = "";
      
      // Instantly refresh states to swap panels
      await fetchGitHubStatus();
    } else {
      githubFeedback.textContent = `Auth failed: ${data.message}`;
      githubFeedback.style.color = "var(--color-red)";
    }
  } catch (e) {
    githubFeedback.textContent = `Auth error: ${e}`;
    githubFeedback.style.color = "var(--color-red)";
  } finally {
    githubLoginBtn.disabled = false;
    githubLoginBtn.textContent = "Link GitHub Token 🔑";
  }
}

async function syncGitHubProject() {
  const action = githubSyncAction.value;
  let repoName = "";
  let description = "";
  
  if (action === "connect") {
    repoName = githubRepoSelect.value;
  } else {
    repoName = githubRepoName.value.trim();
    description = githubRepoDesc.value.trim();
  }

  if (!repoName) {
    githubFeedback.textContent = "Error: Please select or enter a repository name!";
    githubFeedback.style.color = "var(--color-red)";
    return;
  }

  githubSyncBtn.disabled = true;
  githubSyncBtn.textContent = "Syncing... ⚡";
  githubFeedback.textContent = "Communicating with GitHub API gateway...";
  githubFeedback.style.color = "var(--color-yellow)";

  try {
    const res = await fetch(`${API_BASE}/api/github/sync?_=${Date.now()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, repo_name: repoName, description })
    });
    const data = await res.json();

    if (data.status === "success") {
      githubFeedback.textContent = data.message;
      githubFeedback.style.color = "var(--color-green)";
      
      if (action === "connect") {
        composerTextarea.placeholder = `Connected to remote repo. Suggest goals like: 'Inspect the files and fix any bugs in README.md' or 'Add a unit test script'`;
      }
      
      // Track newly created/synced repo for auto-selection
      repoToSelectAfterFetch = repoName;
      
      // Reset fetched repos list to force reload new repo addition on next status check
      fetchedRepos = [];
      
      // Automatically toggle sync action to connect to reveal repositories dropdown
      githubSyncAction.value = "connect";
      toggleSyncActionFields();
      
      // Clear inputs
      githubRepoName.value = "";
      githubRepoDesc.value = "";
      
      // Immediately refresh views
      fetchWorkspaceFiles();
      fetchGitHubStatus();
    } else {
      githubFeedback.textContent = `Sync failed: ${data.message}`;
      githubFeedback.style.color = "var(--color-red)";
    }
  } catch (e) {
    githubFeedback.textContent = `Network failure: ${e}`;
    githubFeedback.style.color = "var(--color-red)";
  } finally {
    githubSyncBtn.disabled = false;
    githubSyncBtn.textContent = "Sync GitHub Project ⚡";
  }
}

async function fetchGitHubStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/github/status?_=${Date.now()}`);
    const data = await res.json();
    
    if (data && data.authenticated) {
      githubStatusDot.className = "status-dot green";
      githubStatusText.textContent = `@${data.username} (Connected)`;
      
      // Connected State: Hide login inputs, show sync controllers
      githubLoginSection.style.display = "none";
      githubSyncSection.style.display = "flex";
      githubDivider.style.display = "block";
      
      // Fetch repositories once authenticated
      if (fetchedRepos.length === 0) {
        fetchUserRepositories();
      }
      
      toggleSyncActionFields();
      
      if (data.active_repo && data.active_repo !== "Not Configured") {
        const repoNameOnly = data.active_repo.split("/").pop().replace(".git", "");
        
        // Dynamically align repositories dropdown selector with backend active repo state
        if (githubSyncAction.value === "connect" && githubRepoSelect.value !== repoNameOnly) {
          if (Array.from(githubRepoSelect.options).some(opt => opt.value === repoNameOnly)) {
            githubRepoSelect.value = repoNameOnly;
          } else {
            repoToSelectAfterFetch = repoNameOnly;
          }
        }
        
        if (isInitialLoad) {
          if (githubSyncAction.value === "connect") {
            githubRepoSelect.value = repoNameOnly;
          } else {
            githubRepoName.value = repoNameOnly;
          }
          isInitialLoad = false;
        }
        githubStatusText.textContent = `@${data.username} (${repoNameOnly})`;
      }
    } else {
      githubStatusDot.className = "status-dot red";
      githubStatusText.textContent = "Disconnected";
      
      // Disconnected State: Show login inputs, hide sync controllers
      githubLoginSection.style.display = "flex";
      githubSyncSection.style.display = "none";
      githubDivider.style.display = "none";
    }
  } catch (e) {
    githubStatusDot.className = "status-dot red";
    githubStatusText.textContent = "FastAPI Offline";
  }
}

// --------------------------------------------------------------------
// 5. Background Data Pollers
// --------------------------------------------------------------------
function startPollers() {
  // Poll overall sprint status
  pollers.push(setInterval(fetchSprintStatus, 1500));
  // Poll current agent terminal logs
  pollers.push(setInterval(fetchAgentLog, 1000));
  // Poll workspace files tree
  pollers.push(setInterval(fetchWorkspaceFiles, 2000));
  // Poll GitHub authentication status
  pollers.push(setInterval(fetchGitHubStatus, 5000));
}

async function fetchSprintStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/sprint/status?_=${Date.now()}`);
    const data = await res.json();
    if (data && data.current_phase) {
      state = data;
      updateUIState();
    }
  } catch (e) {}
}

async function fetchAgentLog() {
  try {
    const res = await fetch(`${API_BASE}/api/agent/log?agent=${activeAgent}&_=${Date.now()}`);
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
    const res = await fetch(`${API_BASE}/api/workspace/files?_=${Date.now()}`);
    const data = await res.json();
    if (data && data.files) {
      renderWorkspaceTree(data.files);
    }
  } catch (e) {}
}

// --------------------------------------------------------------------
// 6. Dynamic UI Updates (Timeline Nodes, Metrics, Sparkline)
// --------------------------------------------------------------------
function updateUIState() {
  // 1. Update Metrics
  metricRuns.textContent = state.metrics.total_runs || 0;
  metricSavings.textContent = `$${(state.metrics.accumulated_savings || 0).toFixed(2)}`;

  if (state.metrics.active_model) {
    activeModelEl.textContent = state.metrics.active_model.split("/").pop();
  }

  // 2. Sprint Action Toggle Button State
  if (state.current_phase === "idle" || state.current_phase === "completed" || state.current_phase === "cancelled") {
    sprintActionBtn.disabled = false;
    sprintActionBtn.className = "glow-button";
    sprintActionBtn.textContent = "Launch Sprint ⚡";
    terminalPulse.style.display = "none";
  } else {
    // Keep it disabled if it is currently in "Stopping" state to prevent duplicate stop requests
    if (sprintActionBtn.textContent === "Stopping... 🛑") {
      sprintActionBtn.disabled = true;
    } else {
      sprintActionBtn.disabled = false;
      sprintActionBtn.className = "glow-button red";
      sprintActionBtn.textContent = "Stop Sprint 🛑";
    }
    terminalPulse.style.display = "block";
  }

  // Toggle Launch App Button visibility based on phase completion
  if (state.current_phase === "completed") {
    sprintLaunchAppBtn.style.display = "block";
  } else {
    sprintLaunchAppBtn.style.display = "none";
  }

  // Update Live Preview Iframe with Coder deliverable if available
  const deliverable = state.phases && state.phases.build && state.phases.build.deliverable;
  if (deliverable && deliverable.toLowerCase().endsWith(".html")) {
    const iframe = document.getElementById("live-preview-iframe");
    const previewUrl = document.getElementById("live-preview-url");
    if (iframe && previewUrl && iframe.src.indexOf(deliverable) === -1) {
      const url = `/workspace/app/${deliverable}`;
      iframe.src = url;
      previewUrl.textContent = url;
      // Auto-switch to Live Preview tab to show the user the live progress!
      switchTab("preview");
    }
  }

  // Auto-follow: if the current phase changed, automatically focus terminal on the new active agent
  const currentRunningPhase = state.current_phase;
  if (currentRunningPhase && currentRunningPhase !== lastObservedPhase) {
    const phaseToAgentMap = {
      think: "ceo",
      plan: "eng_manager",
      design: "designer",
      build: "coder",
      review: "release_engineer",
      test: "qa_lead",
      ship: "release_engineer"
    };
    
    if (phaseToAgentMap[currentRunningPhase]) {
      activeAgent = phaseToAgentMap[currentRunningPhase];
      terminalName.textContent = `TERMINAL: ${activeAgent}_agent`;
      fetchAgentLog(); // Fetch logs immediately for the new agent!
    }
    lastObservedPhase = currentRunningPhase;
  }

  // 3. Update Timeline Stages Nodes & Badges
  const phasesOrder = ["think", "plan", "design", "build", "review", "test", "ship"];
  const currentIdx = phasesOrder.indexOf(state.current_phase);

  phasesOrder.forEach((phase, idx) => {
    // Map timeline node id
    const nodeId = `node-${phase}`;
    const nodeEl = document.getElementById(nodeId);
    if (!nodeEl) return;

    // Reset styles
    nodeEl.classList.remove("active", "completed", "cancelled");

    const badgeEl = document.getElementById(`badge-${phase}`);
    if (badgeEl) {
      badgeEl.className = "node-status-badge";
      badgeEl.innerHTML = "";
    }

    // Connectors mapping
    const connector = nodeEl.nextElementSibling;

    // Highlight currently viewed agent tab in terminal console
    const viewedAgent = nodeEl.getAttribute("data-agent");
    if (viewedAgent === activeAgent) {
      nodeEl.classList.add("active-tab");
    } else {
      nodeEl.classList.remove("active-tab");
    }

    if (state.phases[phase] && state.phases[phase].status === "cancelled") {
      nodeEl.classList.add("cancelled");
      if (badgeEl) {
        badgeEl.classList.add("active", "cancelled");
        badgeEl.textContent = "✗";
      }
      if (connector && connector.classList.contains("timeline-connector")) {
        connector.classList.remove("completed");
      }
    } else if (state.current_phase === phase) {
      nodeEl.classList.add("active");
      if (badgeEl) {
        badgeEl.classList.add("active", "running");
        badgeEl.innerHTML = '<div class="mini-spinner"></div>';
      }
    } else if (state.phases[phase] && state.phases[phase].status === "completed") {
      nodeEl.classList.add("completed");
      if (badgeEl) {
        badgeEl.classList.add("active", "completed");
        badgeEl.textContent = "✓";
      }
      if (connector && connector.classList.contains("timeline-connector")) {
        connector.classList.add("completed");
      }
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
  // Update dynamic file count badge
  const fileCountEl = document.getElementById("file-count-badge");
  if (fileCountEl) {
    fileCountEl.textContent = `${files ? files.length : 0} Files`;
  }

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
    const res = await fetch(`${API_BASE}/api/workspace/file?path=${filename}&_=${Date.now()}`);
    const data = await res.json();
    if (data && data.content) {
      previewFileContent.textContent = data.content;
      
      // If it's a HTML file, load it inside the live preview iframe!
      if (filename.toLowerCase().endsWith(".html")) {
        const iframe = document.getElementById("live-preview-iframe");
        const previewUrl = document.getElementById("live-preview-url");
        if (iframe && previewUrl) {
          const url = `/workspace/app/${filename}`;
          iframe.src = url;
          previewUrl.textContent = url;
          // Auto-switch to Live Preview tab to show the rendered output!
          switchTab("preview");
        }
      } else {
        // If we select a non-HTML file, switch back to the code tab
        switchTab("code");
      }
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
// 7. SVG Latency Chart Sparkline Render
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

async function handleSprintAction() {
  if (state.current_phase === "idle" || state.current_phase === "completed" || state.current_phase === "cancelled") {
    await launchSprint();
  } else {
    await stopSprint();
  }
}

async function stopSprint() {
  if (!confirm("Are you sure you want to stop the current sprint?")) {
    return;
  }
  
  sprintActionBtn.disabled = true;
  sprintActionBtn.textContent = "Stopping... 🛑";
  
  try {
    const res = await fetch(`${API_BASE}/api/sprint/stop?_=${Date.now()}`, {
      method: "POST"
    });
    const data = await res.json();
    
    if (data.status === "success") {
      terminalOutput.textContent += `\n🛑 Sprint cancellation requested successfully!\n`;
    } else {
      alert(`Error stopping sprint: ${data.message}`);
      sprintActionBtn.disabled = false;
      sprintActionBtn.textContent = "Stop Sprint 🛑";
    }
  } catch (e) {
    alert(`Failed to contact FastAPI server: ${e}`);
    sprintActionBtn.disabled = false;
    sprintActionBtn.textContent = "Stop Sprint 🛑";
  }
}

function switchTab(tabName) {
  const tabCodeBtn = document.getElementById("tab-code-btn");
  const tabPreviewBtn = document.getElementById("tab-preview-btn");
  const tabCodeContent = document.getElementById("tab-code-content");
  const tabPreviewContent = document.getElementById("tab-preview-content");

  if (!tabCodeBtn || !tabPreviewBtn || !tabCodeContent || !tabPreviewContent) return;

  if (tabName === "code") {
    tabCodeBtn.classList.add("active");
    tabCodeBtn.style.background = "rgba(255, 255, 255, 0.08)";
    tabCodeBtn.style.color = "var(--text-color)";
    
    tabPreviewBtn.classList.remove("active");
    tabPreviewBtn.style.background = "none";
    tabPreviewBtn.style.color = "rgba(255, 255, 255, 0.6)";
    
    tabCodeContent.style.display = "flex";
    tabPreviewContent.style.display = "none";
  } else if (tabName === "preview") {
    tabPreviewBtn.classList.add("active");
    tabPreviewBtn.style.background = "rgba(255, 255, 255, 0.08)";
    tabPreviewBtn.style.color = "var(--text-color)";
    
    tabCodeBtn.classList.remove("active");
    tabCodeBtn.style.background = "none";
    tabCodeBtn.style.color = "rgba(255, 255, 255, 0.6)";
    
    tabPreviewContent.style.display = "flex";
    tabCodeContent.style.display = "none";
  }
}

// Launch initialization
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeDashboard);
} else {
  initializeDashboard();
}

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

const PHASE_ORDER = ["think", "plan", "design", "build", "review", "test", "ship"];
const PHASE_DETAILS = {
  think: {
    label: "Think",
    agent: "CEO Agent",
    pending: "Will clarify the objective, constraints, and success criteria.",
    running: "CEO Agent is shaping the brief and deciding what the sprint should deliver.",
    completed: "CEO Agent brainstormed the brief spec."
  },
  plan: {
    label: "Plan",
    agent: "Eng Manager",
    pending: "Will turn the brief into a practical technical plan.",
    running: "Eng Manager is mapping implementation steps, risks, and file targets.",
    completed: "Eng Manager designed the technical spec."
  },
  design: {
    label: "Design",
    agent: "Designer",
    pending: "Will define the visual direction, layout, and interaction details.",
    running: "Designer is shaping the UI, spacing, visual hierarchy, and polish.",
    completed: "Designer styled the UI and layout."
  },
  build: {
    label: "Build",
    agent: "Coder Agent",
    pending: "Will write the working code and produce a runnable artifact.",
    running: "Coder Agent is implementing the sprint deliverable.",
    completed: "Coder Agent wrote the working code."
  },
  review: {
    label: "Review",
    agent: "Release Eng",
    pending: "Will review the implementation for correctness and release risk.",
    running: "Release Eng is checking the code for problems before QA.",
    completed: "Release Eng reviewed the code."
  },
  test: {
    label: "Test",
    agent: "QA Lead",
    pending: "Will verify the result and look for user-visible failures.",
    running: "QA Lead is testing the artifact and checking behavior.",
    completed: "QA Lead ran verification tests."
  },
  ship: {
    label: "Ship",
    agent: "Release Eng",
    pending: "Will package the final result and report the outcome.",
    running: "Release Eng is preparing the sprint output for handoff.",
    completed: "Release Eng bundled and shipped the app."
  }
};

// DOM Elements
const activeModelEl = document.getElementById("active-model-id");
const composerTextarea = document.getElementById("composer-textarea");
const sprintActionBtn = document.getElementById("sprint-action-btn");
const sprintLaunchAppBtn = document.getElementById("sprint-launch-app-btn");
const sprintClearBtn = document.getElementById("sprint-clear-btn");
const drawerToggleBtn = document.getElementById("drawer-toggle-btn");
const inspectorToggleBtn = document.getElementById("inspector-toggle-btn");

const providerSelect = document.getElementById("provider-select");
const freellmapiConfigSection = document.getElementById("freellmapi-config-section");
const freellmapiUrlInput = document.getElementById("freellmapi-url");
const freellmapiTokenInput = document.getElementById("freellmapi-token");
const freellmapiModelSelect = document.getElementById("freellmapi-model-select");
const providerSaveBtn = document.getElementById("provider-save-btn");
const gridContainer = document.querySelector(".dashboard-grid");
const pipelineNodes = document.querySelectorAll(".runway-viewport .node-3d");
const terminalOutput = document.getElementById("terminal-output");
const terminalName = document.getElementById("terminal-name");
const terminalPulse = document.getElementById("terminal-pulse");
const workspaceTree = document.getElementById("workspace-tree");
const previewFileTitle = document.getElementById("preview-file-title");
const previewFileContent = document.getElementById("preview-file-content");

const metricRuns = document.getElementById("metric-runs");
const metricSavings = document.getElementById("metric-savings");

function replaceSelectOptions(selectEl, options) {
  selectEl.replaceChildren(...options);
}

function createOption(value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  return option;
}

function workspaceFileUrl(filename) {
  return `${API_BASE}/workspace/app/${encodeURIComponent(filename)}`;
}

function compactTooltipText(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  return text.length > 140 ? `${text.slice(0, 137)}...` : text;
}

function getPhaseTooltip(phase, phaseState, index, currentIndex) {
  const details = PHASE_DETAILS[phase];
  const status = phaseState && phaseState.status ? phaseState.status : "pending";

  if (status === "failed") {
    const reason = compactTooltipText(phaseState.error || phaseState.summary);
    return `${details.label} · Failed\n${reason || "This phase could not complete."}`;
  }

  if (status === "cancelled") {
    return `${details.label} · Cancelled\nThis phase was stopped before it finished.`;
  }

  if (state.current_phase === phase || status === "running") {
    return `${details.label} · Running\n${details.running}`;
  }

  if (status === "completed" || state.current_phase === "completed" || (currentIndex !== -1 && index < currentIndex)) {
    const summary = compactTooltipText(phaseState && phaseState.summary);
    return summary
      ? `${details.label} · Done\n${details.completed}\nResult: ${summary}`
      : `${details.label} · Done\n${details.completed}`;
  }

  return `${details.label} · Queued\n${details.pending}`;
}

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

function formatModelBadgeText(modelStr) {
  if (!modelStr) return "Not Configured";
  const parts = modelStr.split("/");
  const leafModel = parts[parts.length - 1];
  if (leafModel.includes(":")) {
    const subparts = leafModel.split(":");
    const provider = subparts[0].trim();
    const modelName = subparts.slice(1).join(":").trim();
    return `${modelName} (${provider})`;
  }
  return leafModel;
}

// --------------------------------------------------------------------
// 1. Initial Handshake & Setup
// --------------------------------------------------------------------
async function initializeDashboard() {
  try {
    const res = await fetch(`${API_BASE}/api/models?_=${Date.now()}`);
    const data = await res.json();
    if (data.active_model) {
      activeModelEl.textContent = formatModelBadgeText(data.active_model);
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
  fetchWebhookConfig();
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
    replaceSelectOptions(githubRepoSelect, [createOption("", "No matching repositories")]);
    return;
  }
  
  const options = listToUse.map(repo => {
    const isPrivate = repo.private ? "🔒" : "🌐";
    return createOption(repo.name, `${isPrivate} ${repo.full_name}`);
  });
  replaceSelectOptions(githubRepoSelect, options);
  
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
  const searchEl = document.getElementById("github-repo-search");
  const searchLabel = document.getElementById("github-repo-search-label");
  const selectEl = document.getElementById("github-repo-select");
  const selectLabel = document.getElementById("github-repo-select-label");
  const nameEl = document.getElementById("github-repo-name");
  const nameLabel = document.getElementById("github-repo-name-label");
  const descEl = document.getElementById("github-repo-desc");
  const descLabel = document.getElementById("github-repo-desc-label");

  if (action === "connect") {
    if (searchEl) searchEl.style.display = "block";
    if (searchLabel) searchLabel.style.display = "block";
    if (selectEl) selectEl.style.display = "block";
    if (selectLabel) selectLabel.style.display = "block";
    if (nameEl) nameEl.style.display = "none";
    if (nameLabel) nameLabel.style.display = "none";
    if (descEl) descEl.style.display = "none";
    if (descLabel) descLabel.style.display = "none";
  } else {
    if (searchEl) searchEl.style.display = "none";
    if (searchLabel) searchLabel.style.display = "none";
    if (selectEl) selectEl.style.display = "none";
    if (selectLabel) selectLabel.style.display = "none";
    if (nameEl) nameEl.style.display = "block";
    if (nameLabel) nameLabel.style.display = "block";
    if (descEl) descEl.style.display = "block";
    if (descLabel) descLabel.style.display = "block";
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

  // Collapsible Workspace Inspector Toggle
  inspectorToggleBtn.addEventListener("click", () => {
    gridContainer.classList.toggle("inspector-collapsed");
    const isCollapsed = gridContainer.classList.contains("inspector-collapsed");
    inspectorToggleBtn.textContent = isCollapsed ? "◀" : "▶";
    inspectorToggleBtn.title = isCollapsed ? "Show Workspace Inspector" : "Hide Workspace Inspector";
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

  // Reset Dashboard Button
  if (sprintClearBtn) {
    sprintClearBtn.addEventListener("click", handleResetDashboard);
  }

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
    if (providerSelect.value === "freellmapi" || providerSelect.value === "cloud_first") {
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

  // GitHub panel toggle
  const githubPanelHeader = document.getElementById("github-panel-header");
  const githubPanelBody = document.getElementById("github-panel-body");
  const githubToggleIcon = document.getElementById("github-toggle-icon");
  if (githubPanelHeader && githubPanelBody && githubToggleIcon) {
    githubPanelHeader.addEventListener("click", () => {
      const isHidden = githubPanelBody.style.display === "none";
      githubPanelBody.style.display = isHidden ? "block" : "none";
      githubToggleIcon.style.transform = isHidden ? "rotate(180deg)" : "rotate(0deg)";
    });
  }

  // Provider panel toggle
  const providerPanelHeader = document.getElementById("provider-panel-header");
  const providerPanelBody = document.getElementById("provider-panel-body");
  const providerToggleIcon = document.getElementById("provider-toggle-icon");
  if (providerPanelHeader && providerPanelBody && providerToggleIcon) {
    providerPanelHeader.addEventListener("click", () => {
      const isHidden = providerPanelBody.style.display === "none";
      providerPanelBody.style.display = isHidden ? "flex" : "none";
      providerToggleIcon.style.transform = isHidden ? "rotate(180deg)" : "rotate(0deg)";
    });
  }

  // Webhook Configuration panel toggle
  const webhookPanelHeader = document.getElementById("webhook-panel-header");
  const webhookPanelBody = document.getElementById("webhook-panel-body");
  const webhookToggleIcon = document.getElementById("webhook-toggle-icon");
  if (webhookPanelHeader && webhookPanelBody && webhookToggleIcon) {
    webhookPanelHeader.addEventListener("click", () => {
      const isHidden = webhookPanelBody.style.display === "none";
      webhookPanelBody.style.display = isHidden ? "flex" : "none";
      webhookToggleIcon.style.transform = isHidden ? "rotate(180deg)" : "rotate(0deg)";
    });
  }

  // Webhook save button
  const webhookSaveBtn = document.getElementById("webhook-save-btn");
  if (webhookSaveBtn) {
    webhookSaveBtn.addEventListener("click", saveWebhookConfig);
  }

  // HITL Modal buttons
  const hitlApproveBtn = document.getElementById("hitl-approve-btn");
  const hitlRejectBtn = document.getElementById("hitl-reject-btn");
  if (hitlApproveBtn && hitlRejectBtn) {
    hitlApproveBtn.addEventListener("click", handleHITLApprove);
    hitlRejectBtn.addEventListener("click", handleHITLReject);
  }

  // GitHub PAT password reveal
  const githubRevealBtn = document.getElementById("github-reveal-btn");
  const githubPatToken = document.getElementById("github-pat-token");
  if (githubRevealBtn && githubPatToken) {
    githubRevealBtn.addEventListener("click", () => {
      const isPassword = githubPatToken.type === "password";
      githubPatToken.type = isPassword ? "text" : "password";
      githubRevealBtn.textContent = isPassword ? "Hide" : "Show";
    });
  }

  // FreeLLMAPI Key password reveal
  const freellmapiRevealBtn = document.getElementById("freellmapi-reveal-btn");
  const freellmapiToken = document.getElementById("freellmapi-token");
  if (freellmapiRevealBtn && freellmapiToken) {
    freellmapiRevealBtn.addEventListener("click", () => {
      const isPassword = freellmapiToken.type === "password";
      freellmapiToken.type = isPassword ? "text" : "password";
      freellmapiRevealBtn.textContent = isPassword ? "Hide" : "Show";
    });
  }

  // FreeLLMAPI Models search filter
  const freellmapiModelSearch = document.getElementById("freellmapi-model-search");
  if (freellmapiModelSearch) {
    freellmapiModelSearch.addEventListener("input", () => {
      const query = freellmapiModelSearch.value.trim().toLowerCase();
      filterGroupedModels(query, freellmapiModelSelect.value);
    });
  }
}

function toggleProviderConfigFields() {
  const provider = providerSelect.value;
  if (provider === "freellmapi" || provider === "cloud_first") {
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

let fetchedModels = [];

function filterGroupedModels(query = "", selectedModel = null) {
  // Clear previous options
  freellmapiModelSelect.replaceChildren();

  const groups = {};
  fetchedModels.forEach(model => {
    const matchesQuery = !query || 
      model.id.toLowerCase().includes(query) || 
      (model.name && model.name.toLowerCase().includes(query));
      
    if (matchesQuery) {
      const provider = model.owned_by || "Other Providers";
      const formattedProvider = provider.charAt(0).toUpperCase() + provider.slice(1);
      if (!groups[formattedProvider]) {
        groups[formattedProvider] = [];
      }
      groups[formattedProvider].push(model);
    }
  });

  for (const [provider, models] of Object.entries(groups)) {
    const optgroup = document.createElement("optgroup");
    optgroup.label = provider;
    models.forEach(model => {
      const nameLabel = model.name ? model.name : model.id;
      const opt = createOption(model.id, nameLabel);
      optgroup.appendChild(opt);
    });
    freellmapiModelSelect.appendChild(optgroup);
  }

  if (Object.keys(groups).length === 0) {
    replaceSelectOptions(freellmapiModelSelect, [createOption("", "No matching models found")]);
  } else if (selectedModel) {
    // Attempt to set the selected model
    const exactMatch = fetchedModels.some(m => m.id === selectedModel);
    if (exactMatch) {
      freellmapiModelSelect.value = selectedModel;
    } else {
      const flexibleMatch = fetchedModels.find(m => m.id.endsWith('/' + selectedModel) || selectedModel.endsWith('/' + m.id));
      if (flexibleMatch) {
        freellmapiModelSelect.value = flexibleMatch.id;
      }
    }
  }
}

async function fetchFreeLLMAPIModels(selectedModel = null, url = null, token = null) {
  try {
    replaceSelectOptions(freellmapiModelSelect, [createOption("", "Loading models list... ⏳")]);
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
      fetchedModels = data.data;
      filterGroupedModels("", selectedModel);
      
      // If selectedModel is still not set correctly, append it as a safe fallback option
      if (selectedModel && freellmapiModelSelect.value !== selectedModel) {
        const exactMatch = data.data.some(m => m.id === selectedModel);
        const flexibleMatch = data.data.find(m => m.id.endsWith('/' + selectedModel) || selectedModel.endsWith('/' + m.id));
        if (!exactMatch && !flexibleMatch) {
          const opt = document.createElement("option");
          opt.value = selectedModel;
          opt.textContent = `${selectedModel} (current)`;
          freellmapiModelSelect.appendChild(opt);
          freellmapiModelSelect.value = selectedModel;
        }
      }
    } else {
      replaceSelectOptions(freellmapiModelSelect, [createOption("", "No models resolved")]);
    }
  } catch (e) {
    console.error("Failed to fetch FreeLLMAPI models list:", e);
    replaceSelectOptions(freellmapiModelSelect, [createOption("", "Error loading models")]);
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
  updateButtonState(providerSaveBtn, "Saving... 💾", "save");
  
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
        activeModelEl.textContent = formatModelBadgeText(modelData.active_model);
      }
    } else {
      alert(`Failed to save configuration: ${data.message}`);
    }
  } catch (e) {
    alert(`Error communicating with FastAPI server: ${e}`);
  } finally {
    providerSaveBtn.disabled = false;
    updateButtonState(providerSaveBtn, "Save LLM Config 💾", "save");
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
  updateSprintButtonState("Orchestrating... ⚡");
  
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
      updateSprintButtonState("Launch Sprint ⚡");
    }
  } catch (e) {
    alert(`Failed to contact FastAPI server: ${e}`);
    sprintActionBtn.disabled = false;
    updateSprintButtonState("Launch Sprint ⚡");
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
  updateButtonState(githubLoginBtn, "Authenticating... ⚡", "key");
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
    updateButtonState(githubLoginBtn, "Link GitHub Token 🔑", "key");
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
  updateButtonState(githubSyncBtn, "Syncing... ⚡", "sync");
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
    updateButtonState(githubSyncBtn, "Sync GitHub Project ⚡", "sync");
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
let renderedDebateCount = 0;

function startPollers() {
  // Poll overall sprint status
  pollers.push(setInterval(fetchSprintStatus, 1500));
  // Poll current agent terminal logs
  pollers.push(setInterval(fetchAgentLog, 1000));
  // Poll workspace files tree
  pollers.push(setInterval(fetchWorkspaceFiles, 2000));
  // Poll GitHub authentication status
  pollers.push(setInterval(fetchGitHubStatus, 5000));
  // Poll HITL Command approvals status
  pollers.push(setInterval(checkHITLApproval, 1000));
  // Poll real-time agent debate dialogues
  pollers.push(setInterval(fetchDebateLogs, 1500));
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

async function fetchDebateLogs() {
  const debateContainer = document.getElementById("debate-chat-container");
  const activeAgentsLabel = document.getElementById("debate-active-agents");
  if (!debateContainer || !activeAgentsLabel) return;
  
  try {
    const res = await fetch(`${API_BASE}/api/sprint/debate?_=${Date.now()}`);
    const messages = await res.json();
    
    if (Array.isArray(messages) && messages.length > 0) {
      if (messages.length !== renderedDebateCount) {
        if (renderedDebateCount === 0 || messages.length < renderedDebateCount) {
          debateContainer.innerHTML = "";
        }
        
        for (let i = (renderedDebateCount === 0 || messages.length < renderedDebateCount) ? 0 : renderedDebateCount; i < messages.length; i++) {
          const msg = messages[i];
          const msgEl = document.createElement("div");
          msgEl.className = `debate-message ${msg.avatar}`;
          
          const initials = msg.sender.split(" ").map(w => w[0]).join("").substring(0, 2).toUpperCase();
          
          msgEl.innerHTML = `
            <div class="debate-message-header">
              <div class="debate-msg-avatar debate-avatar-${msg.avatar}">${initials}</div>
              <span class="debate-msg-sender">${msg.sender}</span>
              <span class="debate-msg-time">${msg.timestamp}</span>
            </div>
            <div class="debate-msg-content">${msg.content}</div>
          `;
          debateContainer.appendChild(msgEl);
        }
        
        renderedDebateCount = messages.length;
        debateContainer.scrollTop = debateContainer.scrollHeight;
      }
      
      const currentMsg = messages[messages.length - 1];
      const stage = currentMsg.phase ? currentMsg.phase.toUpperCase() : "SPRINT";
      activeAgentsLabel.textContent = `Active debate in [${stage}] phase...`;
    } else {
      if (renderedDebateCount !== 0) {
        debateContainer.innerHTML = `
          <div class="debate-placeholder-text">
            Start a new sprint goal to watch the agents debate architectural specifications and security boundaries.
          </div>
        `;
        renderedDebateCount = 0;
      }
      activeAgentsLabel.textContent = "Awaiting sprint...";
    }
  } catch (e) {
    console.error("Error polling debate logs:", e);
  }
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
    activeModelEl.textContent = formatModelBadgeText(state.metrics.active_model);
  }

  // 2. Sprint Action Toggle Button State
  if (state.current_phase === "idle" || state.current_phase === "completed" || state.current_phase === "cancelled") {
    sprintActionBtn.disabled = false;
    sprintActionBtn.className = "glow-button";
    updateSprintButtonState("Launch Sprint ⚡");
    terminalPulse.style.display = "none";
  } else {
    // Keep it disabled if it is currently in "Stopping" state to prevent duplicate stop requests
    if (sprintActionBtn.textContent.includes("Stopping")) {
      sprintActionBtn.disabled = true;
    } else {
      sprintActionBtn.disabled = false;
      sprintActionBtn.className = "glow-button red";
      updateSprintButtonState("Stop Sprint 🛑");
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
      const url = workspaceFileUrl(deliverable);
      iframe.src = url;
      previewUrl.textContent = url;
      // Auto-switch to Live Preview tab to show the user the live progress!
      switchTab("preview");
    }
  }

  // Update 3D Runway Text dynamically based on active sprint steps
  const runwayOverlay = document.getElementById("runway-text-overlay");
  if (runwayOverlay) {
    let lines = [];

    let lineIndex = 1;
    PHASE_ORDER.forEach(p => {
      const pState = state.phases[p];
      if (pState && (pState.status === "completed" || state.current_phase === p)) {
        const isCurrent = state.current_phase === p;
        const icon = pState.status === "completed" ? "✓" : "⚡";
        const color = isCurrent ? "#fff" : "rgba(255,255,255,0.6)";
        const weight = isCurrent ? "bold" : "normal";
        lines.push(`<div class="runway-line" style="color: ${color}; font-weight: ${weight}; margin-bottom: 4px;">${lineIndex}. ${icon} <strong>${PHASE_DETAILS[p].completed}</strong></div>`);
        lineIndex++;
      }
    });

    if (lines.length === 0) {
      lines.push(`<div class="runway-line" style="color: rgba(255,255,255,0.55); font-style: italic;">Waiting to bootstrap engineering team agents... Ready.</div>`);
    }

    runwayOverlay.innerHTML = lines.join("");
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
  const currentIdx = PHASE_ORDER.indexOf(state.current_phase);

  PHASE_ORDER.forEach((phase, idx) => {
    // Map timeline node id
    const nodeId = `node-${phase}`;
    const nodeEl = document.getElementById(nodeId);
    if (!nodeEl) return;

    // Reset styles
    nodeEl.classList.remove("active", "completed", "cancelled", "failed");
    const phaseState = state.phases[phase];
    const tooltip = getPhaseTooltip(phase, phaseState, idx, currentIdx);
    nodeEl.tabIndex = 0;
    nodeEl.setAttribute("role", "button");
    nodeEl.setAttribute("aria-label", tooltip.replace(/\n/g, ". "));
    nodeEl.setAttribute("title", tooltip);
    nodeEl.dataset.tooltip = tooltip;

    const badgeEl = document.getElementById(`badge-${phase}`);
    if (badgeEl) {
      badgeEl.className = "node-3d-badge";
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

    if (phaseState && phaseState.status === "failed") {
      nodeEl.classList.add("failed");
      if (badgeEl) {
        badgeEl.classList.add("active", "failed");
        badgeEl.textContent = "!";
      }
      if (connector && connector.classList.contains("timeline-connector")) {
        connector.classList.remove("completed");
      }
    } else if (phaseState && phaseState.status === "cancelled") {
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
    } else if (phaseState && phaseState.status === "completed") {
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
    const emptyState = document.createElement("span");
    emptyState.className = "empty-state";
    emptyState.textContent = "No files built in workspace yet.";
    workspaceTree.replaceChildren(emptyState);
    return;
  }

  const fileItems = [];
  files.forEach(file => {
    const fileItem = document.createElement("button");
    fileItem.type = "button";
    fileItem.className = activeFile === file.name ? "file-item active" : "file-item";
    fileItem.addEventListener("click", () => inspectFile(file.name));

    const fileName = document.createElement("span");
    fileName.className = "file-name";
    fileName.textContent = `📄 ${file.name}`;

    const fileSize = document.createElement("span");
    fileSize.className = "file-size";
    fileSize.textContent = `${file.size} B`;

    fileItem.append(fileName, fileSize);
    fileItems.push(fileItem);
  });
  workspaceTree.replaceChildren(...fileItems);
}

async function inspectFile(filename) {
  activeFile = filename;
  previewFileTitle.textContent = `File Inspector: ${filename}`;
  previewFileContent.textContent = "Loading file content...";
  
  // Re-render files to highlight active class selection
  fetchWorkspaceFiles();

  try {
    const res = await fetch(`${API_BASE}/api/workspace/file?path=${encodeURIComponent(filename)}&_=${Date.now()}`);
    const data = await res.json();
    if (data && data.content) {
      previewFileContent.textContent = data.content;
      
      // If it's a HTML file, load it inside the live preview iframe!
      if (filename.toLowerCase().endsWith(".html")) {
        const iframe = document.getElementById("live-preview-iframe");
        const previewUrl = document.getElementById("live-preview-url");
        if (iframe && previewUrl) {
          const url = workspaceFileUrl(filename);
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

// Helper to update utility buttons text and inline SVG icons dynamically
function updateButtonState(btnEl, text, iconType) {
  if (!btnEl) return;
  
  let svgMarkup = "";
  if (iconType === "key") {
    svgMarkup = `<svg class="btn-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px; flex-shrink: 0; margin-right: 8px;"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>`;
  } else if (iconType === "sync") {
    svgMarkup = `<svg class="btn-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px; flex-shrink: 0; margin-right: 8px;"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>`;
  } else if (iconType === "save") {
    svgMarkup = `<svg class="btn-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px; flex-shrink: 0; margin-right: 8px;"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>`;
  } else if (iconType === "trash") {
    svgMarkup = `<svg class="btn-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px; flex-shrink: 0; margin-right: 8px;"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>`;
  }
  
  const cleanText = text.replace(/[🔑⚡💾🧹]/g, "").trim();
  btnEl.innerHTML = `${svgMarkup}<span>${cleanText}</span>`;
}

// Helper to update sprint button text and inline SVG icons dynamically
function updateSprintButtonState(text) {
  const sprintActionBtn = document.getElementById("sprint-action-btn");
  if (!sprintActionBtn) return;

  let iconType = "bolt";
  if (text.includes("Stop") || text.includes("Stopping")) {
    iconType = "stop";
  }
  
  let svgMarkup = "";
  if (iconType === "bolt") {
    const isPulsing = text.includes("Orchestrating");
    const pulsingStyle = isPulsing ? ' style="animation: pulse 1.5s infinite;"' : '';
    svgMarkup = `<svg class="btn-icon-svg"${pulsingStyle} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; flex-shrink: 0; margin-right: 8px;"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>`;
  } else if (iconType === "stop") {
    const isPulsing = text.includes("Stopping");
    const pulsingStyle = isPulsing ? ' style="animation: pulse 1.5s infinite;"' : '';
    svgMarkup = `<svg class="btn-icon-svg"${pulsingStyle} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 16px; height: 16px; flex-shrink: 0; margin-right: 8px;"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"/></svg>`;
  }
  
  const cleanText = text.replace(/[⚡🛑]/g, "").trim();
  sprintActionBtn.innerHTML = `${svgMarkup}<span>${cleanText}</span>`;
}

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

  const paddingLeft = 35;
  const paddingRight = 15;
  const paddingTop = 15;
  const paddingBottom = 20;
  const chartWidth = 300;
  const chartHeight = 120;
  const drawWidth = chartWidth - paddingLeft - paddingRight; // 250
  const drawHeight = chartHeight - paddingTop - paddingBottom; // 85

  const pointsCount = history.length;
  const maxVal = Math.max(...history.map(d => d.duration), 10); // Minimum scale floor of 10s

  // Set dynamic Y labels
  const labelTop = document.getElementById("chart-y-top");
  const labelMid = document.getElementById("chart-y-mid");
  if (labelTop && labelMid) {
    labelTop.textContent = `${Math.round(maxVal)}s`;
    labelMid.textContent = `${Math.round(maxVal / 2)}s`;
  }

  const points = history.map((item, idx) => {
    const x = paddingLeft + (idx / Math.max(pointsCount - 1, 1)) * drawWidth;
    const y = paddingTop + drawHeight - (item.duration / maxVal) * drawHeight;
    return { x, y };
  });

  // Build sparkline SVG Path string
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length; i++) {
    d += ` L ${points[i].x} ${points[i].y}`;
  }
  pathEl.setAttribute("d", d);

  // Build enclosed SVG Area Path string
  let dArea = `${d} L ${points[points.length - 1].x} ${chartHeight - paddingBottom} L ${points[0].x} ${chartHeight - paddingBottom} Z`;
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
  updateSprintButtonState("Stopping... 🛑");
  
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
      updateSprintButtonState("Stop Sprint 🛑");
    }
  } catch (e) {
    alert(`Failed to contact FastAPI server: ${e}`);
    sprintActionBtn.disabled = false;
    updateSprintButtonState("Stop Sprint 🛑");
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

// --------------------------------------------------------------------
// 8. Human-in-the-Loop & Webhooks Dynamic Controllers
// --------------------------------------------------------------------
async function checkHITLApproval() {
  try {
    const res = await fetch(`${API_BASE}/api/sprint/approval?_=${Date.now()}`);
    const data = await res.json();
    const modal = document.getElementById("hitl-modal");
    const cmdText = document.getElementById("hitl-command-text");
    const agentText = document.getElementById("hitl-agent-name");
    
    if (data && data.approval_status === "waiting_for_approval") {
      cmdText.textContent = data.requested_command || "No command requested";
      if (agentText) {
        agentText.textContent = data.requesting_agent || "Release Engineer";
      }
      if (!modal.classList.contains("show")) {
        modal.classList.add("show");
      }
    } else {
      modal.classList.remove("show");
    }
  } catch (e) {
    console.error("Error checking HITL approval:", e);
  }
}

async function handleHITLApprove() {
  const btn = document.getElementById("hitl-approve-btn");
  btn.disabled = true;
  btn.textContent = "Approving... ⏳";
  try {
    const res = await fetch(`${API_BASE}/api/sprint/approve?_=${Date.now()}`, {
      method: "POST"
    });
    const data = await res.json();
    if (data.status === "success") {
      document.getElementById("hitl-modal").classList.remove("show");
    } else {
      alert(`Approval failed: ${data.message}`);
    }
  } catch (e) {
    alert(`Network error approving command: ${e}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Approve Execution ⚡";
  }
}

async function handleHITLReject() {
  const btn = document.getElementById("hitl-reject-btn");
  btn.disabled = true;
  btn.textContent = "Rejecting... ⏳";
  try {
    const res = await fetch(`${API_BASE}/api/sprint/reject?_=${Date.now()}`, {
      method: "POST"
    });
    const data = await res.json();
    if (data.status === "success") {
      document.getElementById("hitl-modal").classList.remove("show");
    } else {
      alert(`Rejection failed: ${data.message}`);
    }
  } catch (e) {
    alert(`Network error rejecting command: ${e}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Reject & Abort 🛑";
  }
}

async function fetchWebhookConfig() {
  try {
    const res = await fetch(`${API_BASE}/api/config/webhook?_=${Date.now()}`);
    const data = await res.json();
    if (data) {
      document.getElementById("webhook-slack-url").value = data.slack_webhook || "";
    }
  } catch (e) {
    console.error("Failed to fetch webhook config:", e);
  }
}

async function saveWebhookConfig() {
  const slackUrl = document.getElementById("webhook-slack-url").value.trim();
  const btn = document.getElementById("webhook-save-btn");
  btn.disabled = true;
  updateButtonState(btn, "Saving... 💾", "save");
  
  try {
    const res = await fetch(`${API_BASE}/api/config/webhook?_=${Date.now()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slack_webhook: slackUrl })
    });
    const data = await res.json();
    if (data.status === "success") {
      alert("Notification webhook settings saved!");
    } else {
      alert(`Failed to save: ${data.message}`);
    }
  } catch (e) {
    alert(`Error saving webhook settings: ${e}`);
  } finally {
    btn.disabled = false;
    updateButtonState(btn, "Save Webhooks 💾", "save");
  }
}

async function handleResetDashboard() {
  if (!confirm("Are you sure you want to reset GStack to its original state? This will stop any active runs, delete all generated files, and clean all terminal logs.")) {
    return;
  }
  
  const btn = document.getElementById("sprint-clear-btn");
  if (btn) {
    btn.disabled = true;
    updateButtonState(btn, "Resetting... 🧹", "trash");
  }
  
  try {
    const res = await fetch(`${API_BASE}/api/sprint/reset?_=${Date.now()}`, {
      method: "POST"
    });
    const data = await res.json();
    
    if (res.ok && data && data.status === "success") {
      // 1. Reset client-side state variables
      composerTextarea.value = "";
      activeFile = null;
      lastObservedPhase = null;
      activeAgent = "ceo"; // Reset active terminal agent
      
      // 2. Fetch fresh status from backend to restore default states
      await fetchSprintStatus();
      await fetchWorkspaceFiles();
      
      // 3. Clear file inspector pre body
      previewFileContent.textContent = "Select a file from the workspace above to inspect its code contents in real time.";
      
      // 4. Force reset nodes in the DOM to default state (first node think is active, others idle)
      pipelineNodes.forEach((nodeEl, idx) => {
        nodeEl.className = "node-3d";
        if (idx === 0) {
          nodeEl.classList.add("active", "active-tab");
        }
        
        const badgeEl = document.getElementById(`badge-${nodeEl.id.replace("node-", "")}`);
        if (badgeEl) {
          badgeEl.className = "node-3d-badge";
          badgeEl.innerHTML = "";
        }
      });
      
      // 5. Restore original terminal logs text
      terminalOutput.textContent = "Waiting to launch GStack local agents... Ready.";
      terminalName.textContent = "TERMINAL: ceo_agent";
      
      // 6. Reset live preview iframe
      const iframe = document.getElementById("live-preview-iframe");
      const previewUrl = document.getElementById("live-preview-url");
      if (iframe && previewUrl) {
        iframe.src = "about:blank";
        previewUrl.textContent = "None";
      }
      
      alert("GStack workspace successfully reset back to original state!");
    } else {
      const errMsg = (data && (data.message || data.detail)) || `HTTP error ${res.status}`;
      alert(`Failed to reset dashboard: ${errMsg}`);
    }
  } catch (e) {
    alert(`Network error resetting dashboard: ${e}`);
  } finally {
    if (btn) {
      btn.disabled = false;
      updateButtonState(btn, "Reset Dashboard 🧹", "trash");
    }
  }
}

// Launch initialization
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeDashboard);
} else {
  initializeDashboard();
}

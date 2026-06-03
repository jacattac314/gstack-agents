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

let PHASE_ORDER = ["think", "plan", "design", "build", "review", "test", "ship"];
let PHASE_DETAILS = {
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
const qdrantUrlInput = document.getElementById("qdrant-url");
const providerSaveBtn = document.getElementById("provider-save-btn");
const presetSelect = document.getElementById("preset-select");
const presetLoadBtn = document.getElementById("preset-load-btn");
const presetNameInput = document.getElementById("preset-name-input");
const presetSaveBtn = document.getElementById("preset-save-btn");
const gridContainer = document.querySelector(".dashboard-grid");
const terminalOutput = document.getElementById("terminal-output");
const terminalName = document.getElementById("terminal-name");
const terminalPulse = document.getElementById("terminal-pulse");
const workspaceTree = document.getElementById("workspace-tree");
const previewFileTitle = document.getElementById("preview-file-title");
const previewFileContent = document.getElementById("preview-file-content");
const saveFileBtn = document.getElementById("save-file-btn");
const keepWorkspaceCheckbox = document.getElementById("keep-workspace-checkbox");

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
  fetchWorkflowConfig();
  fetchPresets();
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

  // Collapsible Agent Workflow Panel Toggle
  const workflowPanelHeader = document.getElementById("workflow-panel-header");
  const workflowPanelBody = document.getElementById("workflow-panel-body");
  const workflowToggleIcon = document.getElementById("workflow-toggle-icon");
  if (workflowPanelHeader && workflowPanelBody && workflowToggleIcon) {
    workflowPanelHeader.addEventListener("click", () => {
      const isHidden = workflowPanelBody.style.display === "none";
      workflowPanelBody.style.display = isHidden ? "flex" : "none";
      workflowToggleIcon.style.transform = isHidden ? "rotate(180deg)" : "rotate(0deg)";
    });
  }

  // Save custom agent button click listener
  const customAgentSaveBtn = document.getElementById("custom-agent-save-btn");
  if (customAgentSaveBtn) {
    customAgentSaveBtn.addEventListener("click", handleSaveCustomAgent);
  }

  // Add custom stage button click listener
  const customStageAddBtn = document.getElementById("custom-stage-add-btn");
  if (customStageAddBtn) {
    customStageAddBtn.addEventListener("click", handleAddCustomStage);
  }

  // Preset buttons click listeners
  if (presetLoadBtn) {
    presetLoadBtn.addEventListener("click", handleLoadPreset);
  }
  if (presetSaveBtn) {
    presetSaveBtn.addEventListener("click", handleSavePreset);
  }
  
  const aiTeamGenerateBtn = document.getElementById("ai-team-generate-btn");
  if (aiTeamGenerateBtn) {
    aiTeamGenerateBtn.addEventListener("click", handleGenerateAITeam);
  }

  setupAgentConfigModalListeners();



  // Sprint Toggle Action Button (Launch/Stop)
  sprintActionBtn.addEventListener("click", handleSprintAction);

  // Save Edited File Button click listener
  if (saveFileBtn) {
    saveFileBtn.addEventListener("click", async () => {
      if (!activeFile) return;
      saveFileBtn.disabled = true;
      const originalText = saveFileBtn.textContent;
      saveFileBtn.textContent = "Saving... 💾";
      
      try {
        const res = await fetch(`${API_BASE}/api/workspace/file`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            path: activeFile,
            content: previewFileContent.value
          })
        });
        const data = await res.json();
        if (data && data.status === "success") {
          saveFileBtn.textContent = "Saved! ✔";
          setTimeout(() => {
            saveFileBtn.textContent = "Save 💾";
            saveFileBtn.disabled = false;
          }, 1500);
          
          // If editing a HTML page, reload it immediately in live preview
          if (activeFile.toLowerCase().endsWith(".html")) {
            const iframe = document.getElementById("live-preview-iframe");
            const previewUrl = document.getElementById("live-preview-url");
            if (iframe && previewUrl) {
              const url = workspaceFileUrl(activeFile) + "?t=" + Date.now();
              iframe.src = url;
              previewUrl.textContent = url;
            }
          }
        } else {
          alert(`Error saving file: ${data.message || "Unknown error"}`);
          saveFileBtn.textContent = originalText;
          saveFileBtn.disabled = false;
        }
      } catch (e) {
        alert(`Error communicating with backend: ${e}`);
        saveFileBtn.textContent = originalText;
        saveFileBtn.disabled = false;
      }
    });
  }

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
      if (qdrantUrlInput) {
        qdrantUrlInput.value = data.qdrant_url || "http://localhost:6333";
      }
      
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
  const qdrantUrl = qdrantUrlInput ? qdrantUrlInput.value.trim() : "http://localhost:6333";
  
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
        freellmapi_model: model,
        qdrant_url: qdrantUrl
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

  const keepWorkspace = keepWorkspaceCheckbox ? keepWorkspaceCheckbox.checked : true;

  try {
    const res = await fetch(`${API_BASE}/api/sprint/start?_=${Date.now()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 
        goal: goalText,
        keep_workspace: keepWorkspace
      })
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
        
        updateLivePreviewDebateSummary(messages);
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
        
        updateLivePreviewDebateSummary([]);
      }
    } catch (e) {
      console.error("Error polling debate logs:", e);
    }
  }

function updateLivePreviewDebateSummary(messages) {
  const summaryEl = document.getElementById("live-preview-debate-summary");
  if (!summaryEl) return;
  
  if (!messages || messages.length === 0) {
    summaryEl.innerHTML = `
      <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: rgba(255,255,255,0.45); text-align: center; gap: 12px; padding: 20px;">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width: 48px; height: 48px; color: var(--color-cyan); opacity: 0.8; margin-bottom: 8px;"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <span style="font-weight: 600; font-size: 12px; color: #fff;">Awaiting Sprint...</span>
        <span style="font-size: 10px; max-width: 240px; color: rgba(255,255,255,0.5);">Start a sprint goal to watch the agents debate scope, tasks, and system architecture design.</span>
      </div>
    `;
    return;
  }
  
  // Categorize decisions by phase
  const decisions = {
    think: { title: "🧠 Scope & Core Goals", items: [] },
    plan: { title: "📋 Implementation Plan", items: [] },
    design: { title: "🎨 UI/UX Design System", items: [] },
    build: { title: "💻 Code & Implementation", items: [] },
    security_review: { title: "🛡️ Security & Compliance", items: [] },
    research: { title: "🔍 Research & Discovery", items: [] }
  };
  
  messages.forEach(msg => {
    const phase = (msg.phase || "").toLowerCase();
    const content = msg.content || "";
    
    // Extract key sentences
    const sentences = content.split(/[.!?]+/).map(s => s.trim()).filter(s => s.length > 12);
    
    sentences.forEach(sentence => {
      const lower = sentence.toLowerCase();
      if (
        lower.includes("decid") || 
        lower.includes("we will") || 
        lower.includes("should use") || 
        lower.includes("recommend") ||
        lower.includes("plan to") ||
        lower.includes("architect") ||
        lower.includes("goal") ||
        lower.includes("ux") ||
        lower.includes("color") ||
        lower.includes("layout") ||
        lower.includes("library") ||
        lower.includes("package") ||
        lower.includes("vulnerab") ||
        lower.includes("secure") ||
        lower.includes("endpoint")
      ) {
        let targetPhase = "think";
        if (phase === "plan" || lower.includes("step") || lower.includes("task") || lower.includes("plan")) targetPhase = "plan";
        else if (phase === "design" || lower.includes("css") || lower.includes("style") || lower.includes("color") || lower.includes("font") || lower.includes("theme")) targetPhase = "design";
        else if (phase === "build" || lower.includes("file") || lower.includes("code") || lower.includes("deliverable") || lower.includes("implement")) targetPhase = "build";
        else if (phase === "security_review" || phase === "cso" || lower.includes("security") || lower.includes("stride") || lower.includes("vulnerability") || lower.includes("audit")) targetPhase = "security_review";
        else if (phase === "research" || lower.includes("docs") || lower.includes("api") || lower.includes("research") || lower.includes("literature")) targetPhase = "research";
        else targetPhase = phase || "think";
        
        if (!decisions[targetPhase]) {
          decisions[targetPhase] = { title: `⚙️ ${targetPhase.toUpperCase()} Phase`, items: [] };
        }
        
        const formatted = sentence.charAt(0).toUpperCase() + sentence.slice(1);
        if (!decisions[targetPhase].items.includes(formatted) && decisions[targetPhase].items.length < 3) {
          decisions[targetPhase].items.push(formatted);
        }
      }
    });
  });
  
  let html = `
    <div style="padding: 4px;">
      <h3 style="margin-top: 0; margin-bottom: 12px; color: var(--color-cyan); font-size: 11px; font-weight: 700; letter-spacing: 0.5px; border-bottom: 1px solid rgba(6, 182, 212, 0.15); padding-bottom: 6px; display: flex; align-items: center; gap: 6px;">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="width: 12px; height: 12px; color: var(--color-cyan);"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <span>LIVE SPRINT DECISION LOG (DEBATED)</span>
      </h3>
      <div style="display: flex; flex-direction: column; gap: 8px;">
  `;
  
  let hasDecisions = false;
  Object.keys(decisions).forEach(key => {
    const group = decisions[key];
    if (group.items.length > 0) {
      hasDecisions = true;
      html += `
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.04); border-radius: 6px; padding: 8px 10px;">
          <span style="font-size: 8.5px; font-weight: 700; color: var(--color-cyan); text-transform: uppercase; letter-spacing: 0.5px; display: block; margin-bottom: 4px;">${group.title}</span>
          <ul style="margin: 0; padding-left: 12px; color: rgba(255,255,255,0.75); font-size: 10px; line-height: 1.4;">
            ${group.items.map(item => `<li style="margin-bottom: 3px;">${item}.</li>`).join("")}
          </ul>
        </div>
      `;
    }
  });
  
  if (!hasDecisions) {
    html += `
      <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 160px; color: rgba(255,255,255,0.4); text-align: center; gap: 8px;">
        <div class="hud-status-dot pulse-dot" style="background-color: var(--color-cyan); width: 8px; height: 8px;"></div>
        <span style="font-size: 10.5px;">Debate is active. Formulating technical decisions...</span>
      </div>
    `;
  }
  
  html += `
      </div>
    </div>
  `;
  
  summaryEl.innerHTML = html;
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
  const iframe = document.getElementById("live-preview-iframe");
  const previewUrl = document.getElementById("live-preview-url");
  const summaryEl = document.getElementById("live-preview-debate-summary");

  if (deliverable && deliverable.toLowerCase().endsWith(".html")) {
    if (iframe && previewUrl && iframe.src.indexOf(deliverable) === -1) {
      const url = workspaceFileUrl(deliverable);
      iframe.src = url;
      previewUrl.textContent = url;
      // Auto-switch to Live Preview tab to show the user the live progress!
      switchTab("preview");
    }
    if (iframe) iframe.style.display = "block";
    if (summaryEl) summaryEl.style.display = "none";
  } else {
    if (iframe) iframe.style.display = "none";
    if (summaryEl) summaryEl.style.display = "block";
    if (previewUrl) previewUrl.textContent = "Awaiting Coder deliverable...";
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
  if (previewFileTitle) {
    previewFileTitle.textContent = filename;
  }
  if (saveFileBtn) {
    saveFileBtn.style.display = "block";
  }
  if (previewFileContent) {
    previewFileContent.removeAttribute("readonly");
    previewFileContent.value = "Loading file content...";
  }
  
  // Re-render files to highlight active class selection
  fetchWorkspaceFiles();

  try {
    const res = await fetch(`${API_BASE}/api/workspace/file?path=${encodeURIComponent(filename)}&_=${Date.now()}`);
    const data = await res.json();
    if (data && data.content) {
      if (previewFileContent) {
        previewFileContent.value = data.content;
      }
      
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
      if (previewFileContent) {
        previewFileContent.value = "Error: Could not read file content.";
      }
    }
  } catch (e) {
    if (previewFileContent) {
      previewFileContent.value = `Error fetching file contents: ${e}`;
    }
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
      if (previewFileTitle) {
        previewFileTitle.textContent = "Select a file to inspect";
      }
      if (saveFileBtn) {
        saveFileBtn.style.display = "none";
      }
      if (previewFileContent) {
        previewFileContent.setAttribute("readonly", "true");
        previewFileContent.value = "Select a file from the workspace above to inspect its code contents in real time.";
      }
      
      // 4. Force reset nodes in the DOM to default state (first node is active, others idle)
      document.querySelectorAll("#pipeline-nodes-container .node-3d").forEach((nodeEl, idx) => {
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
      const summaryEl = document.getElementById("live-preview-debate-summary");
      if (iframe && previewUrl) {
        iframe.src = "about:blank";
        iframe.style.display = "none";
        previewUrl.textContent = "None";
      }
      if (summaryEl) {
        summaryEl.style.display = "block";
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

// Global workflow config state
let globalStages = [];
let globalCustomAgents = [];
let phaseToAgentMap = {};

function getPhaseIconSvg(phase) {
  switch (phase) {
    case "think":
      return `<svg class="node-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2" ry="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="15" x2="23" y2="15"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="15" x2="4" y2="15"/></svg>`;
    case "plan":
      return `<svg class="node-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/><line x1="9" y1="12" x2="15" y2="12"/><line x1="9" y1="16" x2="15" y2="16"/></svg>`;
    case "design":
      return `<svg class="node-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>`;
    case "build":
      return `<svg class="node-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/><line x1="14" y1="4" x2="10" y2="20"/></svg>`;
    case "review":
      return `<svg class="node-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`;
    case "test":
      return `<svg class="node-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3h12"/><path d="M8 3v12a4 4 0 0 0 8 0V3"/><path d="M6 12h12"/></svg>`;
    case "ship":
      return `<svg class="node-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.5-2.5 3.5-2.5 5.5C4 22 6 21 7.5 19.5"/><path d="M12 12l9-9-9 9z"/><path d="M21 3c-3 0-8 3-10 5l-4 4c-2 2-3 5-3 5s1 1 1 1 3-1 5-3l4-4c2-2 5-7 5-10z"/></svg>`;
    default:
      return `<svg class="node-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>`;
  }
}

function getAgentIconSvg(agentKey) {
  let phase = "default";
  if (agentKey === "ceo") phase = "think";
  else if (agentKey === "eng_manager") phase = "plan";
  else if (agentKey === "designer") phase = "design";
  else if (agentKey === "coder") phase = "build";
  else if (agentKey === "qa_lead") phase = "test";
  else if (agentKey === "release_engineer") phase = "ship";
  
  const svg = getPhaseIconSvg(phase);
  return svg.replace('class="node-icon-svg"', 'class="node-icon-svg" style="width: 12px; height: 12px; margin-right: 6px; flex-shrink: 0;"');
}

function renderDraggableAgentsPool() {
  const container = document.getElementById("draggable-agents-pool");
  if (!container) return;
  
  container.innerHTML = "";
  
  const baseAgents = [
    { key: "ceo", name: "CEO Agent" },
    { key: "eng_manager", name: "Eng Manager" },
    { key: "designer", name: "Designer" },
    { key: "coder", name: "Coder Agent" },
    { key: "qa_lead", name: "QA Lead" },
    { key: "release_engineer", name: "Release Eng" }
  ];
  
  const allAgents = [...baseAgents];
  globalCustomAgents.forEach(a => {
    if (!allAgents.some(x => x.key === a.key)) {
      allAgents.push({ key: a.key, name: a.name });
    }
  });
  
  allAgents.forEach(agent => {
    const chip = document.createElement("div");
    chip.className = "draggable-agent-chip";
    chip.draggable = true;
    chip.setAttribute("data-agent-key", agent.key);
    
    chip.style.cssText = "display: inline-flex; align-items: center; background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 6px; padding: 4px 8px; color: #fff; font-size: 10px; font-weight: 500; cursor: grab; user-select: none; transition: all 0.2s ease; box-shadow: 0 2px 5px rgba(0,0,0,0.15);";
    
    chip.innerHTML = getAgentIconSvg(agent.key) + `<span>${agent.name}</span>`;
    
    chip.addEventListener("dragstart", (e) => {
      chip.classList.add("dragging");
      document.body.classList.add("dragging-active");
      e.dataTransfer.setData("text/plain", agent.key);
      e.dataTransfer.effectAllowed = "copyMove";
    });
    
    chip.addEventListener("dragend", () => {
      chip.classList.remove("dragging");
      document.body.classList.remove("dragging-active");
    });

    chip.addEventListener("dblclick", () => {
      openAgentConfigModal(agent.key);
    });

    
    container.appendChild(chip);
  });
}

function assignAgentToPhase(phaseKey, agentKey) {
  const stage = globalStages.find(s => s.phase === phaseKey);
  if (!stage) return;
  
  const baseAgents = [
    { key: "ceo", name: "CEO Agent" },
    { key: "eng_manager", name: "Eng Manager" },
    { key: "designer", name: "Designer" },
    { key: "coder", name: "Coder Agent" },
    { key: "qa_lead", name: "QA Lead" },
    { key: "release_engineer", name: "Release Eng" }
  ];
  
  const allAgents = [...baseAgents];
  globalCustomAgents.forEach(a => {
    if (!allAgents.some(x => x.key === a.key)) {
      allAgents.push({ key: a.key, name: `${a.name} [Custom]` });
    }
  });
  
  const matchedAgent = allAgents.find(a => a.key === agentKey);
  stage.agent = agentKey;
  stage.sub = matchedAgent ? matchedAgent.name.replace(" [Custom]", "") : agentKey;
  
  saveWorkflowConfig();
  renderWorkflowStagesUI();
}

async function fetchWorkflowConfig() {
  try {
    const res = await fetch(`${API_BASE}/api/config/workflow?_=${Date.now()}`);
    const data = await res.json();
    if (data) {
      globalStages = data.stages || [];
      globalCustomAgents = data.custom_agents || [];
      
      // Update global phase order and details maps for active stages
      const activeStages = globalStages.filter(s => s.active);
      PHASE_ORDER = activeStages.map(s => s.phase);
      
      // Build details and mapping
      phaseToAgentMap = {};
      globalStages.forEach(s => {
        // Build map for active ones
        if (s.active) {
          phaseToAgentMap[s.phase] = s.agent;
        }
        
        // Build tooltip phase details
        PHASE_DETAILS[s.phase] = {
          label: s.label,
          agent: s.sub || s.agent,
          pending: `Will run the ${s.label} phase using the ${s.sub || s.agent} agent.`,
          running: `${s.sub || s.agent} is executing the ${s.label} phase...`,
          completed: `${s.sub || s.agent} completed the ${s.label} phase.`
        };
      });
      
      // 1. Render workflow stages checklist UI in Column 1
      renderWorkflowStagesUI();
      
      // 2. Render timeline nodes in Column 2
      renderTimelineNodesUI();
      
      // 3. Render draggable agent pool
      renderDraggableAgentsPool();
    }
  } catch (e) {
    console.error("Failed to fetch workflow config:", e);
  }
}

function renderWorkflowStagesUI() {
  const container = document.getElementById("workflow-stages-list");
  if (!container) return;
  
  container.innerHTML = "";
  
  // Available agents list
  const baseAgents = [
    { key: "ceo", name: "CEO Agent" },
    { key: "eng_manager", name: "Eng Manager" },
    { key: "designer", name: "Designer" },
    { key: "coder", name: "Coder Agent" },
    { key: "qa_lead", name: "QA Lead" },
    { key: "release_engineer", name: "Release Eng" }
  ];
  
  const allAgents = [...baseAgents];
  globalCustomAgents.forEach(a => {
    allAgents.push({ key: a.key, name: `${a.name} [Custom]` });
  });
  
  // Populate the new custom stage form's agent select list if it exists
  const customStageAgentSelect = document.getElementById("custom-stage-agent");
  if (customStageAgentSelect) {
    customStageAgentSelect.innerHTML = "";
    allAgents.forEach(agent => {
      const opt = document.createElement("option");
      opt.value = agent.key;
      opt.textContent = agent.name;
      customStageAgentSelect.appendChild(opt);
    });
  }
  
  globalStages.forEach((s, idx) => {
    const row = document.createElement("div");
    row.className = "flex-row justify-between align-center gap-xs workflow-stage-row";
    row.style.cssText = "display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 8px; border: 1px solid transparent; border-radius: 6px; padding: 4px; transition: all 0.2s ease;";
    row.setAttribute("data-phase", s.phase);
    
    // Drag and drop event listeners
    row.addEventListener("dragover", (e) => {
      e.preventDefault();
      row.style.borderColor = "var(--color-cyan)";
      row.style.boxShadow = "0 0 10px rgba(6, 182, 212, 0.4)";
      row.style.background = "rgba(6, 182, 212, 0.08)";
    });
    row.addEventListener("dragleave", () => {
      row.style.borderColor = "transparent";
      row.style.boxShadow = "none";
      row.style.background = "transparent";
    });
    row.addEventListener("drop", (e) => {
      e.preventDefault();
      row.style.borderColor = "transparent";
      row.style.boxShadow = "none";
      row.style.background = "transparent";
      const agentKey = e.dataTransfer.getData("text/plain");
      if (agentKey) {
        assignAgentToPhase(s.phase, agentKey);
      }
    });
    
    // Left: checkbox + label
    const leftDiv = document.createElement("div");
    leftDiv.style.cssText = "display: flex; align-items: center; gap: 6px;";
    
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = s.active;
    checkbox.style.cssText = "width: 12px; height: 12px; cursor: pointer; accent-color: var(--color-cyan);";
    checkbox.addEventListener("change", () => {
      s.active = checkbox.checked;
      saveWorkflowConfig();
    });
    
    const labelSpan = document.createElement("span");
    labelSpan.textContent = s.label;
    labelSpan.style.cssText = "font-size: 10px; font-weight: 500; color: rgba(255,255,255,0.85); font-family: var(--font-sans);";
    
    leftDiv.appendChild(checkbox);
    leftDiv.appendChild(labelSpan);
    
    // Right controls container (select + reorder buttons)
    const rightControls = document.createElement("div");
    rightControls.style.cssText = "display: flex; align-items: center; gap: 4px;";
    
    // Dropdown select
    const select = document.createElement("select");
    select.className = "premium-input";
    select.style.cssText = "font-size: 9px; height: 22px; padding: 2px 4px; width: 105px; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.08); color: #fff; border-radius: 4px; outline: none; cursor: pointer;";
    
    allAgents.forEach(agent => {
      const opt = document.createElement("option");
      opt.value = agent.key;
      opt.textContent = agent.name;
      if (agent.key === s.agent) {
        opt.selected = true;
      }
      select.appendChild(opt);
    });
    
    select.addEventListener("change", () => {
      s.agent = select.value;
      const matchedAgent = allAgents.find(a => a.key === select.value);
      s.sub = matchedAgent ? matchedAgent.name.split(" [")[0] : select.value;
      saveWorkflowConfig();
    });
    
    rightControls.appendChild(select);
    
    // Reordering actions
    const upBtn = document.createElement("button");
    upBtn.textContent = "▲";
    upBtn.className = "glow-button secondary";
    upBtn.style.cssText = "padding: 0; font-size: 7px; height: 16px; width: 16px; display: flex; align-items: center; justify-content: center; margin: 0;";
    if (idx === 0) {
      upBtn.style.opacity = "0.2";
      upBtn.style.pointerEvents = "none";
    } else {
      upBtn.addEventListener("click", () => {
        const temp = globalStages[idx];
        globalStages[idx] = globalStages[idx - 1];
        globalStages[idx - 1] = temp;
        saveWorkflowConfig();
        renderWorkflowStagesUI();
      });
    }
    
    const downBtn = document.createElement("button");
    downBtn.textContent = "▼";
    downBtn.className = "glow-button secondary";
    downBtn.style.cssText = "padding: 0; font-size: 7px; height: 16px; width: 16px; display: flex; align-items: center; justify-content: center; margin: 0;";
    if (idx === globalStages.length - 1) {
      downBtn.style.opacity = "0.2";
      downBtn.style.pointerEvents = "none";
    } else {
      downBtn.addEventListener("click", () => {
        const temp = globalStages[idx];
        globalStages[idx] = globalStages[idx + 1];
        globalStages[idx + 1] = temp;
        saveWorkflowConfig();
        renderWorkflowStagesUI();
      });
    }
    
    rightControls.appendChild(upBtn);
    rightControls.appendChild(downBtn);
    
    // Delete button for custom stages (only core ones are locked)
    const isCorePhase = ["think", "plan", "design", "build", "review", "test", "ship"].includes(s.phase);
    if (!isCorePhase) {
      const delBtn = document.createElement("button");
      delBtn.textContent = "✕";
      delBtn.className = "glow-button secondary";
      delBtn.style.cssText = "padding: 0; font-size: 8px; height: 16px; width: 16px; display: flex; align-items: center; justify-content: center; margin: 0; background: rgba(239, 68, 68, 0.15); border-color: rgba(239, 68, 68, 0.3); color: #ef4444;";
      delBtn.addEventListener("click", () => {
        globalStages.splice(idx, 1);
        saveWorkflowConfig();
        renderWorkflowStagesUI();
      });
      rightControls.appendChild(delBtn);
    }
    
    row.appendChild(leftDiv);
    row.appendChild(rightControls);
    container.appendChild(row);
  });
}

function renderTimelineNodesUI() {
  const container = document.getElementById("pipeline-nodes-container");
  if (!container) return;
  
  container.innerHTML = "";
  
  const activeStages = globalStages.filter(s => s.active);
  activeStages.forEach(s => {
    const node = document.createElement("div");
    node.className = "node-3d";
    node.setAttribute("data-agent", s.agent);
    node.setAttribute("data-phase", s.phase);
    node.id = `node-${s.phase}`;
    if (s.agent === activeAgent) {
      node.classList.add("active-tab");
    }
    
    // Drag and drop event listeners
    node.addEventListener("dragover", (e) => {
      e.preventDefault();
      node.classList.add("drag-over");
    });
    node.addEventListener("dragleave", () => {
      node.classList.remove("drag-over");
    });
    node.addEventListener("drop", (e) => {
      e.preventDefault();
      node.classList.remove("drag-over");
      const agentKey = e.dataTransfer.getData("text/plain");
      if (agentKey) {
        assignAgentToPhase(s.phase, agentKey);
      }
    });
    
    const circle = document.createElement("div");
    circle.className = "node-3d-circle";
    circle.innerHTML = getPhaseIconSvg(s.phase) + `<div class="node-3d-badge" id="badge-${s.phase}"></div>`;
    
    const copy = document.createElement("div");
    copy.className = "node-3d-copy";
    
    const label = document.createElement("div");
    label.className = "node-3d-label";
    label.textContent = s.label;
    
    const sub = document.createElement("div");
    sub.className = "node-3d-sub";
    sub.textContent = s.sub || s.agent;
    
    copy.appendChild(label);
    copy.appendChild(sub);
    node.appendChild(circle);
    node.appendChild(copy);
    
    // Clickable tab switching listener
    node.addEventListener("click", () => {
      activeAgent = s.agent;
      terminalName.textContent = `TERMINAL: ${activeAgent}_agent`;
      
      // Update visual active-tab class on all nodes
      document.querySelectorAll("#pipeline-nodes-container .node-3d").forEach(n => n.classList.remove("active-tab"));
      node.classList.add("active-tab");
      
      fetchAgentLog(); // Immediate fetch on switch
    });

    node.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      openAgentConfigModal(s.agent);
    });

    
    container.appendChild(node);
  });
}

async function saveWorkflowConfig() {
  try {
    await fetch(`${API_BASE}/api/config/workflow`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        stages: globalStages,
        custom_agents: globalCustomAgents
      })
    });
    
    const activeStages = globalStages.filter(s => s.active);
    PHASE_ORDER = activeStages.map(s => s.phase);
    
    phaseToAgentMap = {};
    globalStages.forEach(s => {
      if (s.active) {
        phaseToAgentMap[s.phase] = s.agent;
      }
      PHASE_DETAILS[s.phase] = {
        label: s.label,
        agent: s.sub || s.agent,
        pending: `Will run the ${s.label} phase using the ${s.sub || s.agent} agent.`,
        running: `${s.sub || s.agent} is executing the ${s.label} phase...`,
        completed: `${s.sub || s.agent} completed the ${s.label} phase.`
      };
    });
    
    renderTimelineNodesUI();
    renderWorkflowStagesUI();
    renderDraggableAgentsPool();
  } catch (e) {
    console.error("Failed to save workflow config:", e);
  }
}

async function handleSaveCustomAgent() {
  const keyInput = document.getElementById("custom-agent-key");
  const nameInput = document.getElementById("custom-agent-name");
  const subInput = document.getElementById("custom-agent-sub");
  const promptInput = document.getElementById("custom-agent-prompt");
  const btn = document.getElementById("custom-agent-save-btn");
  
  const key = keyInput.value.trim();
  const name = nameInput.value.trim();
  const sub = subInput.value.trim();
  const prompt = promptInput.value.trim();
  
  if (!key || !name || !sub || !prompt) {
    alert("Please fill in all custom agent fields.");
    return;
  }
  
  btn.disabled = true;
  const originalText = btn.innerHTML;
  btn.innerHTML = "<span>Creating... ⚙️</span>";
  
  try {
    const res = await fetch(`${API_BASE}/api/config/agent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, name, sub, prompt })
    });
    
    const data = await res.json();
    if (res.ok && data.status === "success") {
      alert(`Custom agent '${name}' created successfully! You can now select it for any workflow stage.`);
      keyInput.value = "";
      nameInput.value = "";
      subInput.value = "";
      promptInput.value = "";
      
      await fetchWorkflowConfig();
    } else {
      alert(`Failed to create custom agent: ${data.detail || data.message}`);
    }
  } catch (e) {
    alert(`Error creating custom agent: ${e}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalText;
  }
}

async function handleAddCustomStage() {
  const keyInput = document.getElementById("custom-stage-key");
  const labelInput = document.getElementById("custom-stage-label");
  const agentSelect = document.getElementById("custom-stage-agent");
  const btn = document.getElementById("custom-stage-add-btn");
  
  if (!keyInput || !labelInput || !agentSelect || !btn) return;
  
  const phase = keyInput.value.trim().toLowerCase().replace(/[^a-z0-9_]/g, "");
  const label = labelInput.value.trim();
  const agent = agentSelect.value;
  
  if (!phase || !label || !agent) {
    alert("Please fill in all custom stage fields.");
    return;
  }
  
  // Verify the stage key is unique
  if (globalStages.some(s => s.phase === phase)) {
    alert(`Stage with phase key '${phase}' already exists in your workflow.`);
    return;
  }
  
  btn.disabled = true;
  const originalText = btn.innerHTML;
  btn.innerHTML = "<span>Adding... ⚙️</span>";
  
  // Get description sub-label (e.g. Coder Agent)
  const matchedText = agentSelect.options[agentSelect.selectedIndex].text;
  const sub = matchedText.split(" [")[0];
  
  globalStages.push({
    phase,
    agent,
    label,
    sub,
    active: true
  });
  
  try {
    await saveWorkflowConfig();
    
    alert(`Custom stage '${label}' successfully added to your pipeline!`);
    
    // Clear inputs
    keyInput.value = "";
    labelInput.value = "";
    
    // Re-fetch config to refresh everything
    await fetchWorkflowConfig();
  } catch (e) {
    alert(`Error adding custom stage: ${e}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalText;
  }
}

async function fetchPresets() {
  try {
    const res = await fetch(`${API_BASE}/api/config/presets?_=${Date.now()}`);
    const data = await res.json();
    if (data && presetSelect) {
      presetSelect.innerHTML = "";
      Object.keys(data).forEach(name => {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        presetSelect.appendChild(opt);
      });
    }
  } catch (e) {
    console.error("Failed to fetch presets:", e);
  }
}

async function handleLoadPreset() {
  if (!presetSelect) return;
  const name = presetSelect.value;
  if (!name) return;
  
  if (!confirm(`Are you sure you want to load the team configuration preset '${name}'? This will overwrite your active workflow stages.`)) {
    return;
  }
  
  presetLoadBtn.disabled = true;
  const originalText = presetLoadBtn.innerHTML;
  presetLoadBtn.innerHTML = "<span>Loading... ⚙️</span>";
  
  try {
    const res = await fetch(`${API_BASE}/api/config/preset/load`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name })
    });
    const data = await res.json();
    if (res.ok && data.status === "success") {
      alert(`Team configuration preset '${name}' loaded successfully!`);
      await fetchWorkflowConfig();
    } else {
      alert(`Failed to load preset: ${data.detail || data.message}`);
    }
  } catch (e) {
    alert(`Error loading preset: ${e}`);
  } finally {
    presetLoadBtn.disabled = false;
    presetLoadBtn.innerHTML = originalText;
  }
}

async function handleSavePreset() {
  if (!presetNameInput || !presetSaveBtn) return;
  const name = presetNameInput.value.trim();
  if (!name) {
    alert("Please enter a name for the new team configuration preset.");
    return;
  }
  
  presetSaveBtn.disabled = true;
  const originalText = presetSaveBtn.innerHTML;
  presetSaveBtn.innerHTML = "<span>Saving... ⚙️</span>";
  
  try {
    const res = await fetch(`${API_BASE}/api/config/preset`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, stages: globalStages })
    });
    const data = await res.json();
    if (res.ok && data.status === "success") {
      alert(`Team configuration preset '${name}' saved successfully!`);
      presetNameInput.value = "";
      await fetchPresets();
      if (presetSelect) {
        presetSelect.value = name;
      }
    } else {
      alert(`Failed to save preset: ${data.detail || data.message}`);
    }
  } catch (e) {
    alert(`Error saving preset: ${e}`);
  } finally {
    presetSaveBtn.disabled = false;
    presetSaveBtn.innerHTML = originalText;
  }
}

async function handleGenerateAITeam() {
  const promptInput = document.getElementById("ai-team-prompt");
  const generateBtn = document.getElementById("ai-team-generate-btn");
  if (!promptInput || !generateBtn) return;

  const promptValue = promptInput.value.trim();
  if (!promptValue) {
    alert("Please describe the team or goal you want to generate.");
    return;
  }

  generateBtn.disabled = true;
  const originalText = generateBtn.innerHTML;
  generateBtn.innerHTML = "<span>Generating... ⚙️</span>";

  try {
    const res = await fetch(`${API_BASE}/api/config/generate_team`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: promptValue })
    });
    const data = await res.json();
    if (res.ok && data.status === "success") {
      alert("AI Team configuration generated successfully!");
      promptInput.value = "";
      await fetchWorkflowConfig();
    } else {
      alert(`Failed to generate team: ${data.detail || data.message}`);
    }
  } catch (e) {
    alert(`Error generating team: ${e}`);
  } finally {
    generateBtn.disabled = false;
    generateBtn.innerHTML = originalText;
  }
}

async function openAgentConfigModal(agentKey) {
  const modal = document.getElementById("agent-config-modal");
  const keyInput = document.getElementById("agent-config-key");
  const nameInput = document.getElementById("agent-config-name");
  const subInput = document.getElementById("agent-config-sub");
  const promptInput = document.getElementById("agent-config-prompt");
  const titleEl = document.getElementById("agent-config-title");
  
  if (!modal || !keyInput || !nameInput || !subInput || !promptInput) return;

  keyInput.value = agentKey;
  if (titleEl) {
    titleEl.textContent = `Configure Agent: ${agentKey}`;
  }

  nameInput.value = "Loading...";
  subInput.value = "Loading...";
  promptInput.value = "Loading agent configuration, please wait...";
  modal.classList.add("show");

  try {
    const res = await fetch(`${API_BASE}/api/config/agent/${agentKey}`);
    if (res.ok) {
      const data = await res.json();
      nameInput.value = data.name || "";
      subInput.value = data.sub || "";
      promptInput.value = data.prompt || "";
    } else {
      nameInput.value = agentKey;
      subInput.value = "";
      promptInput.value = "Failed to load configuration from server.";
    }
  } catch (e) {
    nameInput.value = agentKey;
    subInput.value = "";
    promptInput.value = `Error loading agent configuration: ${e}`;
  }
}

function setupAgentConfigModalListeners() {
  const modal = document.getElementById("agent-config-modal");
  const cancelBtn = document.getElementById("agent-config-cancel-btn");
  const saveBtn = document.getElementById("agent-config-save-btn");
  
  const keyInput = document.getElementById("agent-config-key");
  const nameInput = document.getElementById("agent-config-name");
  const subInput = document.getElementById("agent-config-sub");
  const promptInput = document.getElementById("agent-config-prompt");

  if (!modal || !cancelBtn || !saveBtn) return;

  cancelBtn.addEventListener("click", () => {
    modal.classList.remove("show");
  });

  modal.addEventListener("click", (e) => {
    if (e.target === modal) {
      modal.classList.remove("show");
    }
  });

  saveBtn.addEventListener("click", async () => {
    const key = keyInput.value;
    const name = nameInput.value.trim();
    const sub = subInput.value.trim();
    const prompt = promptInput.value.trim();

    if (!name || !sub || !prompt) {
      alert("Please fill in all fields (Display Name, Sub-label, and System Prompt).");
      return;
    }

    saveBtn.disabled = true;
    const originalText = saveBtn.innerHTML;
    saveBtn.innerHTML = "<span>Saving... ⚙️</span>";

    try {
      const res = await fetch(`${API_BASE}/api/config/agent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, name, sub, prompt })
      });
      const data = await res.json();
      if (res.ok && data.status === "success") {
        alert(`Agent '${name}' configuration saved successfully!`);
        modal.classList.remove("show");
        await fetchWorkflowConfig();
      } else {
        alert(`Failed to save agent configuration: ${data.detail || data.message}`);
      }
    } catch (e) {
      alert(`Error saving agent configuration: ${e}`);
    } finally {
      saveBtn.disabled = false;
      saveBtn.innerHTML = originalText;
    }
  });
}



// Launch initialization
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeDashboard);
} else {
  initializeDashboard();
}


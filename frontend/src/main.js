// Connection and state management
let ws = null;
let reconnectInterval = 3000;
let isExecuting = false;

// DOM Elements
const connectionBadge = document.getElementById('connection-badge');
const connectionStatusText = document.getElementById('connection-status-text');
const repoUrlInput = document.getElementById('repo-url-input');
const submitBtn = document.getElementById('submit-btn');
const stepperLineProgress = document.getElementById('stepper-line-progress');
const dockerfileEditor = document.getElementById('dockerfile-editor');
const containerPortInput = document.getElementById('container-port');
const rebuildBtn = document.getElementById('rebuild-btn');
const consoleContainer = document.getElementById('console');
const clearConsoleBtn = document.getElementById('clear-console-btn');

// Metadata DOM Elements
const metaLang = document.getElementById('meta-lang');
const metaFramework = document.getElementById('meta-framework');
const metaManager = document.getElementById('meta-manager');
const metaState = document.getElementById('meta-state');
const alertPopup = document.getElementById('alert-popup');
const alertMessage = document.getElementById('alert-message');

// Steps mappings
const stepIds = ['cloning', 'analyzing', 'generating', 'building', 'verifying'];
const stepProgressPercent = {
    'idle': 0,
    'cloning': 10,
    'analyzing': 35,
    'generating': 55,
    'building': 75,
    'verifying': 90,
    'debugging': 75,
    'success': 100,
    'failed': 100
};

// Initialize WebSocket Connection
function connectWebSocket() {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Match backend port (8000) when running locally
    const host = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' 
        ? 'localhost:8000' 
        : window.location.host;
        
    const wsUrl = `${wsProtocol}//${host}/ws/stream`;
    
    appendConsoleLine('system', `Connecting to WebSocket: ${wsUrl}...`);
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        connectionBadge.classList.remove('disconnected');
        connectionStatusText.textContent = 'ONLINE';
        appendConsoleLine('system', 'WebSocket connection established successfully. API is Online.');
    };
    
    ws.onclose = () => {
        connectionBadge.classList.add('disconnected');
        connectionStatusText.textContent = 'OFFLINE';
        appendConsoleLine('error', 'WebSocket disconnected. Retrying in 3 seconds...');
        ws = null;
        setTimeout(connectWebSocket, reconnectInterval);
    };
    
    ws.onerror = (err) => {
        loggerError('WebSocket error', err);
    };
    
    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleServerMessage(data);
        } catch (e) {
            loggerError('Failed to parse WebSocket message', e);
        }
    };
}

// Log Helper
function loggerError(context, err) {
    console.error(`[${context}]`, err);
}

// Format and append console line
function appendConsoleLine(source, message) {
    if (!message) return;
    
    const lineDiv = document.createElement('div');
    lineDiv.className = `console-line ${source}`;
    
    // Check if compilation error/success indicator keywords exist to highlight
    if (message.includes('Successfully built image') || message.includes('verification SUCCEEDED')) {
        lineDiv.className = 'console-line success';
    } else if (message.includes('BUILD ERROR') || message.includes('VERIFICATION ERROR') || message.includes('CLONING FAILED') || message.includes('failed after 3')) {
        lineDiv.className = 'console-line error';
    }
    
    lineDiv.textContent = message;
    consoleContainer.appendChild(lineDiv);
    
    // Keep scrolled to bottom
    consoleContainer.scrollTop = consoleContainer.scrollHeight;
}

// Popup Alerts
function showAlert(message, duration = 4000) {
    alertMessage.textContent = message;
    alertPopup.classList.add('show');
    setTimeout(() => {
        alertPopup.classList.remove('show');
    }, duration);
}

// Clear Terminal Console
clearConsoleBtn.addEventListener('click', () => {
    consoleContainer.innerHTML = '';
    appendConsoleLine('system', 'Terminal logs cleared.');
});

// Update Stepper Progress UI
function updateStepper(step) {
    // Reset all step styles if idle
    if (step === 'idle') {
        stepIds.forEach(id => {
            const el = document.getElementById(`step-${id}`);
            if (el) el.className = 'step-item';
        });
        stepperLineProgress.style.width = '0%';
        return;
    }
    
    // Set percentages
    const percent = stepProgressPercent[step] || 0;
    stepperLineProgress.style.width = `${percent}%`;
    
    // Determine active index
    const activeIndex = stepIds.indexOf(step);
    
    stepIds.forEach((id, index) => {
        const el = document.getElementById(`step-${id}`);
        if (!el) return;
        
        if (step === 'failed' && index === activeIndex) {
            el.className = 'step-item failed';
        } else if (index < activeIndex) {
            el.className = 'step-item completed';
        } else if (index === activeIndex) {
            el.className = 'step-item active';
        } else {
            el.className = 'step-item';
        }
    });
}

// Set state of controls during pipeline run
function setExecutionState(executing) {
    isExecuting = executing;
    repoUrlInput.disabled = executing;
    submitBtn.disabled = executing;
    
    if (executing) {
        rebuildBtn.disabled = true;
        submitBtn.innerHTML = `
            <span class="spinner"></span>
            <span>Building...</span>
        `;
    } else {
        submitBtn.innerHTML = `
            <span>Build Container</span>
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
        `;
    }
}

// Handle WebSocket messages
function handleServerMessage(data) {
    const { type } = data;
    
    if (type === 'log') {
        appendConsoleLine(data.source, data.message);
    } 
    else if (type === 'step') {
        const step = data.step;
        metaState.textContent = step.toUpperCase();
        
        if (step === 'success') {
            metaState.style.color = 'var(--color-green)';
            updateStepper('success');
            setExecutionState(false);
            rebuildBtn.disabled = false;
            showAlert('🎉 Containerization Pipeline Completed Successfully!');
        } else if (step === 'failed') {
            metaState.style.color = 'var(--color-red)';
            // Find active step to flag it red
            const activeStep = stepIds.find(id => {
                const el = document.getElementById(`step-${id}`);
                return el && el.classList.contains('active');
            });
            updateStepper(activeStep ? 'failed' : 'failed');
            setExecutionState(false);
            rebuildBtn.disabled = dockerfileEditor.value.trim() === '';
            showAlert('❌ Containerization Pipeline Failed. Check terminal error logs.');
        } else {
            metaState.style.color = 'var(--color-teal)';
            updateStepper(step);
        }
    } 
    else if (type === 'analysis') {
        const analysis = data.data;
        metaLang.textContent = (analysis.language || '-').toUpperCase();
        metaFramework.textContent = (analysis.framework || '-').toUpperCase();
        metaManager.textContent = (analysis.package_manager || '-').toUpperCase();
        containerPortInput.value = analysis.port || 8080;
    } 
    else if (type === 'generation') {
        dockerfileEditor.value = data.dockerfile;
        rebuildBtn.disabled = false;
        if (data.explanation) {
            appendConsoleLine('agent', `[AI Designer Decision Summary]: ${data.explanation}`);
        }
        if (data.root_cause) {
            appendConsoleLine('agent', `[AI Debugger diagnosis]: Detected Root Cause - ${data.root_cause}`);
        }
    } 
    else if (type === 'status') {
        appendConsoleLine('system', `Status Notification: ${data.message}`);
    }
}

// Submit Repository
submitBtn.addEventListener('click', () => {
    const repoUrl = repoUrlInput.value.trim();
    if (!repoUrl) {
        showAlert('Please enter a valid GitHub repository URL.');
        return;
    }
    
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        showAlert('WebSocket is not connected. Connecting to API...');
        connectWebSocket();
        return;
    }
    
    // Reset layout
    consoleContainer.innerHTML = '';
    dockerfileEditor.value = '';
    metaLang.textContent = '-';
    metaFramework.textContent = '-';
    metaManager.textContent = '-';
    rebuildBtn.disabled = true;
    updateStepper('idle');
    
    setExecutionState(true);
    
    ws.send(JSON.stringify({
        type: 'start',
        repo_url: repoUrl
    }));
});

// Re-Build Button Action
rebuildBtn.addEventListener('click', () => {
    const dockerfile = dockerfileEditor.value;
    const port = parseInt(containerPortInput.value) || 8080;
    
    if (!dockerfile.trim()) {
        showAlert('Dockerfile cannot be empty.');
        return;
    }
    
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        showAlert('WebSocket is offline. Reconnecting...');
        connectWebSocket();
        return;
    }
    
    setExecutionState(true);
    appendConsoleLine('system', 'Triggering manual Re-Build...');
    
    ws.send(JSON.stringify({
        type: 'rebuild',
        dockerfile: dockerfile,
        port: port,
        env_vars: {}
    }));
});

// Start WebSockets
connectWebSocket();

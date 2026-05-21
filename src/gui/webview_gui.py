"""
Webview-based GUI for game automation using pywebview.
Provides a modern web-based interface that communicates with Python backend via JS API.
"""
import json
import threading
import webview
from typing import Optional, Dict, Any
from pathlib import Path

from src.games.base_game import BaseGameAutomation, Activity
from src.utils import log_info, log_error


class WebviewAPI:
    """
    API class exposed to JavaScript frontend.
    All public methods are automatically exposed to JS via pywebview.js_api
    """
    
    def __init__(self, automation: BaseGameAutomation):
        self.automation = automation
        self.window: Optional[webview.Window] = None
        self._automation_thread: Optional[threading.Thread] = None
        
        # Setup callbacks to update UI
        self._setup_callbacks()
    
    def _setup_callbacks(self):
        """Setup callbacks to send events to frontend"""
        self.automation.register_callback('on_start', self._on_start)
        self.automation.register_callback('on_stop', self._on_stop)
        self.automation.register_callback('on_activity_start', self._on_activity_start)
        self.automation.register_callback('on_activity_complete', self._on_activity_complete)
        self.automation.register_callback('on_activity_failed', self._on_activity_failed)
        self.automation.register_callback('on_progress', self._on_progress)
        self.automation.register_callback('on_error', self._on_error)
        self.automation.register_callback('on_status_change', self._on_status_change)
    
    def _emit_event(self, event: str, data: Dict[str, Any]):
        """Emit event to JavaScript frontend"""
        if self.window:
            try:
                # ``json.dumps`` produces a valid JS literal for both args, so
                # event names with quotes/backslashes cannot break the call.
                js_code = (
                    "if(window.handleBackendEvent) "
                    f"window.handleBackendEvent({json.dumps(event)}, {json.dumps(data)})"
                )
                self.window.evaluate_js(js_code)
            except Exception as e:
                log_error(f"Error emitting event: {e}")
    
    # ===== Callback Handlers =====
    
    def _on_start(self):
        self._emit_event('automation_start', {})
    
    def _on_stop(self):
        self._emit_event('automation_stop', {})
    
    def _on_activity_start(self, activity: Activity):
        self._emit_event('activity_start', {
            'id': activity.id,
            'name': activity.name,
            'status': activity.status.value
        })
    
    def _on_activity_complete(self, activity: Activity, success: bool):
        self._emit_event('activity_complete', {
            'id': activity.id,
            'name': activity.name,
            'success': success,
            'status': activity.status.value
        })
    
    def _on_activity_failed(self, activity: Activity, error: Exception):
        self._emit_event('activity_failed', {
            'id': activity.id,
            'name': activity.name,
            'error': str(error)
        })
    
    def _on_progress(self, activity_id: str, progress: float):
        self._emit_event('progress', {
            'activity_id': activity_id,
            'progress': progress
        })
    
    def _on_error(self, error: Exception):
        self._emit_event('error', {'message': str(error)})
    
    def _on_status_change(self, status: dict):
        self._emit_event('status_change', status)
    
    # ===== Exposed API Methods (callable from JS via pywebview.api) =====
    
    def get_activities(self) -> str:
        """Get all activities as JSON"""
        activities = self.automation.get_activities()
        return json.dumps([{
            'id': act.id,
            'name': act.name,
            'description': act.description,
            'enabled': act.enabled,
            'status': act.status.value,
            'progress': act.progress
        } for act in activities])
    
    def set_activity_enabled(self, activity_id: str, enabled: bool) -> str:
        """Enable/disable an activity"""
        self.automation.set_activity_enabled(activity_id, enabled)
        return json.dumps({'success': True})
    
    def set_activity_order(self, order: str) -> str:
        """Set activity execution order (JSON array string)"""
        try:
            order_list = json.loads(order)
            self.automation.set_activity_order(order_list)
            return json.dumps({'success': True})
        except Exception as e:
            return json.dumps({'success': False, 'error': str(e)})
    
    def start_automation(self) -> str:
        """Start automation"""
        try:
            self.automation.reset_activities()
            self._automation_thread = threading.Thread(
                target=self.automation.start,
                daemon=True
            )
            self._automation_thread.start()
            return json.dumps({'success': True})
        except Exception as e:
            return json.dumps({'success': False, 'error': str(e)})
    
    def stop_automation(self) -> str:
        """Stop automation"""
        try:
            self.automation.stop()
            return json.dumps({'success': True})
        except Exception as e:
            return json.dumps({'success': False, 'error': str(e)})
    
    def pause_automation(self) -> str:
        """Pause automation"""
        try:
            self.automation.pause()
            return json.dumps({'success': True, 'paused': True})
        except Exception as e:
            return json.dumps({'success': False, 'error': str(e)})
    
    def resume_automation(self) -> str:
        """Resume automation"""
        try:
            self.automation.resume()
            return json.dumps({'success': True, 'paused': False})
        except Exception as e:
            return json.dumps({'success': False, 'error': str(e)})
    
    def get_status(self) -> str:
        """Get current automation status"""
        status = self.automation.get_status()
        return json.dumps(status)
    
    def get_performance_metrics(self) -> str:
        """Get performance metrics"""
        metrics = self.automation.get_performance_metrics()
        return json.dumps(metrics or {})
    
    def is_paused(self) -> str:
        """Check if automation is paused"""
        return json.dumps({'paused': self.automation.is_paused()})


class WebviewGUI:
    """
    Webview-based GUI for game automation.
    
    Usage:
        from src.games.bd2.bd2 import BD2
        
        game = BD2()
        gui = WebviewGUI(game, "BD2 Automation")
        gui.start()
    """
    
    def __init__(
        self,
        automation: BaseGameAutomation,
        title: str = "Game Automation",
        width: int = 1000,
        height: int = 700
    ):
        self.automation = automation
        self.title = title
        self.width = width
        self.height = height
        
        # Create API instance
        self.api = WebviewAPI(automation)
        
        # Get HTML file path
        self.html_path = self._get_html_path()
    
    def _get_html_path(self) -> str:
        """Get path to HTML file"""
        # Look for static/index.html
        current_dir = Path(__file__).parent
        html_file = current_dir / 'static' / 'index.html'
        
        if html_file.exists():
            return str(html_file.absolute())
        
        # Fallback: create HTML file
        return self._create_html_file()
    
    def _create_html_file(self) -> str:
        """Create HTML file if not exists"""
        static_dir = Path(__file__).parent / 'static'
        static_dir.mkdir(exist_ok=True)
        
        html_file = static_dir / 'index.html'
        
        html_content = self._get_default_html()
        html_file.write_text(html_content, encoding='utf-8')
        
        return str(html_file.absolute())
    
    def _get_default_html(self) -> str:
        """Get default HTML content"""
        return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Game Automation</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            min-height: 100vh;
            color: #333;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        
        header h1 {
            font-size: 2.5rem;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .control-panel {
            background: white;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        
        .control-buttons {
            display: flex;
            gap: 10px;
            justify-content: center;
            flex-wrap: wrap;
        }
        
        button {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        button:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }
        
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        .btn-start {
            background: #28a745;
            color: white;
        }
        
        .btn-pause {
            background: #ffc107;
            color: #333;
        }
        
        .btn-stop {
            background: #dc3545;
            color: white;
        }
        
        .status-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 15px;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        
        .status-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
            font-weight: 600;
        }
        
        .status-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #6c757d;
        }
        
        .status-dot.running {
            background: #28a745;
            animation: pulse 1.5s infinite;
        }
        
        .status-dot.paused {
            background: #ffc107;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .activities-section {
            background: white;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        
        .section-title {
            font-size: 1.5rem;
            margin-bottom: 20px;
            color: #2a5298;
            border-bottom: 2px solid #e9ecef;
            padding-bottom: 10px;
        }
        
        .activity-list {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        
        .activity-item {
            display: flex;
            align-items: center;
            gap: 15px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #6c757d;
            transition: all 0.3s ease;
        }
        
        .activity-item.running {
            border-left-color: #007bff;
            background: #e7f3ff;
        }
        
        .activity-item.completed {
            border-left-color: #28a745;
            background: #e8f5e9;
        }
        
        .activity-item.failed {
            border-left-color: #dc3545;
            background: #ffebee;
        }
        
        .activity-checkbox {
            width: 20px;
            height: 20px;
            cursor: pointer;
        }
        
        .activity-info {
            flex: 1;
        }
        
        .activity-name {
            font-weight: 600;
            font-size: 1.1rem;
            margin-bottom: 4px;
        }
        
        .activity-description {
            color: #6c757d;
            font-size: 0.9rem;
        }
        
        .activity-status {
            font-size: 0.85rem;
            font-weight: 600;
            padding: 4px 12px;
            border-radius: 20px;
            background: #e9ecef;
            color: #6c757d;
        }
        
        .activity-status.running {
            background: #007bff;
            color: white;
        }
        
        .activity-status.completed {
            background: #28a745;
            color: white;
        }
        
        .activity-status.failed {
            background: #dc3545;
            color: white;
        }
        
        .progress-bar {
            width: 150px;
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #28a745, #34ce57);
            border-radius: 4px;
            transition: width 0.3s ease;
        }
        
        .log-section {
            background: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        
        .log-container {
            background: #1e1e1e;
            color: #d4d4d4;
            border-radius: 8px;
            padding: 15px;
            height: 200px;
            overflow-y: auto;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 0.9rem;
        }
        
        .log-entry {
            margin-bottom: 5px;
            padding: 2px 0;
        }
        
        .log-entry.error {
            color: #f48771;
        }
        
        .log-entry.success {
            color: #7ee787;
        }
        
        .log-entry.info {
            color: #79c0ff;
        }
        
        .performance-metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .metric-card {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        
        .metric-value {
            font-size: 1.5rem;
            font-weight: 700;
            color: #2a5298;
        }
        
        .metric-label {
            font-size: 0.9rem;
            color: #6c757d;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎮 Game Automation</h1>
            <p>Control your game automation with ease</p>
        </header>
        
        <div class="control-panel">
            <div class="control-buttons">
                <button class="btn-start" id="btnStart" onclick="startAutomation()">
                    ▶ Start
                </button>
                <button class="btn-pause" id="btnPause" onclick="togglePause()" disabled>
                    ⏸ Pause
                </button>
                <button class="btn-stop" id="btnStop" onclick="stopAutomation()" disabled>
                    ⏹ Stop
                </button>
            </div>
            
            <div class="status-bar">
                <div class="status-indicator">
                    <div class="status-dot" id="statusDot"></div>
                    <span id="statusText">Ready</span>
                </div>
                <div id="currentActivity">No activity running</div>
            </div>
        </div>
        
        <div class="activities-section">
            <h2 class="section-title">📋 Activities</h2>
            <div class="activity-list" id="activityList">
                <!-- Activities will be loaded here -->
            </div>
        </div>
        
        <div class="log-section">
            <h2 class="section-title">📜 Log</h2>
            <div class="log-container" id="logContainer">
                <div class="log-entry info">[System] Ready to start automation...</div>
            </div>
            
            <div class="performance-metrics" id="performanceMetrics">
                <!-- Metrics will be loaded here -->
            </div>
        </div>
    </div>
    
    <script>
        // Global state
        let isRunning = false;
        let isPaused = false;
        let activities = [];
        
        // Initialize
        document.addEventListener('DOMContentLoaded', async () => {
            await loadActivities();
            updatePerformanceMetrics();
            setInterval(updatePerformanceMetrics, 2000);
        });
        
        // Load activities from backend
        async function loadActivities() {
            try {
                const result = await pywebview.api.get_activities();
                activities = JSON.parse(result);
                renderActivities();
            } catch (error) {
                log('Error loading activities: ' + error, 'error');
            }
        }
        
        // Render activities list
        function renderActivities() {
            const container = document.getElementById('activityList');
            container.innerHTML = activities.map(act => `
                <div class="activity-item ${act.status}" id="activity-${act.id}">
                    <input type="checkbox" 
                           class="activity-checkbox" 
                           ${act.enabled ? 'checked' : ''}
                           onchange="toggleActivity('${act.id}', this.checked)"
                           ${isRunning ? 'disabled' : ''}>
                    <div class="activity-info">
                        <div class="activity-name">${act.name}</div>
                        <div class="activity-description">${act.description}</div>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" id="progress-${act.id}" style="width: ${act.progress}%"></div>
                    </div>
                    <div class="activity-status ${act.status}" id="status-${act.id}">
                        ${act.status}
                    </div>
                </div>
            `).join('');
        }
        
        // Toggle activity enabled state
        async function toggleActivity(id, enabled) {
            try {
                await pywebview.api.set_activity_enabled(id, enabled);
                log(`${enabled ? 'Enabled' : 'Disabled'} activity: ${id}`, 'info');
            } catch (error) {
                log('Error toggling activity: ' + error, 'error');
            }
        }
        
        // Start automation
        async function startAutomation() {
            try {
                const result = await pywebview.api.start_automation();
                const data = JSON.parse(result);
                
                if (data.success) {
                    isRunning = true;
                    isPaused = false;
                    updateUIState();
                    log('Automation started', 'success');
                    
                    // Reset all progress
                    activities.forEach(act => {
                        act.progress = 0;
                        act.status = 'pending';
                    });
                    renderActivities();
                } else {
                    log('Failed to start: ' + data.error, 'error');
                }
            } catch (error) {
                log('Error starting automation: ' + error, 'error');
            }
        }
        
        // Stop automation
        async function stopAutomation() {
            try {
                await pywebview.api.stop_automation();
                isRunning = false;
                isPaused = false;
                updateUIState();
                log('Automation stopped', 'info');
            } catch (error) {
                log('Error stopping automation: ' + error, 'error');
            }
        }
        
        // Toggle pause/resume
        async function togglePause() {
            try {
                if (isPaused) {
                    await pywebview.api.resume_automation();
                    isPaused = false;
                    log('Automation resumed', 'info');
                } else {
                    await pywebview.api.pause_automation();
                    isPaused = true;
                    log('Automation paused', 'info');
                }
                updateUIState();
            } catch (error) {
                log('Error toggling pause: ' + error, 'error');
            }
        }
        
        // Update UI state based on running/paused
        function updateUIState() {
            const btnStart = document.getElementById('btnStart');
            const btnPause = document.getElementById('btnPause');
            const btnStop = document.getElementById('btnStop');
            const statusDot = document.getElementById('statusDot');
            const statusText = document.getElementById('statusText');
            
            btnStart.disabled = isRunning;
            btnPause.disabled = !isRunning;
            btnStop.disabled = !isRunning;
            
            btnPause.textContent = isPaused ? '▶ Resume' : '⏸ Pause';
            
            if (isRunning) {
                statusDot.className = 'status-dot ' + (isPaused ? 'paused' : 'running');
                statusText.textContent = isPaused ? 'Paused' : 'Running';
            } else {
                statusDot.className = 'status-dot';
                statusText.textContent = 'Ready';
            }
            
            // Disable checkboxes when running
            document.querySelectorAll('.activity-checkbox').forEach(cb => {
                cb.disabled = isRunning;
            });
        }
        
        // Add log entry
        function log(message, type = 'info') {
            const container = document.getElementById('logContainer');
            const entry = document.createElement('div');
            entry.className = `log-entry ${type}`;
            const time = new Date().toLocaleTimeString();
            entry.textContent = `[${time}] ${message}`;
            container.appendChild(entry);
            container.scrollTop = container.scrollHeight;
        }
        
        // Update performance metrics
        async function updatePerformanceMetrics() {
            try {
                const result = await pywebview.api.get_performance_metrics();
                const metrics = JSON.parse(result);
                
                const container = document.getElementById('performanceMetrics');
                container.innerHTML = `
                    <div class="metric-card">
                        <div class="metric-value">${(metrics.success_rate * 100).toFixed(1)}%</div>
                        <div class="metric-label">Success Rate</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">${metrics.template_matches || 0}</div>
                        <div class="metric-label">Matches</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">${metrics.template_failures || 0}</div>
                        <div class="metric-label">Failures</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-value">${(metrics.avg_match_time || 0).toFixed(3)}s</div>
                        <div class="metric-label">Avg Match Time</div>
                    </div>
                `;
            } catch (error) {
                // Silently ignore errors
            }
        }
        
        // Handle backend events
        window.handleBackendEvent = function(event, data) {
            switch(event) {
                case 'automation_start':
                    log('Automation started', 'success');
                    break;
                    
                case 'automation_stop':
                    isRunning = false;
                    isPaused = false;
                    updateUIState();
                    log('Automation stopped', 'info');
                    break;
                    
                case 'activity_start':
                    log(`Activity started: ${data.name}`, 'info');
                    updateActivityStatus(data.id, 'running');
                    document.getElementById('currentActivity').textContent = 
                        `Running: ${data.name}`;
                    break;
                    
                case 'activity_complete':
                    log(`Activity ${data.success ? 'completed' : 'failed'}: ${data.name}`, 
                        data.success ? 'success' : 'error');
                    updateActivityStatus(data.id, data.success ? 'completed' : 'failed');
                    break;
                    
                case 'activity_failed':
                    log(`Activity error: ${data.name} - ${data.error}`, 'error');
                    updateActivityStatus(data.id, 'failed');
                    break;
                    
                case 'progress':
                    updateActivityProgress(data.activity_id, data.progress);
                    break;
                    
                case 'error':
                    log('Error: ' + data.message, 'error');
                    break;
                    
                case 'status_change':
                    isPaused = data.paused;
                    updateUIState();
                    break;
            }
        };
        
        // Update activity status in UI
        function updateActivityStatus(id, status) {
            const item = document.getElementById(`activity-${id}`);
            const statusLabel = document.getElementById(`status-${id}`);
            
            if (item && statusLabel) {
                item.className = `activity-item ${status}`;
                statusLabel.className = `activity-status ${status}`;
                statusLabel.textContent = status;
            }
            
            // Update activity in data
            const act = activities.find(a => a.id === id);
            if (act) {
                act.status = status;
            }
        }
        
        // Update activity progress
        function updateActivityProgress(id, progress) {
            const progressBar = document.getElementById(`progress-${id}`);
            if (progressBar) {
                progressBar.style.width = progress + '%';
            }
            
            // Update activity in data
            const act = activities.find(a => a.id === id);
            if (act) {
                act.progress = progress;
            }
        }
    </script>
</body>
</html>'''
    
    def start(self):
        """Start the webview GUI"""
        log_info(f"Starting webview GUI: {self.title}")
        
        # Create window with API exposed to JS
        self.window = webview.create_window(
            title=self.title,
            url=self.html_path,
            js_api=self.api,  # This exposes all public methods to JS
            width=self.width,
            height=self.height,
            resizable=True,
            min_size=(800, 600)
        )
        
        # Set window reference in API
        self.api.window = self.window
        
        # Start webview
        webview.start(debug=False)


# ===== Quick Start Functions =====

def run_with_webview(game_class, title: str = "Game Automation"):
    """
    Quick function to run a game with webview GUI.
    
    Args:
        game_class: Class inheriting from BaseGameAutomation
        title: Window title
    
    Example:
        from src.games.bd2.bd2 import BD2
        run_with_webview(BD2, "BD2 Automation")
    """
    game = game_class()
    gui = WebviewGUI(game, title)
    gui.start()


def run_cli(game_class):
    """
    Quick function to run a game in CLI mode.
    
    Args:
        game_class: Class inheriting from BaseGameAutomation
    
    Example:
        from src.games.bd2.bd2 import BD2
        run_cli(BD2)
    """
    game = game_class()
    game.start()


if __name__ == "__main__":
    print("This is a webview GUI module. Import and use run_with_webview() or run_cli()")
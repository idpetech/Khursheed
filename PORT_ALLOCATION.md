# Enaam Port Allocation Strategy

To prevent port conflicts between services, here's the official port allocation for the Enaam system:

## 🎯 Production Services (Fixed Ports)

| Service | Port | Description | File |
|---------|------|-------------|------|
| **Enaam Command Center** | `8501` | Main Streamlit UI | `enaam_ui.py` |
| **Enaam Skill Management API** | `5001` | RESTful API for skill config | `enaam_skill_api.py` |
| **Enaam Admin UI** | `8502` | Admin interface for skill management | `enaam_admin.py` |
| **Enaam MCP Server** | `8080` | Model Context Protocol server | `enaam/mcp_server.py` |

## 🧪 Development/Testing Ports (Dynamic Range)

| Purpose | Port Range | Description |
|---------|------------|-------------|
| **Integration Tests** | `8090-8099` | Automated test suites |
| **Development Servers** | `8510-8519` | Local development instances |
| **Temporary Services** | `9000-9099` | One-off testing services |

## 🔧 Service Configuration Updates

### 1. Enaam Command Center (Main UI)
```python
# enaam_ui.py - Ensure it uses port 8501
if __name__ == "__main__":
    # Force specific port to avoid conflicts
    import sys
    sys.argv.extend(["--server.port", "8501"])
    main()
```

### 2. Skill Management API
```python
# enaam_skill_api.py - Already configured for port 5001
app.run(host='0.0.0.0', port=5001, debug=True)
```

### 3. Admin UI
```python
# enaam_admin.py - Should use port 8502
if __name__ == "__main__":
    import sys
    sys.argv.extend(["--server.port", "8502"])
    main()
```

### 4. MCP Server
```python
# enaam/mcp_server.py - Default port 8080
port = int(sys.argv[3]) if len(sys.argv) > 3 else 8080
```

## 🚀 Startup Commands

### Quick Start (Automated)
```bash
# Start all services with proper port allocation
./scripts/start_enaam_services.sh

# Check status
./scripts/status_enaam_services.sh

# Stop all services
./scripts/stop_enaam_services.sh
```

### Manual Start (For Development)
```bash
# Start services in this order to avoid conflicts:

# 1. MCP Server
cd /Users/haseebtoor/Projects/Khursheed
source .venv/bin/activate
python -m enaam.mcp_server

# 2. Skill Management API (in new terminal)
source .venv/bin/activate
python enaam_skill_api.py

# 3. Main Command Center (in new terminal)
source .venv/bin/activate
streamlit run enaam_ui.py --server.port 8501

# 4. Admin Interface (in new terminal)
source .venv/bin/activate
streamlit run enaam_admin.py --server.port 8502

# 5. Legacy App (if needed)
source .venv/bin/activate
streamlit run hey_eman_app.py --server.port 8510
```

## 🔍 Port Conflict Detection

Use this command to check for conflicts before starting services:

```bash
# Check if ports are available
netstat -an | grep LISTEN | grep -E ":(8501|8502|5001|8080)"

# If any results show up, those ports are in use
# Kill conflicting processes:
lsof -ti:8501 | xargs kill -9  # Kill anything using port 8501
lsof -ti:8502 | xargs kill -9  # Kill anything using port 8502
```

## 📱 Service Access URLs

Once running, access services at:

- **Main Enaam UI**: http://localhost:8501
- **Skill Admin**: http://localhost:8502  
- **API Documentation**: http://localhost:5001/api/health
- **MCP Server**: http://localhost:8080

## 🔄 Integration Points

Services communicate as follows:

```
┌─────────────────┐    HTTP/REST     ┌──────────────────┐
│ Admin UI (8502) │ ◄──────────────► │ Skill API (5001) │
└─────────────────┘                  └──────────────────┘
        │                                       │
        │ DB Access                             │ DB Access
        ▼                                       ▼
┌─────────────────┐                  ┌──────────────────┐
│   SQLite DB     │                  │   SQLite DB      │
│ khursheed.db    │                  │  khursheed.db    │
└─────────────────┘                  └──────────────────┘
        ▲                                       ▲
        │ Direct DB                             │ DB Access
        │                                       │
┌─────────────────┐   Command/Chat    ┌──────────────────┐
│ Main UI (8501)  │ ◄──────────────── │ MCP Server (8080)│
└─────────────────┘                  └──────────────────┘
```

This ensures clean separation and no port conflicts!
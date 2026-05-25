# Global Port Allocation Strategy for All Projects

This document defines a standardized port allocation system to prevent conflicts across all Haseebtoor projects.

## 🎯 Current Project Analysis

| Project | Current Port | Type | Status |
|---------|--------------|------|--------|
| **Khursheed (Enaam)** | 8501, 8502, 5001, 8080 | Streamlit + API + MCP | ✅ Fixed |
| **bus_ai_audit_v2** | 8501 (default) | Streamlit | ⚠️ Conflict |
| **ctodashboard** | 3001 (default) | Flask | ✅ Unique |
| **InsightVault** | 5001 | Flask | ⚠️ Conflict |

## 🏗️ Global Port Allocation Matrix

### **Production Service Ports (Fixed Assignment)**

| Port Range | Project | Service Type | Description |
|------------|---------|--------------|-------------|
| **8500-8509** | **Enaam System** | Mixed | Core Enaam services |
| **8510-8519** | **Business Assistant** | Streamlit | BA audit & analysis |
| **8520-8529** | **CTO Dashboard** | Flask | Management dashboard |
| **8530-8539** | **InsightVault** | Flask | Knowledge capture system |
| **8540-8549** | **Future Project 1** | TBD | Reserved |
| **8550-8559** | **Future Project 2** | TBD | Reserved |

### **Detailed Service Allocation**

#### Enaam System (8500-8509)
- **8501**: Main Enaam Command Center UI
- **8502**: Skill Administration Interface  
- **8503**: MCP Server (moved from 8080)
- **8504**: Legacy Hey Eman App
- **8505**: Skill Management API (moved from 5001)
- **8506-8509**: Reserved for Enaam expansion

#### Business Assistant (8510-8519)  
- **8510**: BA Main App (`bus_ai_audit_v2/app.py`)
- **8511**: BA Production App (`app_production.py`)
- **8512**: BA Testing Interface
- **8513-8519**: Reserved for BA modules

#### CTO Dashboard (8520-8529)
- **8520**: Main Dashboard (`ctodashboard/integrated_dashboard.py`)
- **8521**: MCP Server (`ctodashboard/mcp_server.py`)
- **8522**: Skippy Coach Interface
- **8523-8529**: Reserved for dashboard modules

#### InsightVault (8530-8539)
- **8530**: Main InsightVault App (`InsightVault/app.py`)
- **8531**: API Gateway
- **8532**: Admin Interface
- **8533-8539**: Reserved for vault expansion

## 🔧 Implementation Strategy

### 1. **Reusable Port Management Template**

Each project gets:
- `PORT_CONFIG.json` - Project-specific port definitions
- `scripts/port_manager.py` - Standardized port management
- `scripts/start_services.sh` - Automated service startup
- `scripts/stop_services.sh` - Graceful service shutdown
- `scripts/status_services.sh` - Service health monitoring

### 2. **Environment-Based Configuration**

```json
{
  "project_name": "bus_ai_audit_v2", 
  "port_range": [8510, 8519],
  "services": {
    "main_app": {
      "port": 8510,
      "type": "streamlit",
      "file": "app.py",
      "description": "BA Main Application"
    },
    "production_app": {
      "port": 8511,
      "type": "streamlit", 
      "file": "app_production.py",
      "description": "BA Production Interface"
    }
  },
  "development_ports": [8515, 8516, 8517],
  "testing_ports": [8518, 8519]
}
```

### 3. **Conflict Prevention**

- **Global Registry**: Central tracking of all assigned ports
- **Auto-Detection**: Scripts scan for conflicts before startup  
- **Dynamic Fallback**: Auto-assign alternate ports if conflicts detected
- **Validation**: Pre-commit hooks prevent port conflicts in commits

## 🚀 Deployment Process

### Phase 1: Deploy to Enaam (✅ Complete)
- Update existing services to use new ports
- Test multi-service coordination
- Validate conflict resolution

### Phase 2: Deploy to Business Assistant
```bash
cd /Users/haseebtoor/Projects/bus_ai_audit_v2
./deploy_port_allocation.sh
```

### Phase 3: Deploy to CTO Dashboard  
```bash
cd /Users/haseebtoor/Projects/ctodashboard
./deploy_port_allocation.sh
```

### Phase 4: Deploy to InsightVault
```bash
cd /Users/haseebtoor/Projects/InsightVault
./deploy_port_allocation.sh
```

## 🔍 Service Discovery

### Centralized Service Registry
```bash
# Global status check across all projects
./scripts/global_service_status.sh

# Output example:
🟢 Enaam Main UI        - http://localhost:8501
🟢 Enaam Admin         - http://localhost:8502  
🟢 Enaam MCP          - http://localhost:8503
🟢 BA Main App        - http://localhost:8510
🟢 BA Production      - http://localhost:8511
🟢 CTO Dashboard      - http://localhost:8520
🟢 InsightVault       - http://localhost:8530
```

## 📋 Migration Checklist

For each project:

- [ ] **Create PORT_CONFIG.json** with allocated ports
- [ ] **Update application files** to use assigned ports  
- [ ] **Install port management scripts**
- [ ] **Test service startup** with new ports
- [ ] **Update documentation** with new URLs
- [ ] **Validate no conflicts** with other running services
- [ ] **Test development workflow** with new port allocation

## 🎉 Benefits

1. **No More Conflicts** - Each project has dedicated port range
2. **Predictable URLs** - Standardized port patterns  
3. **Easy Management** - Unified scripts across projects
4. **Scalable** - Room for growth within each project
5. **Development Friendly** - Clear separation of concerns
6. **Documentation** - Self-documenting port allocation

This system ensures all your projects can run simultaneously without stepping on each other! 🚀
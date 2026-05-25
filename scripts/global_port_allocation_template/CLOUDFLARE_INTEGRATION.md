# Cloudflare Workers Integration Plan

This document outlines how to expose all your projects as separate URLs under `techvizpro.workers.dev` with proper port allocation.

## 🌐 Target URL Structure

| Service | Local Port | Public URL | Description |
|---------|------------|------------|-------------|
| **Enaam Main** | 8501 | `enaam.techvizpro.workers.dev` | Main Enaam Command Center |
| **Enaam Admin** | 8502 | `enaam-admin.techvizpro.workers.dev` | Skill Management Interface |
| **Enaam API** | 8505 | `enaam-api.techvizpro.workers.dev` | RESTful API endpoints |
| **Business Assistant** | 8510 | `ba.techvizpro.workers.dev` | AI Business Audit Tool |
| **BA Production** | 8511 | `ba-prod.techvizpro.workers.dev` | Production BA Interface |
| **CTO Dashboard** | 8520 | `cto.techvizpro.workers.dev` | Management Dashboard |
| **CTO MCP** | 8521 | `cto-api.techvizpro.workers.dev` | CTO API Gateway |
| **InsightVault** | 8530 | `vault.techvizpro.workers.dev` | Knowledge Capture System |

## 🔧 Implementation Options

### Option 1: Cloudflare Tunnels (Recommended)
**Pros**: Direct tunneling, no code needed, secure
**Cons**: Requires cloudflared daemon running

### Option 2: Cloudflare Workers Proxy
**Pros**: More control, custom routing, can add auth
**Cons**: Code maintenance, potential latency

### Option 3: Hybrid Approach
**Pros**: Best of both worlds
**Cons**: More complex setup

## 🚀 Implementation: Cloudflare Tunnels

### Step 1: Install Cloudflare Tunnel
```bash
# Install cloudflared
brew install cloudflare/cloudflare/cloudflared

# Authenticate
cloudflared tunnel login
```

### Step 2: Create Tunnel Configuration
```yaml
# ~/.cloudflared/config.yml
tunnel: techvizpro-services
credentials-file: /Users/haseebtoor/.cloudflared/techvizpro-services.json

ingress:
  # Enaam Services
  - hostname: enaam.techvizpro.workers.dev
    service: http://localhost:8501
  - hostname: enaam-admin.techvizpro.workers.dev  
    service: http://localhost:8502
  - hostname: enaam-api.techvizpro.workers.dev
    service: http://localhost:8505

  # Business Assistant  
  - hostname: ba.techvizpro.workers.dev
    service: http://localhost:8510
  - hostname: ba-prod.techvizpro.workers.dev
    service: http://localhost:8511

  # CTO Dashboard
  - hostname: cto.techvizpro.workers.dev
    service: http://localhost:8520
  - hostname: cto-api.techvizpro.workers.dev
    service: http://localhost:8521

  # InsightVault
  - hostname: vault.techvizpro.workers.dev
    service: http://localhost:8530

  # Catch-all rule (must be last)
  - service: http_status:404
```

### Step 3: Setup Automation Scripts

#### Tunnel Management Script
```bash
#!/bin/bash
# scripts/cloudflare_tunnel.sh

case "$1" in
  start)
    echo "🚀 Starting Cloudflare tunnel..."
    cloudflared tunnel --config ~/.cloudflared/config.yml run techvizpro-services &
    echo $! > tunnel.pid
    ;;
  stop)
    echo "🛑 Stopping Cloudflare tunnel..."
    kill $(cat tunnel.pid) 2>/dev/null || true
    rm -f tunnel.pid
    ;;
  status)
    if [[ -f tunnel.pid ]] && kill -0 $(cat tunnel.pid) 2>/dev/null; then
      echo "🟢 Tunnel running"
    else
      echo "🔴 Tunnel stopped"
    fi
    ;;
  *)
    echo "Usage: $0 {start|stop|status}"
    ;;
esac
```

## 🔐 Security Considerations

### Access Control Options
1. **Cloudflare Access** - Add authentication layer
2. **IP Allowlist** - Restrict to specific IPs
3. **Rate Limiting** - Prevent abuse
4. **API Keys** - For API endpoints

### Example Access Policy
```yaml
# Add to tunnel config for protected services
- hostname: enaam-admin.techvizpro.workers.dev
  service: http://localhost:8502
  originRequest:
    headers:
      X-Forwarded-For: 
        - CF-Connecting-IP
```

## 📋 Deployment Checklist

### Pre-requisites
- [ ] All projects deployed with port allocation system
- [ ] Services running on assigned ports (8501, 8502, 8510, etc.)
- [ ] Cloudflare account with Workers/Tunnels enabled
- [ ] Domain techvizpro.workers.dev configured

### Setup Steps
1. **Create Tunnel**
   ```bash
   cloudflared tunnel create techvizpro-services
   ```

2. **Configure DNS**
   ```bash
   # Add CNAME records for each subdomain
   cloudflared tunnel route dns techvizpro-services enaam.techvizpro.workers.dev
   cloudflared tunnel route dns techvizpro-services enaam-admin.techvizpro.workers.dev
   cloudflared tunnel route dns techvizpro-services ba.techvizpro.workers.dev
   cloudflared tunnel route dns techvizpro-services cto.techvizpro.workers.dev
   cloudflared tunnel route dns techvizpro-services vault.techvizpro.workers.dev
   ```

3. **Start Services**
   ```bash
   # Start all local services
   cd /Users/haseebtoor/Projects/Khursheed && ./scripts/start_services.sh
   cd /Users/haseebtoor/Projects/bus_ai_audit_v2 && ./scripts/start_services.sh
   cd /Users/haseebtoor/Projects/ctodashboard && ./scripts/start_services.sh
   cd /Users/haseebtoor/Projects/InsightVault && ./scripts/start_services.sh
   ```

4. **Start Tunnel**
   ```bash
   cloudflared tunnel --config ~/.cloudflared/config.yml run techvizpro-services
   ```

## 🎯 Advanced Features

### Health Monitoring
```javascript
// Cloudflare Worker for health checks
addEventListener('fetch', event => {
  if (event.request.url.includes('/health')) {
    event.respondWith(handleHealthCheck(event.request))
  }
})

async function handleHealthCheck(request) {
  const services = [
    { name: 'enaam', url: 'http://localhost:8501' },
    { name: 'ba', url: 'http://localhost:8510' },
    { name: 'cto', url: 'http://localhost:8520' },
    { name: 'vault', url: 'http://localhost:8530' }
  ]
  
  const results = await Promise.all(
    services.map(async service => {
      try {
        const response = await fetch(service.url, { timeout: 5000 })
        return { name: service.name, status: response.ok ? 'up' : 'down' }
      } catch {
        return { name: service.name, status: 'down' }
      }
    })
  )
  
  return new Response(JSON.stringify(results), {
    headers: { 'Content-Type': 'application/json' }
  })
}
```

### Load Balancing
For high availability, you can add multiple instances:
```yaml
- hostname: ba.techvizpro.workers.dev
  service: http://localhost:8510
  originRequest:
    connectTimeout: 10s
    tlsTimeout: 10s
```

## 🚀 Quick Start Commands

### 1. Complete Setup
```bash
# Deploy port allocation to all projects
cd /Users/haseebtoor/Projects/bus_ai_audit_v2 && echo "y" | /path/to/deploy_port_allocation.sh
cd /Users/haseebtoor/Projects/ctodashboard && echo "y" | /path/to/deploy_port_allocation.sh  
cd /Users/haseebtoor/Projects/InsightVault && echo "y" | /path/to/deploy_port_allocation.sh

# Start all services
./scripts/start_all_projects.sh

# Configure and start tunnel
cloudflared tunnel create techvizpro-services
# [Copy config.yml to ~/.cloudflared/]
cloudflared tunnel run techvizpro-services
```

### 2. Access Services
```bash
# Your services will be available at:
curl https://enaam.techvizpro.workers.dev
curl https://ba.techvizpro.workers.dev  
curl https://cto.techvizpro.workers.dev
curl https://vault.techvizpro.workers.dev
```

## 🎉 Benefits

✅ **Professional URLs** - Clean, branded access to all services
✅ **Global Access** - Available from anywhere on the internet
✅ **SSL/HTTPS** - Automatic SSL certificates  
✅ **DDoS Protection** - Cloudflare's built-in protection
✅ **Analytics** - Traffic insights and monitoring
✅ **Caching** - Improved performance for static assets
✅ **Zero Configuration** - Once set up, runs automatically

Your entire development ecosystem becomes a professional, internet-accessible platform! 🌍
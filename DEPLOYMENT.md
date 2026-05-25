# Enaam MCP Server Deployment Guide

Production-ready deployment infrastructure for the Enaam MCP server with health monitoring, graceful shutdown, and multi-environment support.

## Quick Start

### Development (Local)
```bash
# Start development server (foreground)
./scripts/deploy_enaam.sh start

# Start development server with custom port
./scripts/deploy_enaam.sh --port 9000 start
```

### Staging
```bash
# Start staging server (daemon)
./scripts/deploy_enaam.sh --env staging --daemon start

# Check staging server status
./scripts/deploy_enaam.sh --env staging status

# View staging server health
./scripts/deploy_enaam.sh --env staging health
```

### Production
```bash
# Start production server (daemon)
./scripts/deploy_enaam.sh --env production --daemon start

# Monitor production logs
./scripts/deploy_enaam.sh --env production logs

# Restart production server
./scripts/deploy_enaam.sh --env production restart
```

## Deployment Architecture

### Core Components

1. **ServerManager** - Main deployment orchestration
   - Graceful startup and shutdown
   - Signal handling (SIGTERM, SIGINT, SIGHUP)
   - PID file management
   - Process lifecycle management

2. **HealthMonitor** - System health and auto-recovery
   - Memory usage monitoring
   - CPU usage monitoring  
   - Disk space monitoring
   - Automatic restart on threshold breaches
   - Configurable health check intervals

3. **ServerConfiguration** - Environment-specific configuration
   - JSON-based configuration files
   - Environment variable overrides
   - Runtime configuration validation
   - Per-environment settings

### Configuration Management

Configuration is hierarchical with the following precedence:
1. Command line arguments (highest)
2. Environment variables 
3. Environment-specific config files (`config/{env}.json`)
4. Default values (lowest)

#### Environment Files

- **`config/development.json`** - Local development settings
  - Debug logging, relaxed rate limits, localhost binding

- **`config/staging.json`** - Staging environment settings  
  - Info logging, moderate rate limits, external binding

- **`config/production.json`** - Production settings
  - Warning-level logging, strict rate limits, optimized thresholds

### Health Monitoring

The health monitoring system continuously tracks:

- **Memory Usage**: Automatic restart if memory exceeds threshold
- **CPU Usage**: Alert and restart on sustained high CPU
- **Disk Space**: Warning when disk space is low
- **API Responsiveness**: Health endpoint availability
- **Process Health**: PID monitoring and zombie detection

#### Health Check Configuration

```json
{
  "health": {
    "check_interval": 30,        // Seconds between health checks
    "restart_threshold": 3,      // Failed checks before restart  
    "memory_threshold": "512MB", // Memory limit
    "cpu_threshold": 80.0        // CPU percentage limit
  }
}
```

## Command Reference

### Deployment Script (`./scripts/deploy_enaam.sh`)

```bash
# Basic commands
./scripts/deploy_enaam.sh start      # Start server (foreground)
./scripts/deploy_enaam.sh stop       # Stop server gracefully  
./scripts/deploy_enaam.sh restart    # Restart server
./scripts/deploy_enaam.sh status     # Show status
./scripts/deploy_enaam.sh health     # Show health metrics
./scripts/deploy_enaam.sh logs       # View logs (tail -f)
./scripts/deploy_enaam.sh config     # Show configuration

# Advanced options
./scripts/deploy_enaam.sh --env production start           # Production environment
./scripts/deploy_enaam.sh --daemon start                   # Background daemon
./scripts/deploy_enaam.sh --host 0.0.0.0 --port 9000 start # Custom host/port
./scripts/deploy_enaam.sh --config custom.json start       # Custom config file
```

### Direct Python Interface

```bash
# Using the deployment manager directly
python -m enaam.deployment.server_manager start --env production --daemon
python -m enaam.deployment.server_manager stop
python -m enaam.deployment.server_manager config --env staging
```

## Environment Variables

### Server Configuration
- `ENAAM_HOST` - Server host (default: localhost)
- `ENAAM_PORT` - Server port (default: 8080)
- `ENAAM_WORKERS` - Worker processes (default: 1)
- `ENAAM_ENV` - Environment name (development|staging|production)

### Logging Configuration  
- `ENAAM_LOG_LEVEL` - Logging level (DEBUG|INFO|WARNING|ERROR)
- `ENAAM_LOG_FILE` - Log file path (empty = stderr)
- `ENAAM_LOG_MAX_SIZE` - Max log file size (default: 10MB)

### Security Configuration
- `ENAAM_RATE_LIMIT` - Requests per minute (default: 60)
- `ENAAM_MAX_REQUEST_SIZE` - Max request size (default: 1MB)
- `ENAAM_CORS_ORIGINS` - Allowed CORS origins (comma-separated)

### Health Monitoring
- `ENAAM_MEMORY_THRESHOLD` - Memory restart threshold (default: 512MB)
- `ENAAM_CPU_THRESHOLD` - CPU restart threshold (default: 80.0)
- `ENAAM_HEALTH_INTERVAL` - Health check interval (default: 30s)

## Production Deployment

### Prerequisites

1. **System Requirements**
   - Python 3.8+
   - Virtual environment activated
   - Required Python packages installed
   - Sufficient disk space for logs and database

2. **Network Requirements**
   - Open port for server (default: 8080)
   - Network access to required APIs (OpenAI, Tavily)
   - DNS resolution if using domain names

### Production Setup

```bash
# 1. Clone and setup
git clone <repository>
cd enaam-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Create production configuration
cp config/production.json config/production-custom.json
# Edit production-custom.json with your settings

# 3. Set environment variables
export ENAAM_ENV=production
export ENAAM_HOST=0.0.0.0  
export ENAAM_PORT=8080
export ENAAM_LOG_FILE=/var/log/enaam/server.log

# 4. Start production server
./scripts/deploy_enaam.sh --env production --daemon start

# 5. Verify deployment
./scripts/deploy_enaam.sh --env production status
./scripts/deploy_enaam.sh --env production health
```

### Process Management

#### Using systemd (Recommended)

Create `/etc/systemd/system/enaam-mcp.service`:

```ini
[Unit]
Description=Enaam MCP Server
After=network.target

[Service]
Type=forking
User=enaam
Group=enaam
WorkingDirectory=/opt/enaam
Environment=ENAAM_ENV=production
ExecStart=/opt/enaam/scripts/deploy_enaam.sh --env production --daemon start
ExecStop=/opt/enaam/scripts/deploy_enaam.sh --env production stop
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start service
sudo systemctl enable enaam-mcp
sudo systemctl start enaam-mcp

# Check status
sudo systemctl status enaam-mcp
```

#### Manual Process Management

```bash
# Start as daemon
./scripts/deploy_enaam.sh --env production --daemon start

# Check if running
./scripts/deploy_enaam.sh --env production status

# Stop gracefully
./scripts/deploy_enaam.sh --env production stop

# Emergency stop (if graceful fails)
kill -KILL $(cat run/enaam_mcp.pid)
```

### Monitoring and Maintenance

#### Log Management

```bash
# View live logs
./scripts/deploy_enaam.sh --env production logs

# Log rotation (automatic based on configuration)
# Logs rotate when max_size is reached
# backup_count old logs are kept

# Manual log rotation
mv logs/enaam_production.log logs/enaam_production.log.$(date +%Y%m%d)
./scripts/deploy_enaam.sh --env production restart
```

#### Health Monitoring

```bash
# Check health via script
./scripts/deploy_enaam.sh --env production health

# Check health via API
curl http://localhost:8080/health

# Monitor system metrics
top -p $(cat run/enaam_mcp.pid)
```

#### Database Maintenance

```bash
# Database files are automatically managed
ls -la data/enaam_runs_production.db*

# Backup database (automatic based on backup_interval)
# Manual backup:
cp data/enaam_runs_production.db backups/enaam_$(date +%Y%m%d_%H%M%S).db
```

## Troubleshooting

### Common Issues

#### Server Won't Start
```bash
# Check configuration
./scripts/deploy_enaam.sh config

# Check port availability
netstat -ln | grep :8080

# Check logs
tail -f logs/enaam_production.log

# Check permissions
ls -la run/ logs/ data/
```

#### Server Stops Unexpectedly
```bash
# Check health status
./scripts/deploy_enaam.sh health

# Check system resources
df -h          # Disk space
free -h        # Memory usage
top            # CPU usage

# Check error logs
grep ERROR logs/enaam_production.log
```

#### High Memory/CPU Usage
```bash
# Check health thresholds
./scripts/deploy_enaam.sh config | grep -A5 health

# Adjust thresholds in config file
# Restart server
./scripts/deploy_enaam.sh restart
```

### Debug Mode

Enable debug logging for detailed troubleshooting:

```bash
# Temporary debug logging
export ENAAM_LOG_LEVEL=DEBUG
./scripts/deploy_enaam.sh restart

# Or modify config file
{
  "logging": {
    "level": "DEBUG"
  }
}
```

## Security Considerations

### Network Security
- Use reverse proxy (nginx/Apache) for SSL termination
- Configure firewall to restrict port access
- Use CORS origins restrictions in production

### Process Security
- Run as dedicated user (not root)
- Limit file system permissions
- Use systemd security features

### Configuration Security
- Store sensitive config in environment variables
- Restrict config file permissions (600)
- Use secrets management for API keys

## Performance Optimization

### Server Tuning
```json
{
  "server": {
    "workers": 4,           // CPU cores
    "max_connections": 200, // Concurrent connections
    "request_timeout": 30,  // Request timeout
    "keep_alive_timeout": 5 // Keep-alive timeout
  }
}
```

### Resource Monitoring
- Monitor memory usage trends
- Track CPU utilization patterns  
- Monitor request latency
- Watch disk I/O for database operations

## Backup and Recovery

### Automated Backups
- Database backups occur automatically per `backup_interval`
- Log rotation preserves historical logs
- Configuration files should be in version control

### Manual Backup
```bash
# Backup everything
tar czf enaam_backup_$(date +%Y%m%d).tar.gz \
  data/ logs/ config/ run/enaam_mcp.pid

# Backup just database
cp data/enaam_runs_production.db backups/
```

### Recovery Procedures
```bash
# Restore from backup
./scripts/deploy_enaam.sh stop
tar xzf enaam_backup_YYYYMMDD.tar.gz
./scripts/deploy_enaam.sh start

# Reset to clean state
./scripts/deploy_enaam.sh stop
rm -rf data/ logs/ run/
./scripts/deploy_enaam.sh start
```
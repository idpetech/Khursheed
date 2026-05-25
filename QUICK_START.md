# 🚀 Enaam Platform Quick Start Guide

Get up and running with the Enaam Chief-of-Staff AI platform in minutes!

## ⚡ Quick Setup

### 1. Start the Server
```bash
# Activate virtual environment
source .venv/bin/activate

# Start MCP server
python -c "
from enaam.mcp.server import MCPServer
server = MCPServer(host='0.0.0.0', port=8093)
print('🚀 Starting Enaam Server...')
result = server.start()
print(f'Result: {result}')
input('Press Enter to stop...')
"
```

### 2. Test via Web Interface
1. Open `web_chat_test.html` in your browser
2. Click the ⚙️ Config button and set URL to `localhost:8093`
3. Start chatting!

### 3. Test via Command Line
```bash
# Test health
curl http://localhost:8093/health

# Test capabilities
curl http://localhost:8093/capabilities

# Test chat
curl -X POST http://localhost:8093/ \
  -H 'Content-Type: application/json' \
  -d '{
    "method": "chat_query",
    "params": {
      "query": "Hello! What can you help me with?",
      "context": {"session_id": "test", "user_id": "demo"}
    },
    "response_type": "chat",
    "id": "test-1"
  }'
```

## 🗣️ Chat Commands to Try

### Basic Commands
- "Hello! What can you help me with?"
- "Check my email please"
- "Give me the weekly summary"
- "Show me the executive summary"

### Skill-Specific Commands
- "Calculate 2 + 3 * 4"
- "What's the current timestamp?"
- "Echo this message back to me"
- "Find business leads"

### Advanced Commands
- "I need a detailed status update"
- "Give me a brief summary"
- "Urgent! Check emails immediately!"

## 📊 System Status

### ✅ What's Working
- **Core MCP Server**: Healthy and responsive
- **Basic Chat**: Intent detection and routing
- **Bridge Functions**: Executive summary, weekly digest, email summary
- **Core Skills**: Echo, timestamp, sifter, lead_scout
- **SQLite Threading**: Completely fixed
- **Web Interface**: Full chat testing capability

### 🔧 Skills Available
1. **echo** - Echoes input data
2. **timestamp** - Generates ISO timestamps  
3. **sifter** - Email processing and analysis
4. **lead_scout** - Lead discovery and generation
5. **calculator** - Mathematical operations (⚠️ registration in progress)
6. **weather** - Weather information (⚠️ registration in progress)
7. **file_analyzer** - File/directory analysis (⚠️ registration in progress)

### 📝 Next Steps
1. Complete new skills registration (see SKILLS_DEVELOPMENT_GUIDE.md)
2. Add more API integrations (weather requires API key)
3. Enhance chat context persistence
4. Add production security features

## 🛠️ Development

### Adding New Skills
See `SKILLS_DEVELOPMENT_GUIDE.md` for complete instructions.

### Testing
```bash
# Run integration tests
source .venv/bin/activate
python -m pytest tests/integration/ -v

# Test specific skill
python -c "
from skills.echo import EchoSkill
skill = EchoSkill()
result = skill.run({'id': 'test', 'payload': {'message': 'hello'}})
print(result)
"
```

### Server Management
```bash
# Check what's running on port 8093
lsof -i:8093

# Kill server if needed
lsof -ti:8093 | xargs kill

# Start on different port
python -c "from enaam.mcp.server import MCPServer; MCPServer(port=8094).start()"
```

## 📚 Documentation

- `SKILLS_DEVELOPMENT_GUIDE.md` - How to add new skills
- `VALIDATION_REPORT.md` - Technical architecture analysis
- `web_chat_test.html` - Interactive chat testing interface
- `tests/integration/` - Test examples and validation

## 🎯 Ready to Use!

Your Enaam Chief-of-Staff AI is ready! The platform provides:

✅ **Chat Interface** - Natural language interaction  
✅ **Skills System** - Modular, extensible capabilities  
✅ **Bridge Functions** - Integration with existing workflows  
✅ **MCP Protocol** - Standard API interface  
✅ **Web Testing** - Easy testing and debugging  

Start chatting and exploring what Enaam can do for you! 🤖✨
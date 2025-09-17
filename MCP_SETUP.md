# MCP SQLite Setup for KBXY Monsters Pro

## Overview

This project now includes MCP (Model Context Protocol) SQLite server configuration for enhanced database interaction capabilities.

## Installed MCP Tool

**Package**: [mcp-sqlite](https://github.com/jparkerweb/mcp-sqlite) by jparkerweb/eQuill Labs
- Comprehensive SQLite database interaction
- Complete CRUD operations
- Custom SQL query execution
- Database schema exploration

## Configuration Files

### 1. `mcp-config.json`
Basic MCP server configuration for the project:
```json
{
  "mcpServers": {
    "sqlite": {
      "command": "npx",
      "args": ["-y", "mcp-sqlite", "./kbxy-dev.db"],
      "description": "SQLite MCP Server for KBXY Monsters Pro database"
    }
  }
}
```

### 2. Claude Desktop Integration

For Claude Desktop, add this to your `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "kbxy-sqlite": {
      "command": "npx",
      "args": ["-y", "mcp-sqlite", "/full/path/to/kbxy-monsters-pro/kbxy-dev.db"],
      "description": "KBXY Monsters Pro SQLite Database"
    }
  }
}
```

## Database Schema

Current tables in `kbxy-dev.db`:
- `collection_items`
- `collections`
- `import_jobs`
- `monster_derived`
- `monster_skills`
- `monster_tag`
- `monsters`
- `skills`
- `tags`
- `tasks`

## Available MCP Operations

The mcp-sqlite server provides these tools:
- **Database Info**: List tables, get schema information
- **Read Operations**: Query data with custom SQL
- **Write Operations**: Insert, update, delete records
- **Table Management**: Create/modify table structures

## Usage Examples

Once configured in your MCP client, you can:
- Ask Claude to analyze monster data patterns
- Generate reports from the database
- Perform complex queries across multiple tables
- Get insights about collections, skills, and tags

## Testing the Setup

To verify the MCP server works:
```bash
# Test database connectivity
sqlite3 ./kbxy-dev.db ".tables"

# Run MCP server manually (for debugging)
npx -y mcp-sqlite ./kbxy-dev.db
```

## Notes

- Database file: `kbxy-dev.db` (1.7MB, last modified Aug 23)
- Uses npx for package execution (no local installation required)
- Compatible with environment switching (dev/test databases)
- Follows project's existing SQLite + FastAPI architecture
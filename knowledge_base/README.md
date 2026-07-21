# Knowledge Base

This folder is a curated, trusted set of reference documents that the
**Researcher** agent can read over the **Model Context Protocol (MCP)**.

The Researcher connects to the official
[`@modelcontextprotocol/server-filesystem`](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem)
MCP server (launched via `npx`) and is granted **read-only** access to this
directory. It consults these documents *before* falling back to Google Search.

Add any `.md`/`.txt` reference material here to make it available to research.
The path can be overridden with the `KNOWLEDGE_BASE_DIR` environment variable.

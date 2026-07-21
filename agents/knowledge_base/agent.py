import os

from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters


MODEL = "gemini-3.5-flash-lite"

# --- Local Knowledge Base over MCP ---
# This agent's ONLY tools are the read-only filesystem MCP tools. Keeping the
# MCP tools isolated on their own agent (separate from the Researcher's
# google_search built-in tool) avoids ADK's limitation where mixing a built-in
# tool with MCP tools disables automatic function calling.
KNOWLEDGE_BASE_DIR = os.environ.get(
    "KNOWLEDGE_BASE_DIR",
    os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "knowledge_base")
    ),
)

knowledge_base_tools = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="npx",
            args=[
                "-y",
                "@modelcontextprotocol/server-filesystem",
                KNOWLEDGE_BASE_DIR,
            ],
        ),
        timeout=30,
    ),
    tool_filter=[
        "read_file",
        "read_text_file",
        "list_directory",
        "directory_tree",
        "search_files",
        "get_file_info",
    ],
)

knowledge_base = Agent(
    name="knowledge_base",
    model=MODEL,
    description="Looks up curated local reference material (course syllabi, internal standards) via MCP.",
    instruction="""
    You are a knowledge base librarian. You have read-only filesystem tools over
    a curated local knowledge base that may contain course syllabi and internal
    standards.

    For the user's topic:
    1. List the files in the knowledge base.
    2. Read the files that are relevant to the topic.
    3. Report exactly what relevant material exists. Quote any syllabus structure,
       scope limits (what is in scope / out of scope), and style guides closely
       enough that a later agent can apply them.

    If NO file is relevant to the topic, respond with exactly:
    "No relevant material found in the local knowledge base."

    Do NOT invent or supplement content from your own knowledge — report ONLY
    what is actually in the files.
    DO NOT output any function calls in your final answer. Provide your findings
    as plain text.
    """,
    tools=[knowledge_base_tools],
)

root_agent = knowledge_base

from google.adk.agents import Agent
from google.adk.tools.google_search_tool import google_search


MODEL = "gemini-3.5-flash-lite"

# Define the Researcher Agent
#
# The Researcher uses Google Search only. The local knowledge base is handled by
# the separate `knowledge_base` agent, which runs BEFORE this one in the
# pipeline. Keeping google_search (a built-in tool) isolated from the MCP tools
# avoids ADK's limitation where mixing them disables automatic function calling.
researcher = Agent(
    name="researcher",
    model=MODEL,
    description="Gathers information on a topic using Google Search.",
    instruction="""
    You are an expert researcher with Google Search.

    Earlier in this conversation, a knowledge base agent already checked the
    curated local knowledge base and posted its findings. Use them as follows:
    - If the local findings already cover the user's topic well, build on them
      and use Google Search only to fill specific gaps or add recent details.
    - If the local findings say no relevant material was found (or are clearly
      insufficient), research the topic from scratch using Google Search.

    IMPORTANT: Always honor any scope limits (in scope / out of scope) and style
    or structure guidance stated in the local findings — do not cover topics the
    local material marks as out of scope.

    Summarize your findings clearly, indicating which parts came from the local
    knowledge base versus the web.
    If you receive feedback that your research is insufficient, use the feedback to refine your next search.
    DO NOT output any function calls. Provide your research directly as text.
    """,
    tools=[google_search],
)

root_agent = researcher

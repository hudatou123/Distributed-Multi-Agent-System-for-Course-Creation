import os
import json
from typing import AsyncGenerator
from google.adk.agents import BaseAgent, LoopAgent, SequentialAgent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.events import Event, EventActions
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from authenticated_httpx import create_authenticated_client
import cache

# --- Callbacks ---
def create_save_output_callback(key: str):
    """Creates a callback to save the agent's final response to session state."""
    def callback(callback_context: CallbackContext, **kwargs) -> None:
        ctx = callback_context
        # Find the last event from this agent that has content
        for event in reversed(ctx.session.events):
            if event.author == ctx.agent_name and event.content and event.content.parts:
                text = event.content.parts[0].text
                if text:
                    # Try to parse as JSON if it looks like it, for judge_feedback
                    if key == "judge_feedback" and text.strip().startswith("{"):
                        try:
                            ctx.state[key] = json.loads(text)
                        except json.JSONDecodeError:
                            ctx.state[key] = text
                    else:
                        ctx.state[key] = text
                    print(f"[{ctx.agent_name}] Saved output to state['{key}']")
                    return
    return callback

# --- Redis Course Cache ---
# A repeated request for the same topic is served from Redis, skipping the
# whole Researcher -> Judge -> ContentBuilder pipeline. On a cache hit the
# root before-callback returns Content; ADK then sets end_invocation=True and
# skips the pipeline entirely. On a miss the pipeline runs normally and
# ContentBuilder's after-callback stores the finished course.

def _extract_topic(ctx: CallbackContext) -> str:
    """Best-effort extraction of the user's topic for this invocation."""
    user_content = getattr(ctx, "user_content", None)
    if user_content and getattr(user_content, "parts", None):
        for part in user_content.parts:
            if getattr(part, "text", None):
                return part.text
    # Fall back to the latest user-authored message in the session.
    for event in reversed(ctx.session.events):
        if event.author == "user" and event.content and event.content.parts:
            text = event.content.parts[0].text
            if text:
                return text
    return ""


def check_course_cache(callback_context: CallbackContext, **kwargs):
    """Root before-callback: serve a cached course if one exists for the topic."""
    ctx = callback_context
    topic = _extract_topic(ctx)
    # Remember the topic so the after-callback can key the cache write.
    ctx.state["topic"] = topic
    if not topic:
        return None
    cached = cache.get_cached(cache.make_course_key(topic))
    if cached:
        print(f"[course_creation_pipeline] ⚡ Cache HIT for topic={topic!r}; skipping pipeline")
        # Returning Content makes ADK skip the pipeline and end the invocation.
        return types.Content(role="model", parts=[types.Part(text=cached)])
    print(f"[course_creation_pipeline] Cache MISS for topic={topic!r}; running pipeline")
    return None


def save_course_to_cache(callback_context: CallbackContext, **kwargs) -> None:
    """ContentBuilder after-callback: persist the finished course to Redis."""
    ctx = callback_context
    topic = ctx.state.get("topic", "")
    if not topic:
        return
    for event in reversed(ctx.session.events):
        if event.author == ctx.agent_name and event.content and event.content.parts:
            text = event.content.parts[0].text
            if text:
                cache.set_cached(cache.make_course_key(topic), text)
                return

# --- Remote Agents ---

# TODO: Define connections to remote agents
# Connect to Researcher, Judge, and Content Builder using RemoteA2aAgent.
# Remember to use the environment variables for URLs (or localhost defaults).

# ... existing code ...

# Connect to the Knowledge Base agent (Localhost port 8005). It runs first and
# reports any relevant curated local material (syllabi, standards) via MCP.
knowledge_base_url = os.environ.get("KNOWLEDGE_BASE_AGENT_CARD_URL", "http://localhost:8005/a2a/agent/.well-known/agent-card.json")
knowledge_base = RemoteA2aAgent(
    name="knowledge_base",
    agent_card=knowledge_base_url,
    description="Looks up curated local reference material via MCP.",
    after_agent_callback=create_save_output_callback("kb_findings"),
    httpx_client=create_authenticated_client(knowledge_base_url)
)

# Connect to the Researcher (Localhost port 8001)
researcher_url = os.environ.get("RESEARCHER_AGENT_CARD_URL", "http://localhost:8001/a2a/agent/.well-known/agent-card.json")
researcher = RemoteA2aAgent(
    name="researcher",
    agent_card=researcher_url,
    description="Gathers information using Google Search.",
    # IMPORTANT: Save the output to state for the Judge to see
    after_agent_callback=create_save_output_callback("research_findings"),
    # IMPORTANT: Use authenticated client for communication
    httpx_client=create_authenticated_client(researcher_url)
)

# Connect to the Judge (Localhost port 8002)
judge_url = os.environ.get("JUDGE_AGENT_CARD_URL", "http://localhost:8002/a2a/agent/.well-known/agent-card.json")
judge = RemoteA2aAgent(
    name="judge",
    agent_card=judge_url,
    description="Evaluates research.",
    after_agent_callback=create_save_output_callback("judge_feedback"),
    httpx_client=create_authenticated_client(judge_url)
)

# Content Builder (Localhost port 8003)
content_builder_url = os.environ.get("CONTENT_BUILDER_AGENT_CARD_URL", "http://localhost:8003/a2a/agent/.well-known/agent-card.json")
content_builder = RemoteA2aAgent(
    name="content_builder",
    agent_card=content_builder_url,
    description="Builds the course.",
    # Persist the finished course to Redis, keyed by the topic saved in state.
    after_agent_callback=save_course_to_cache,
    httpx_client=create_authenticated_client(content_builder_url)
)

# --- Escalation Checker ---

# TODO: Define EscalationChecker
# This agent should check the status of the judge's feedback.
# If status is "pass", it should escalate (break the loop).

class EscalationChecker(BaseAgent):
    """Checks the judge's feedback and escalates (breaks the loop) if it passed."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        # Retrieve the feedback saved by the Judge
        feedback = ctx.session.state.get("judge_feedback")
        print(f"[EscalationChecker] Feedback: {feedback}")

        # Check for 'pass' status
        is_pass = False
        if isinstance(feedback, dict) and feedback.get("status") == "pass":
            is_pass = True
        # Handle string fallback if JSON parsing failed
        elif isinstance(feedback, str) and '"status": "pass"' in feedback:
            is_pass = True

        if is_pass:
            # 'escalate=True' tells the parent LoopAgent to stop looping
            yield Event(author=self.name, actions=EventActions(escalate=True))
        else:
            # Continue the loop
            yield Event(author=self.name)

escalation_checker = EscalationChecker(name="escalation_checker")

# --- Orchestration ---

# TODO: Define the Research Loop
# Use LoopAgent to cycle through Researcher -> Judge -> EscalationChecker.

research_loop = LoopAgent(
    name="research_loop",
    description="Iteratively researches and judges until quality standards are met.",
    sub_agents=[researcher, judge, escalation_checker],
    # Lowered from 3 to 1 to stay under the Gemini free-tier rate limit
    # (5 requests/minute). Raise it again on a paid tier for better quality.
    max_iterations=1,
)

# TODO: Define the Root Agent (Pipeline)
# Use SequentialAgent to run the Research Loop followed by the Content Builder.

root_agent = SequentialAgent(
    name="course_creation_pipeline",
    description="A pipeline that checks the local knowledge base, researches a topic, then builds a course from it.",
    # Knowledge base first (local material), then the research loop (web search
    # fills gaps), then the course builder.
    sub_agents=[knowledge_base, research_loop, content_builder],
    # Serve repeat topics straight from Redis, skipping the whole pipeline.
    before_agent_callback=check_course_cache,
)


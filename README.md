# course-creation-agent (Distributed)

A multi-agent system built with Google's Agent Development Kit (ADK) and Agent-to-Agent (A2A) protocol. It features a team of microservice agents that research, judge, and build content, orchestrated to deliver high-quality results.

## Architecture

This project uses a distributed microservices architecture where each agent runs in its own container and communicates via A2A:

*   **Orchestrator Service (`orchestrator`):** The main entry point. It manages the workflow using `LoopAgent` and `SequentialAgent`, and connects to other agents using `RemoteA2aAgent`.
*   **Knowledge Base Service (`knowledge_base`):** A standalone agent that reads curated local reference material (course syllabi, internal standards) over MCP (see [Knowledge Base via MCP](#knowledge-base-via-mcp)).
*   **Researcher Service (`researcher`):** A standalone agent that gathers information using Google Search.
*   **Judge Service (`judge`):** A standalone agent that evaluates research quality.
*   **Content Builder Service (`content_builder`):** A standalone agent that compiles the final course.
*   **Agent App (`app`):** A web application that queries the Orchestrator agent, displays progress and results.
*   **Redis:** A shared cache used by the Orchestrator to serve repeated topics without re-running the pipeline (see [Caching](#caching)).

### Pipeline

The Orchestrator runs a `SequentialAgent` over three stages:

```
Knowledge Base  →  Research Loop (Researcher ↔ Judge)  →  Content Builder
```

1. **Knowledge Base** checks the local `knowledge_base/` folder for material relevant to the topic and reports what it finds (or that nothing relevant exists).
2. **Research Loop** (a `LoopAgent`): the Researcher builds on the knowledge-base findings and uses Google Search to fill gaps; the Judge evaluates the result and can request another iteration. An `EscalationChecker` breaks the loop early once the Judge passes.
3. **Content Builder** turns the approved findings into the final course.

> The Knowledge Base and Researcher are deliberately **separate agents**: ADK disables automatic function calling when a built-in tool (`google_search`) is mixed with MCP tools on the *same* agent, so each agent holds only one kind of tool. See [Knowledge Base via MCP](#knowledge-base-via-mcp).

## Project Structure

```
course-creation-agent/
├── agents/
    ├── orchestrator/        # Main Orchestrator agent, ADK API Service
    ├── knowledge_base/      # Knowledge Base agent (reads local docs via MCP), A2A microservice
    ├── researcher/          # Researcher agent (Google Search), A2A microservice
    ├── judge/               # Judge agent, A2A microservice
    └── content_builder/     # Content Builder agent, A2A microservice
├── app/                     # Web App service application
    └── frontend/            # Frontend application
├── knowledge_base/          # Curated reference docs (syllabi, standards) read over MCP
├── shared/                  # Files used by all agents
├── logs/                    # Per-service logs written by run_local.sh (gitignored)
└── ...
```

### Shared files

There are some files in `shared` directory that are shared across all agents and the web app.
To avoid duplication, these files are linked into respective subdirectories as [**symlinks**](https://en.wikipedia.org/wiki/Symbolic_link).

* `a2a_utils.py` - contains code for rewriting agent URLs in A2A AgentCard when deployed in Cloud Run.
* `adk_app.py` - ADK API Service implementation with additional A2A functionality.
* `authenticated_httpx.py` - [httpx](https://www.python-httpx.org/) client extension for [service-to-service requests](https://docs.cloud.google.com/run/docs/authenticating/service-to-service).

## Caching

The Orchestrator caches the **finished course** in [Redis](https://redis.io/), keyed by a
normalized hash of the topic. This avoids re-running the expensive
`Researcher → Judge → Content Builder` pipeline (multiple LLM calls plus Google
Search) when the same topic is requested again.

* **On a cache hit**, the root pipeline's `before_agent_callback`
  (`check_course_cache` in [`agents/orchestrator/agent.py`](agents/orchestrator/agent.py))
  returns the cached course directly. ADK then skips the entire pipeline and
  ends the invocation, so the response is served in milliseconds.
* **On a cache miss**, the pipeline runs normally and the Content Builder's
  `after_agent_callback` (`save_course_to_cache`) writes the finished course to
  Redis with a 24-hour TTL.
* **Why Redis (not an in-process dict):** on Cloud Run the Orchestrator runs as
  multiple stateless instances. An external shared cache lets an entry written
  by one instance be reused by all of them — that's what makes it a
  *distributed* cache.
* **Graceful degradation:** all cache operations are wrapped so that an
  unreachable Redis silently falls back to a cache miss. Caching is a pure
  optimization and is never a hard dependency of the pipeline.

The cache is configured via the `REDIS_URL` environment variable (defaults to
`redis://localhost:6379`).

## Knowledge Base via MCP

The dedicated **Knowledge Base agent** reads curated local reference material
over the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/). Drop
trusted material — e.g. detailed course syllabi and internal standards — into the
[`knowledge_base/`](knowledge_base/) folder and the pipeline grounds the course
in it before falling back to the public web.

* **Dedicated agent:** the Knowledge Base agent
  ([`agents/knowledge_base/agent.py`](agents/knowledge_base/agent.py)) mounts the
  official `@modelcontextprotocol/server-filesystem` MCP server via ADK's
  `McpToolset`. The server is launched on demand with `npx`, so **Node.js is
  required** for this feature.
* **Why a separate agent (important):** ADK disables automatic function calling
  when a built-in tool such as `google_search` is combined with MCP tools on the
  *same* agent. So the MCP tools live on the Knowledge Base agent and
  `google_search` stays on the Researcher — each agent holds only one kind of
  tool. The Knowledge Base agent runs first; the Researcher then sees its
  findings in the shared session and only searches the web for what the local
  material doesn't cover (and honors any in-scope/out-of-scope limits it states).
* **Read-only by design:** only read-oriented tools (`read_file`,
  `read_text_file`, `list_directory`, `directory_tree`, `search_files`,
  `get_file_info`) are exposed via `tool_filter`, so the agent can read curated
  material but never modify it.
* **Configuration:** the folder defaults to `knowledge_base/` at the repo root
  and can be overridden with the `KNOWLEDGE_BASE_DIR` environment variable.
* **Graceful degradation:** if Node/`npx` is unavailable the rest of the
  pipeline still runs; the Knowledge Base agent just can't read local files.

> **MCP vs A2A:** these are two different protocols used here. **A2A** connects
> agents *to each other*; **MCP** connects an agent *to external tools/data
> sources*. The Knowledge Base agent uses MCP for the local files; the
> Orchestrator uses A2A to reach all the agents.

## Requirements

*   **uv**: Python package manager (required for local development).
*   **Gemini access**: either a **Google AI Studio API key** (simplest for local
    dev — get one at https://aistudio.google.com/apikey) or **Vertex AI** via the
    Google Cloud SDK. Configured through `.env` (see [Quick Start](#quick-start)).
*   **Node.js**: Provides `npx`, used to launch the filesystem MCP server for the
    Knowledge Base agent. Optional — the pipeline still works without it, just
    without the local knowledge base.
*   **Redis**: Distributed cache for the Orchestrator. Run one locally with
    `docker run -d --name redis -p 6379:6379 redis:7`. Optional — the pipeline
    still works without it, just without cache hits.

## Quick Start

1.  **Install Dependencies:**
    ```bash
    uv sync
    ```

2.  **Configure credentials (`.env`):**
    Copy the template and fill in your key:
    ```bash
    cp .env.example .env
    ```
    For the simplest local setup, get a free key at
    https://aistudio.google.com/apikey and set it in `.env`:
    ```
    GOOGLE_GENAI_USE_VERTEXAI="False"
    GOOGLE_API_KEY="AIza...your-key..."
    ```
    To use **Vertex AI** instead, set `GOOGLE_GENAI_USE_VERTEXAI="True"`, leave
    `GOOGLE_API_KEY` empty, run `gcloud auth application-default login`, and set
    `GOOGLE_CLOUD_PROJECT`. `.env` is gitignored — never commit your key.

3.  **Start Redis (optional, enables caching):**
    ```bash
    docker run -d --name redis -p 6379:6379 redis:7
    ```

4.  **Run Locally:**
    ```bash
    ./run_local.sh
    ```
    This starts all five agents (Knowledge Base, Researcher, Judge, Content
    Builder, Orchestrator) and the web app in the background. Each service's
    output is written to `logs/<service>.log`. The script warns if Redis or
    `npx` is missing (both optional).

5.  **Access the App:**
    Open **http://localhost:8000** in your browser.

> **Free-tier rate limits:** Gemini's free tier caps requests per minute
> (e.g. 5/min for some models), and this multi-agent pipeline makes several LLM
> calls per course. You may hit `429 RESOURCE_EXHAUSTED`. Mitigations: wait ~60s
> between generations, keep the research loop's `max_iterations` low (it is set
> to `2` in [`agents/orchestrator/agent.py`](agents/orchestrator/agent.py) — one
> refinement pass; set `1` to disable reflection, `3` rarely adds value), or
> enable billing for higher limits.

## Deployment

To deploy to Google Cloud Run, you need to deploy each service individually and then configure the Orchestrator with the URLs of the other services.

1.  **Deploy Knowledge Base, Researcher, Judge, Content Builder, and Orchestrator:**
    Deploy each of these folders as a separate Cloud Run service. Note down their URLs (e.g., `https://researcher-xyz.a.run.app`).

    The Knowledge Base service's container installs Node.js (for the MCP `npx`
    server) — see its [`Dockerfile`](agents/knowledge_base/Dockerfile).

    The **Orchestrator** needs the other agents' card URLs (it reads them from
    the environment):
    *   `KNOWLEDGE_BASE_AGENT_CARD_URL`: `https://<knowledge-base-url>/a2a/agent/.well-known/agent.json`
    *   `RESEARCHER_AGENT_CARD_URL`: `https://<researcher-url>/a2a/agent/.well-known/agent.json`
    *   `JUDGE_AGENT_CARD_URL`: `https://<judge-url>/a2a/agent/.well-known/agent.json`
    *   `CONTENT_BUILDER_AGENT_CARD_URL`: `https://<content-builder-url>/a2a/agent/.well-known/agent.json`

    For caching in production, provision a managed Redis (e.g.
    [Memorystore for Redis](https://cloud.google.com/memorystore)) and set
    `REDIS_URL` on the **Orchestrator** service to its connection string. If
    `REDIS_URL` is omitted, the Orchestrator runs fine but without cache hits.

2.  **Deploy Agent App:**
    Deploy the `app/` folder to Cloud Run and set `AGENT_URL`/`AGENT_SERVER_URL`
    to `https://<orchestrator-url>`.

3.  **Access:**
    Open the App's URL in your browser.

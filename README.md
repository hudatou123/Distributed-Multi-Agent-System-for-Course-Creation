# course-creation-agent (Distributed)

A multi-agent system built with Google's Agent Development Kit (ADK) and Agent-to-Agent (A2A) protocol. It features a team of microservice agents that research, judge, and build content, orchestrated to deliver high-quality results.

## Architecture

This project uses a distributed microservices architecture where each agent runs in its own container and communicates via A2A:

*   **Orchestrator Service (`orchestrator`):** The main entry point. It manages the workflow using `LoopAgent` and `SequentialAgent`, and connects to other agents using `RemoteA2aAgent`.
*   **Researcher Service (`researcher`):** A standalone agent that gathers information using Google Search and a curated local knowledge base exposed over MCP (see [Knowledge Base via MCP](#knowledge-base-via-mcp)).
*   **Judge Service (`judge`):** A standalone agent that evaluates research quality.
*   **Content Builder Service (`content_builder`):** A standalone agent that compiles the final course.
*   **Agent App (`app`):** A web application that queries the Orchestrator agent, displays progress and results.
*   **Redis:** A shared cache used by the Orchestrator to serve repeated topics without re-running the pipeline (see [Caching](#caching)).

## Project Structure

```
course-creation-agent/
├── agents/
    ├── orchestrator/        # Main Orchestrator agent, ADK API Service
    ├── researcher/          # Researcher agent, A2A microservice
    ├── judge/               # Judge agent, A2A microservice
    └── content_builder/     # Content Builder agent, A2A microservice
├── app/                     # Web App service application
    └── frontend/            # Frontend application
├── knowledge_base/          # Curated docs the Researcher reads over MCP
├── shared/                  # Files used by all agents
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

The Researcher reads a curated local knowledge base over the
[Model Context Protocol (MCP)](https://modelcontextprotocol.io/). This lets you
drop trusted reference material — e.g. detailed course syllabi and internal
standards — into the [`knowledge_base/`](knowledge_base/) folder and have the
agent ground its research in it before falling back to the public web.

* **How it connects:** the Researcher
  ([`agents/researcher/agent.py`](agents/researcher/agent.py)) mounts the
  official `@modelcontextprotocol/server-filesystem` MCP server via ADK's
  `McpToolset`. The server is launched on demand with `npx`, so **Node.js is
  required** for this feature.
* **Read-only by design:** only read-oriented tools (`read_file`,
  `list_directory`, `search_files`, …) are exposed via `tool_filter`, so the
  agent can read curated material but never modify it.
* **Tool priority:** the Researcher consults the knowledge base *first* and uses
  Google Search only to fill gaps.
* **Configuration:** the folder defaults to `knowledge_base/` at the repo root
  and can be overridden with the `KNOWLEDGE_BASE_DIR` environment variable.
* **Graceful degradation:** if Node/`npx` is unavailable the rest of the
  pipeline still runs; the Researcher just loses its local-knowledge tools.

> **MCP vs A2A:** these are two different protocols used here. **A2A** connects
> agents *to each other*; **MCP** connects an agent *to external tools/data
> sources*. The Researcher uses MCP for the knowledge base; the Orchestrator
> uses A2A to reach the Researcher/Judge/Content Builder.

## Requirements

*   **uv**: Python package manager (required for local development).
*   **Google Cloud SDK**: For GCP services and authentication.
*   **Node.js**: Provides `npx`, used to launch the filesystem MCP server for
    the Researcher's knowledge base. Optional — the pipeline still works
    without it, just without the local knowledge base.
*   **Redis**: Distributed cache for the Orchestrator. Run one locally with
    `docker run -d --name redis -p 6379:6379 redis:7`. Optional — the pipeline
    still works without it, just without cache hits.

## Quick Start

1.  **Install Dependencies:**
    ```bash
    uv sync
    ```

2.  **Set up credentials:**
    Ensure you have Google Cloud credentials available. You might need to run:
    ```bash
    gcloud auth application-default login
    ```
    And ensure your `GOOGLE_CLOUD_PROJECT` environment variable is set.

3.  **Start Redis (optional, enables caching):**
    ```bash
    docker run -d --name redis -p 6379:6379 redis:7
    ```

4.  **Run Locally:**
    ```bash
    ./run_local.sh
    ```
    This will start all 4 agents and the web app in background processes.
    The script checks whether Redis is reachable and prints a warning if not.

5.  **Access the App:**
    Open **http://localhost:8000** in your browser.

## Deployment

To deploy to Google Cloud Run, you need to deploy each service individually and then configure the Orchestrator with the URLs of the other services.

1.  **Deploy Researcher, Judge, Content Builder, and Orchestrator:**
    Deploy each of these folders as a separate Cloud Run service. Note down their URLs (e.g., `https://researcher-xyz.a.run.app`).

    For caching in production, provision a managed Redis (e.g.
    [Memorystore for Redis](https://cloud.google.com/memorystore)) and set
    `REDIS_URL` on the **Orchestrator** service to its connection string. If
    `REDIS_URL` is omitted, the Orchestrator runs fine but without cache hits.

2.  **Deploy Agent App:**
    Deploy the `app/` folder to Cloud Run.
    Set the following environment variables on the Agent App service:
    *   `RESEARCHER_AGENT_CARD_URL`: `https://<researcher-url>/a2a/agent/.well-known/agent.json`
    *   `JUDGE_AGENT_CARD_URL`: `https://<judge-url>/a2a/agent/.well-known/agent.json`
    *   `CONTENT_BUILDER_AGENT_CARD_URL`: `https://<content-builder-url>/a2a/agent/.well-known/agent.json`
    *   `AGENT_URL`: `https://<orchestrator-url>`

3.  **Access:**
    Open the App's URL in your browser.

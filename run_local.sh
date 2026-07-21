#!/bin/bash

# Kill any existing processes on these ports
echo "Stopping any existing processes on ports 8000-8004..."
lsof -ti:8000,8001,8002,8003,8004,8005 | xargs kill -9 2>/dev/null

# Load local secrets/overrides (e.g. GOOGLE_API_KEY) from .env if present.
# Keep secrets in .env (gitignored) — never hard-code them in this script.
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

# Set common environment variables for local development.
# Defaults target the Google AI Studio (Gemini Developer API) path; override
# any of these in .env (e.g. set GOOGLE_GENAI_USE_VERTEXAI=True for Vertex).
export GOOGLE_GENAI_USE_VERTEXAI="${GOOGLE_GENAI_USE_VERTEXAI:-False}"
export GOOGLE_CLOUD_LOCATION="${GOOGLE_CLOUD_LOCATION:-global}"

# When using Vertex AI, derive the project from gcloud if not already set.
if [ "$GOOGLE_GENAI_USE_VERTEXAI" = "True" ] && command -v gcloud >/dev/null 2>&1; then
  export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
fi

# When using the AI Studio path, a real API key is required to call Gemini.
if [ "$GOOGLE_GENAI_USE_VERTEXAI" != "True" ] && [ -z "$GOOGLE_API_KEY" ]; then
  echo "⚠️  GOOGLE_API_KEY is not set. Put it in a .env file (see .env.example) — get one at https://aistudio.google.com/apikey"
fi

export REDIS_URL="${REDIS_URL:-redis://localhost:6379}" # Distributed course cache (orchestrator)
export KNOWLEDGE_BASE_DIR="$(pwd)/knowledge_base" # Curated docs the Researcher reads over MCP

# Write each service's output to its own log file for easier debugging.
ROOT="$(pwd)"
mkdir -p "$ROOT/logs"
echo "📝 Per-agent logs in $ROOT/logs/ (researcher.log, judge.log, content_builder.log, orchestrator.log, app.log)"

# The Researcher reads the knowledge base through the filesystem MCP server,
# which is launched via `npx` and therefore needs Node.js installed.
if ! command -v npx >/dev/null 2>&1; then
  echo "⚠️  npx (Node.js) not found — the Researcher's MCP knowledge base will be unavailable."
fi

# Make sure Redis is running. The cache degrades gracefully if it isn't, but
# you won't get any cache hits. Start one quickly with:
#   docker run -d --name redis -p 6379:6379 redis:7
if ! (exec 3<>/dev/tcp/127.0.0.1/6379) 2>/dev/null; then
  echo "⚠️  Redis not reachable on localhost:6379 — caching disabled (pipeline still works)."
  echo "    Start it with: docker run -d --name redis -p 6379:6379 redis:7"
else
  echo "✅ Redis is up on localhost:6379"
fi

echo "Starting Knowledge Base Agent on port 8005..."
pushd agents/knowledge_base
uv run adk_app.py --host 0.0.0.0 --port 8005 --a2a . > "$ROOT/logs/knowledge_base.log" 2>&1 &
KNOWLEDGE_BASE_PID=$!
popd

echo "Starting Researcher Agent on port 8001..."
pushd agents/researcher
uv run adk_app.py --host 0.0.0.0 --port 8001 --a2a . > "$ROOT/logs/researcher.log" 2>&1 &
RESEARCHER_PID=$!
popd

echo "Starting Judge Agent on port 8002..."
pushd agents/judge
uv run adk_app.py --host 0.0.0.0 --port 8002 --a2a . > "$ROOT/logs/judge.log" 2>&1 &
JUDGE_PID=$!
popd

echo "Starting Content Builder Agent on port 8003..."
pushd agents/content_builder
uv run adk_app.py --host 0.0.0.0 --port 8003 --a2a . > "$ROOT/logs/content_builder.log" 2>&1 &
CONTENT_BUILDER_PID=$!
popd

export KNOWLEDGE_BASE_AGENT_CARD_URL=http://localhost:8005/a2a/agent/.well-known/agent-card.json
export RESEARCHER_AGENT_CARD_URL=http://localhost:8001/a2a/agent/.well-known/agent-card.json
export JUDGE_AGENT_CARD_URL=http://localhost:8002/a2a/agent/.well-known/agent-card.json
export CONTENT_BUILDER_AGENT_CARD_URL=http://localhost:8003/a2a/agent/.well-known/agent-card.json

echo "Starting Orchestrator Agent on port 8004..."
pushd agents/orchestrator
uv run adk_app.py --host 0.0.0.0 --port 8004 . > "$ROOT/logs/orchestrator.log" 2>&1 &
ORCHESTRATOR_PID=$!
popd

# Wait a bit for them to start up
sleep 5

echo "Starting Orchestrator Agent on port 8000..."
pushd app
export AGENT_SERVER_URL=http://localhost:8004

uv run uvicorn main:app --host 0.0.0.0 --port 8000 > "$ROOT/logs/app.log" 2>&1 &
BACKEND_PID=$!
popd

echo "All agents started!"
echo "Knowledge Base: http://localhost:8005"
echo "Researcher: http://localhost:8001"
echo "Judge: http://localhost:8002"
echo "Content Builder: http://localhost:8003"
echo "Orchestrator: http://localhost:8004"
echo "App Server (Frontend): http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop all agents."

# Wait for all processes
trap "kill $KNOWLEDGE_BASE_PID $RESEARCHER_PID $JUDGE_PID $CONTENT_BUILDER_PID $ORCHESTRATOR_PID $BACKEND_PID; exit" INT
wait

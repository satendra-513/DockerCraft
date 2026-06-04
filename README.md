# DockerCraft 🚀

DockerCraft is an AI-powered developer tool that analyzes Git repositories, generates optimized Dockerfiles, runs test builds, self-corrects up to 3 times on failures, and verifies container startups. 

It is built as a **Client-Server Web Application** utilizing a **FastAPI backend** and a beautiful **glassmorphic Vite/Vanilla JS web dashboard** with real-time log streaming over WebSockets.

---

## 🛠️ Architectural Overview

DockerCraft operates on a decoupled client-server architecture coordinating a specialized multi-agent pipeline:

```mermaid
graph TD
    User([User]) <-->|WebSockets / HTTP| Frontend[Vite Frontend Dashboard]
    subgraph FastAPI Backend
        Frontend <-->|Real-time Pipeline Logs & Events| WS[WebSocket Controller]
        WS -->|Trigger Pipeline| Manager[Orchestrator Engine]
        Manager -->|1. Clone Repo| Git[Git Cloner]
        Manager -->|2. Scan File Tree & Manifests| Analyzer[Analyzer Agent]
        Manager -->|3. Generate Initial Dockerfile| Generator[Generator Agent]
        Manager -->|4. Test & Repair Build (Max 3 retries)| Debugger[Debugger Agent]
        Manager -->|5. Verify Container Startup| Verifier[Container Verifier]
    end
    subgraph Host / Docker Daemon
        Verifier -->|docker run| DockerD[(Docker Daemon)]
        Generator -.->|docker build| DockerD
    end
```

### Components

* **Interactive Web Dashboard:** A responsive single-page web panel with pipeline progress visualization (stepper timeline), interactive side-by-side workspace (editable Dockerfile pane + live terminal logs), and project metadata card displays.
* **FastAPI Backend:** Communicates with the Docker daemon using the Docker Python SDK, manages git cloning with GitPython, and coordinates the LLM Multi-Agent system.
* **Multi-Agent Pipeline:** Coordinated state-machine utilizing three specialized LLM agents communicating with Pydantic schemas:
  1. **Analyzer Agent:** Inspects file structure and manifest contents (`package.json`, `requirements.txt`, etc.) to build a project profile.
  2. **Generator Agent:** Takes the profile and outputs a production-ready, security-hardened Dockerfile (caching-optimized, non-root user).
  3. **Debugger Agent:** Invoked on build failures with the error logs to diagnose and output a corrected Dockerfile (retries up to 3 times).

---

## 📋 Prerequisites

1. **Docker Desktop** (or dockerd daemon) must be running on your host machine.
2. **Python 3.12+**
3. **Node.js 18+ & npm**
4. **Groq API Key** (optional, fallback rule-based mode is automatically activated if not provided).

---

## 🚀 Setup & Execution

### 1. Backend Setup
Navigate to the `backend/` directory, configure environment variables, install dependencies, and start the FastAPI server:

```bash
cd backend

# Create .env and configure GROQ_API_KEY
# If left empty, DockerCraft will fall back to rule-based generation so you can still use it!
# GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxx

# Install dependencies (virtual environment recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Start the server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
The backend API starts running on `http://localhost:8000`.

### 2. Frontend Setup
Open another terminal pane, navigate to the `frontend/` directory, install dependencies, and spin up the Vite server:

```bash
cd frontend
npm install
npm run dev
```
The Vite development server will run on `http://localhost:5173`. Open your browser and go to `http://localhost:5173`.

### 3. Running with Docker (Recommended)

Since the project is fully Dockerized, you can launch DockerCraft in a single command using Docker Compose:

```bash
# Set your Groq API Key (optional)
export GROQ_API_KEY="your_api_key_here"  # Windows PowerShell: $env:GROQ_API_KEY="your_api_key_here"

# Build and start the container
docker compose up --build
```

Or run it using the Docker CLI directly:

```bash
# Build the unified container
docker build -t dockercraft:latest .

# Run the container (mounting the docker socket is required)
docker run -d -p 8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e GROQ_API_KEY \
  --name dockercraft-app \
  dockercraft:latest
```

The application will be served at `http://localhost:8000`.

---

## 🔄 Verification & Walkthrough

1. Open `http://localhost:5173` in your browser. You should see the **DockerCraft** neon dashboard.
2. The top right badge should show **ONLINE** (green), indicating a successful WebSocket handshake with the backend at `ws://localhost:8000/ws/stream`.
3. Enter a git repository URL (e.g. `https://github.com/pallets/flask.git` or `https://github.com/expressjs/express.git`) and click **Build Container**.
4. The stepper will progress through the pipeline phases:
   * **Cloning:** The repository is shallowly cloned.
   * **Analyzing:** Manifest files are processed.
   * **Generating:** The initial Dockerfile is written.
   * **Building:** Streams compiler logs chunk-by-chunk in real-time. If it fails, the **Debugger Agent** starts self-correcting.
   * **Verifying:** The built container starts in detached mode on an ephemeral port. It stays active for 5 seconds to inspect runtime stability, prints its startup logs to the screen, stops, and clears the container.
5. If the build finishes, you can edit the Dockerfile in the **Interactive Dockerfile Editor** pane, adjust the mapped port, and click **Re-Build & Verify** to instantly verify your customized changes!

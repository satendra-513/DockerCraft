import os
import json
import logging
from typing import List, Optional, Dict, Type, Any
from pydantic import BaseModel, Field
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("dockercraft.agents")

# Pydantic Schemas for Structured JSON outputs
class AnalysisResult(BaseModel):
    language: str = Field(description="The primary programming language detected (e.g. python, node, go, rust, java)")
    framework: Optional[str] = Field(None, description="The detected runtime framework (e.g. fastapi, express, nextjs, gin, spring-boot)")
    dependencies: List[str] = Field(default=[], description="Key dependencies detected from the manifests")
    package_manager: Optional[str] = Field(None, description="The package manager used (e.g. npm, yarn, pip, poetry, go-modules, cargo)")
    suggested_entrypoint: Optional[str] = Field(None, description="The suggested entry point file (e.g. main.py, src/index.js, main.go)")
    build_steps: List[str] = Field(default=[], description="Build steps required before running (e.g. npm run build, go build)")
    run_command: str = Field(description="Command to start the application (e.g. python main.py, npm start, ./main)")
    port: int = Field(8080, description="The port the application listens on (default to 8080 if not specified)")
    env_vars: Dict[str, str] = Field(default={}, description="Environment variables needed to run the app")

class GeneratorResult(BaseModel):
    dockerfile: str = Field(description="The optimized Dockerfile content")
    explanation: str = Field(description="Brief explanation of the Dockerfile optimization decisions")

class DebuggerResult(BaseModel):
    dockerfile: str = Field(description="The corrected, repaired Dockerfile content")
    root_cause: str = Field(description="The root cause analysis of the build error")
    fix_explanation: str = Field(description="Explanation of the fix applied to resolve the error")


class BaseAgent:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY", "").strip()
        self.client = None
        self.model = "llama-3.3-70b-versatile"
        
        if self.api_key:
            try:
                self.client = Groq(api_key=self.api_key)
            except Exception as e:
                logger.error(f"Failed to initialize Groq client: {e}")

    def _call_llm(self, system_prompt: str, user_prompt: str, schema: Type[BaseModel]) -> Dict[str, Any]:
        """Calls Groq Chat API in JSON mode. Falls back to manual extraction if needed."""
        if not self.client:
            raise ValueError("Groq client not initialized (missing GROQ_API_KEY)")
            
        try:
            # We request JSON mode using response_format
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                model=self.model,
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            content = chat_completion.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            logger.error(f"Groq API call failed: {e}")
            raise e

    def _clean_json_response(self, text: str) -> str:
        """Cleans and extracts JSON block from LLM string if JSON mode wasn't strictly honored."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()


class AnalyzerAgent(BaseAgent):
    def analyze(self, file_tree: str, manifests: Dict[str, str]) -> AnalysisResult:
        """Analyzes directory tree and manifest files to determine project properties."""
        manifest_str = ""
        for filename, content in manifests.items():
            manifest_str += f"\n--- File: {filename} ---\n{content}\n"

        system_prompt = (
            "You are a Senior DevOps Engineer and repository analyzer. "
            "Your task is to analyze the file tree and manifests of a project to determine its build/run properties. "
            "You must return a JSON object matching this schema:\n"
            "{\n"
            "  \"language\": \"string\",\n"
            "  \"framework\": \"string or null\",\n"
            "  \"dependencies\": [\"string\"],\n"
            "  \"package_manager\": \"string or null\",\n"
            "  \"suggested_entrypoint\": \"string or null\",\n"
            "  \"build_steps\": [\"string\"],\n"
            "  \"run_command\": \"string\",\n"
            "  \"port\": number,\n"
            "  \"env_vars\": { \"key\": \"value\" }\n"
            "}\n"
            "Do not include any formatting, markdown, or text outside the JSON object. Output ONLY valid JSON."
        )

        user_prompt = (
            f"Here is the directory tree representation of the repository:\n"
            f"```\n{file_tree}\n```\n\n"
            f"Here are the contents of the detected manifest files:\n"
            f"{manifest_str}\n"
            f"Analyze this information and output the project profile."
        )

        if not self.client:
            # Fallback to local rule-based analysis
            logger.warning("GROQ_API_KEY not set. Using rule-based Analyzer fallback.")
            return self._fallback_analyze(file_tree, manifests)

        try:
            result_json = self._call_llm(system_prompt, user_prompt, AnalysisResult)
            return AnalysisResult.model_validate(result_json)
        except Exception as e:
            logger.error(f"AnalyzerAgent LLM call failed, falling back to rule-based: {e}")
            return self._fallback_analyze(file_tree, manifests)

    def _fallback_analyze(self, file_tree: str, manifests: Dict[str, str]) -> AnalysisResult:
        # Check Node.js
        if "package.json" in manifests:
            pkg_data = {}
            try:
                pkg_data = json.loads(manifests["package.json"])
            except:
                pass
            
            dependencies = list(pkg_data.get("dependencies", {}).keys()) + list(pkg_data.get("devDependencies", {}).keys())
            framework = None
            if "express" in dependencies:
                framework = "express"
            elif "react" in dependencies:
                framework = "react"
            elif "next" in dependencies:
                framework = "nextjs"
                
            entrypoint = pkg_data.get("main", "index.js")
            scripts = pkg_data.get("scripts", {})
            run_cmd = "npm start"
            if "start" not in scripts and "index.js" in file_tree:
                run_cmd = "node index.js"
                
            build_steps = []
            if "build" in scripts:
                build_steps = ["npm run build"]
                
            port = 3000
            if framework == "nextjs":
                port = 3000
            elif "express" in dependencies:
                port = 3000
                
            return AnalysisResult(
                language="node",
                framework=framework,
                dependencies=dependencies[:10],
                package_manager="npm",
                suggested_entrypoint=entrypoint,
                build_steps=build_steps,
                run_command=run_cmd,
                port=port,
                env_vars={"NODE_ENV": "production"}
            )
            
        # Check Python
        if "requirements.txt" in manifests or "pyproject.toml" in manifests:
            framework = None
            dependencies = []
            if "requirements.txt" in manifests:
                dependencies = [line.split("==")[0].strip() for line in manifests["requirements.txt"].split("\n") if line.strip() and not line.startswith("#")]
            
            if "pyproject.toml" in manifests:
                toml = manifests["pyproject.toml"]
                if "poetry" in toml:
                    package_manager = "poetry"
                else:
                    package_manager = "pip"
            else:
                package_manager = "pip"
                
            # Detect framework
            all_deps_lower = [d.lower() for d in dependencies]
            if "fastapi" in all_deps_lower or "fastapi" in file_tree:
                framework = "fastapi"
            elif "django" in all_deps_lower or "django" in file_tree:
                framework = "django"
            elif "flask" in all_deps_lower or "flask" in file_tree:
                framework = "flask"
                
            # Try to guess run command
            run_cmd = "python main.py"
            suggested_entry = "main.py"
            port = 8000
            
            if framework == "fastapi":
                run_cmd = "uvicorn main:app --host 0.0.0.0 --port 8000"
                if "app/main.py" in file_tree:
                    run_cmd = "uvicorn app.main:app --host 0.0.0.0 --port 8000"
                    suggested_entry = "app/main.py"
            elif framework == "django":
                run_cmd = "python manage.py runserver 0.0.0.0:8000"
                suggested_entry = "manage.py"
            elif framework == "flask":
                run_cmd = "flask run --host=0.0.0.0 --port=8000"
                suggested_entry = "app.py"
                
            return AnalysisResult(
                language="python",
                framework=framework,
                dependencies=dependencies[:10],
                package_manager=package_manager,
                suggested_entrypoint=suggested_entry,
                build_steps=[],
                run_command=run_cmd,
                port=port,
                env_vars={"PYTHONUNBUFFERED": "1"}
            )
            
        # Check Go
        if "go.mod" in manifests or "main.go" in file_tree:
            return AnalysisResult(
                language="go",
                framework="gin" if "gin" in file_tree else None,
                dependencies=[],
                package_manager="go-modules",
                suggested_entrypoint="main.go",
                build_steps=["go build -o main ."],
                run_command="./main",
                port=8080,
                env_vars={"GIN_MODE": "release"}
            )

        # Default fallback
        return AnalysisResult(
            language="static-html",
            framework=None,
            dependencies=[],
            package_manager=None,
            suggested_entrypoint="index.html",
            build_steps=[],
            run_command="npx serve -s . -p 8080",
            port=8080,
            env_vars={}
        )


class GeneratorAgent(BaseAgent):
    def generate(self, analysis: AnalysisResult) -> GeneratorResult:
        """Generates a high-quality Dockerfile based on Analyzer metadata."""
        system_prompt = (
            "You are an expert DevOps engineer who writes highly optimized, secure, production-grade Dockerfiles.\n"
            "Your output must be a JSON object matching this schema:\n"
            "{\n"
            "  \"dockerfile\": \"string (containing the actual Dockerfile code)\",\n"
            "  \"explanation\": \"string (brief explanation of decisions)\"\n"
            "}\n"
            "Guidelines for Dockerfile generation:\n"
            "1. Multi-stage builds are preferred for compiled languages (Go, Java, Rust) and complex frontend apps (React/Vite, Next.js).\n"
            "2. Optimize layer caching: Copy lock/manifest files first, install dependencies, then copy code.\n"
            "3. Security: Running as non-root is MANDATORY. Create a system user and group and run using the USER instruction.\n"
            "4. Port EXPOSE: Expose the correct port and bind applications to 0.0.0.0.\n"
            "5. Slim Base Images: Prefer -slim or -alpine images.\n"
            "Do not include any formatting, markdown, or text outside the JSON object. Output ONLY valid JSON."
        )

        user_prompt = (
            f"Here is the project analysis data:\n"
            f"```json\n{analysis.model_dump_json(indent=2)}\n```\n\n"
            f"Generate the optimized Dockerfile."
        )

        if not self.client:
            logger.warning("GROQ_API_KEY not set. Using rule-based Generator fallback.")
            return self._fallback_generate(analysis)

        try:
            result_json = self._call_llm(system_prompt, user_prompt, GeneratorResult)
            return GeneratorResult.model_validate(result_json)
        except Exception as e:
            logger.error(f"GeneratorAgent LLM call failed, falling back to rule-based: {e}")
            return self._fallback_generate(analysis)

    def _fallback_generate(self, analysis: AnalysisResult) -> GeneratorResult:
        lang = analysis.language.lower()
        port = analysis.port or 8080
        run_cmd_list = analysis.run_command.split(" ")
        run_cmd_json = json.dumps(run_cmd_list)
        
        if lang == "node":
            dockerfile = f"""FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production || npm install --only=production
COPY . .
{chr(10).join([f"RUN {step}" for step in analysis.build_steps])}

FROM node:20-alpine
WORKDIR /app
COPY --from=builder /app /app
RUN addgroup -S appgroup && adduser -S appuser -G appgroup && chown -R appuser:appgroup /app
USER appuser
EXPOSE {port}
ENV PORT={port}
CMD {run_cmd_json}
"""
            explanation = "Created multi-stage node build, cached node_modules, created non-root appuser, exposed requested port."
            
        elif lang == "python":
            # Determine requirements copy
            req_copy = "COPY requirements.txt ./\nRUN pip install --no-cache-dir -r requirements.txt"
            if analysis.package_manager == "poetry":
                req_copy = "RUN pip install poetry && poetry config virtualenvs.create false\nCOPY pyproject.toml poetry.lock* ./\nRUN poetry install --no-root --no-dev"
            
            dockerfile = f"""FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
{req_copy}
COPY . .
RUN addgroup --system appgroup && adduser --system --group appuser && chown -R appuser:appgroup /app
USER appuser
EXPOSE {port}
ENV PORT={port}
CMD {run_cmd_json}
"""
            explanation = "Used official python slim base, cached pip package installation, created appuser non-root security configuration."
            
        elif lang == "go":
            dockerfile = f"""FROM golang:1.21-alpine AS builder
WORKDIR /app
COPY go.mod go.sum* ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o app .

FROM alpine:latest
RUN apk --no-cache add ca-certificates
WORKDIR /app
COPY --from=builder /app/app .
RUN addgroup -S appgroup && adduser -S appuser -G appgroup && chown -R appuser:appgroup /app
USER appuser
EXPOSE {port}
CMD ["./app"]
"""
            explanation = "Compiled statically linked Go binary using multi-stage build, resulting in minimal final Alpine run image."
            
        else:
            # Default static HTML
            dockerfile = f"""FROM node:20-alpine
WORKDIR /app
COPY . .
RUN npm install -g serve
RUN addgroup -S appgroup && adduser -S appuser -G appgroup && chown -R appuser:appgroup /app
USER appuser
EXPOSE {port}
CMD ["serve", "-s", ".", "-p", "{port}"]
"""
            explanation = "Static file serving using npm serve utility, running under container appuser."

        return GeneratorResult(dockerfile=dockerfile, explanation=explanation)


class DebuggerAgent(BaseAgent):
    def debug(self, dockerfile: str, build_errors: str) -> DebuggerResult:
        """Diagnoses a Docker build failure and generates a corrected Dockerfile."""
        system_prompt = (
            "You are a Senior DevOps Engineer specializing in containerization troubleshooting.\n"
            "You are given a Dockerfile that failed to build, and the filtered build output logs containing the error trace.\n"
            "Your goal is to inspect the error, identify the root cause, and write a corrected Dockerfile that resolves the error.\n"
            "Output must be a JSON object matching this schema:\n"
            "{\n"
            "  \"dockerfile\": \"string (the corrected Dockerfile code)\",\n"
            "  \"root_cause\": \"string (explanation of why the build failed)\",\n"
            "  \"fix_explanation\": \"string (explanation of what you changed to fix the issue)\"\n"
            "}\n"
            "Do not include any formatting, markdown, or text outside the JSON object. Output ONLY valid JSON."
        )

        user_prompt = (
            f"--- FAILED DOCKERFILE ---\n"
            f"```dockerfile\n{dockerfile}\n```\n\n"
            f"--- FILTERED BUILD ERROR LOGS ---\n"
            f"```\n{build_errors}\n```\n\n"
            f"Diagnose the build failure and output the corrected Dockerfile JSON."
        )

        if not self.client:
            logger.warning("GROQ_API_KEY not set. Debugger agent will return the original Dockerfile with a mock description.")
            return DebuggerResult(
                dockerfile=dockerfile,
                root_cause="LLM Debugger not active (missing GROQ_API_KEY)",
                fix_explanation="No modifications applied because the LLM is inactive."
            )

        try:
            result_json = self._call_llm(system_prompt, user_prompt, DebuggerResult)
            return DebuggerResult.model_validate(result_json)
        except Exception as e:
            logger.error(f"DebuggerAgent LLM call failed: {e}")
            # Safe fallback
            return DebuggerResult(
                dockerfile=dockerfile,
                root_cause=f"Error in LLM call: {str(e)}",
                fix_explanation="Failed to contact debugger LLM. Returning original Dockerfile."
            )

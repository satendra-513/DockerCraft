import os
import shutil
import asyncio
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.utils import get_repo_temp_path, clone_repository, generate_file_tree, get_manifest_contents, truncate_docker_logs, rmtree_compat
from app.agents import AnalyzerAgent, GeneratorAgent, DebuggerAgent, AnalysisResult
from app.docker_ops import build_docker_image, verify_container_startup, BuildError

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("dockercraft")

app = FastAPI(title="DockerCraft API", description="AI-Powered Containerization Engine API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class RepoRequest(BaseModel):
    repo_url: str

# Detect frontend static paths
frontend_dist_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))
static_dir_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "dockercraft"}

# Only define fallback root route if static frontend files are not present
if not (os.path.exists(frontend_dist_path) or os.path.exists(static_dir_path)):
    @app.get("/")
    def read_root():
        return {"message": "Welcome to DockerCraft API. Connect to /ws/stream via WebSockets to stream pipelines."}


@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket client connected.")
    
    # Store active temp path for cleanup on disconnect
    active_temp_path = None
    image_tag = None
    
    # Helper to send log messages
    async def send_log(source: str, message: str):
        try:
            await websocket.send_json({
                "type": "log",
                "source": source,
                "message": message
            })
        except Exception as e:
            logger.error(f"Error sending log: {e}")
            
    # Helper to send step updates
    async def send_step(step: str):
        try:
            await websocket.send_json({
                "type": "step",
                "step": step
            })
        except Exception as e:
            logger.error(f"Error sending step: {e}")

    try:
        while True:
            # Receive instructions
            data = await websocket.receive_json()
            msg_type = data.get("type")
            
            if msg_type == "start":
                repo_url = data.get("repo_url")
                if not repo_url:
                    await send_log("agent", "Error: repo_url is required.")
                    continue
                    
                await send_log("agent", f"Starting pipeline for: {repo_url}")
                
                # Setup paths and image tag
                active_temp_path = get_repo_temp_path(repo_url)
                image_name = os.path.basename(repo_url.rstrip("/")).replace(".git", "").lower()
                image_tag = f"dockercraft-{image_name}:latest"
                
                # Step 1: Cloning
                await send_step("cloning")
                await send_log("agent", f"Cloning repository shallowly into {active_temp_path}...")
                try:
                    clone_repository(repo_url, active_temp_path)
                    await send_log("agent", "Repository successfully cloned.")
                except Exception as e:
                    logger.error(f"Cloning failed: {e}")
                    await send_log("agent", f"CLONING FAILED: {str(e)}")
                    await send_step("failed")
                    await websocket.send_json({"type": "status", "status": "failed", "message": "Cloning failed."})
                    continue
                
                # Step 2: Analyzing
                await send_step("analyzing")
                await send_log("agent", "Analyzing project directory structure and files...")
                
                file_tree = generate_file_tree(active_temp_path, max_depth=3)
                manifests = get_manifest_contents(active_temp_path)
                
                await send_log("agent", f"Detected manifest files: {list(manifests.keys())}")
                
                analyzer = AnalyzerAgent()
                analysis = analyzer.analyze(file_tree, manifests)
                
                await send_log("agent", f"Analysis completed. Language: {analysis.language}, Framework: {analysis.framework}")
                await websocket.send_json({
                    "type": "analysis",
                    "data": analysis.model_dump()
                })
                
                # Step 3: Generating Dockerfile
                await send_step("generating")
                await send_log("agent", "Generating optimized production Dockerfile...")
                
                generator = GeneratorAgent()
                gen_result = generator.generate(analysis)
                
                dockerfile_content = gen_result.dockerfile
                await send_log("agent", f"Initial Dockerfile generated: {gen_result.explanation[:100]}...")
                await websocket.send_json({
                    "type": "generation",
                    "dockerfile": dockerfile_content,
                    "explanation": gen_result.explanation
                })
                
                # Step 4 & 5: Build & Debug loops
                debugger = DebuggerAgent()
                retries = 0
                max_retries = 3
                build_success = False
                
                while retries <= max_retries:
                    await send_step("building")
                    await send_log("agent", f"Building Docker image (Attempt {retries + 1}/{max_retries + 1})...")
                    
                    try:
                        # Define docker stream logger callback
                        async def docker_logger(source: str, msg: str):
                            await send_log(source, msg)
                            
                        await build_docker_image(active_temp_path, dockerfile_content, image_tag, docker_logger)
                        build_success = True
                        break
                    except BuildError as be:
                        retries += 1
                        if retries > max_retries:
                            await send_log("agent", f"Docker build failed after {max_retries} self-correction attempts.")
                            break
                            
                        await send_step("debugging")
                        await send_log("agent", f"Build failed. Activating AI self-correction debugger (Attempt {retries}/{max_retries})...")
                        
                        # Filter/truncate build logs
                        truncated_logs = truncate_docker_logs(be.logs)
                        await send_log("agent", "Sending build failure tracebacks to AI Debugger...")
                        
                        debug_result = debugger.debug(dockerfile_content, truncated_logs)
                        dockerfile_content = debug_result.dockerfile
                        
                        await send_log("agent", f"AI Debugger Diagnosis: {debug_result.root_cause}")
                        await send_log("agent", f"Proposed Fix: {debug_result.fix_explanation}")
                        
                        # Send updated dockerfile to UI
                        await websocket.send_json({
                            "type": "generation",
                            "dockerfile": dockerfile_content,
                            "explanation": debug_result.fix_explanation,
                            "root_cause": debug_result.root_cause,
                            "fix_explanation": debug_result.fix_explanation
                        })
                        
                if not build_success:
                    await send_step("failed")
                    await websocket.send_json({"type": "status", "status": "failed", "message": "Docker build failed."})
                    continue
                    
                # Step 6: Verify
                await send_step("verifying")
                await send_log("agent", f"Initiating container startup verification on port {analysis.port or 8080}...")
                
                async def verify_logger(source: str, msg: str):
                    await send_log(source, msg)
                    
                verify_success = await verify_container_startup(
                    image_tag=image_tag,
                    port=analysis.port or 8080,
                    env_vars=analysis.env_vars or {},
                    log_callback=verify_logger
                )
                
                if verify_success:
                    await send_step("success")
                    await websocket.send_json({"type": "status", "status": "success", "message": "Pipeline completed successfully!"})
                else:
                    await send_step("failed")
                    await websocket.send_json({"type": "status", "status": "failed", "message": "Container startup verification failed."})

            elif msg_type == "rebuild":
                # Manual rebuild request with custom Dockerfile from user
                custom_dockerfile = data.get("dockerfile")
                custom_port = data.get("port", 8080)
                custom_env_vars = data.get("env_vars", {})
                
                if not active_temp_path or not image_tag:
                    await send_log("agent", "Error: No active project cloned yet. Submit a repo first.")
                    continue
                    
                await send_log("agent", "User triggered manual Re-Build. Building image with updated Dockerfile...")
                
                # Execute Build
                await send_step("building")
                build_success = False
                try:
                    async def docker_logger(source: str, msg: str):
                        await send_log(source, msg)
                    await build_docker_image(active_temp_path, custom_dockerfile, image_tag, docker_logger)
                    build_success = True
                except BuildError as be:
                    await send_log("agent", "Manual build failed. Check error logs.")
                    await send_step("failed")
                    await websocket.send_json({"type": "status", "status": "failed", "message": "Manual build failed."})
                    continue
                except Exception as e:
                    await send_log("agent", f"Error in manual build: {str(e)}")
                    await send_step("failed")
                    await websocket.send_json({"type": "status", "status": "failed", "message": str(e)})
                    continue
                    
                # Execute Verification
                await send_step("verifying")
                await send_log("agent", f"Initiating container startup verification on port {custom_port}...")
                
                async def verify_logger(source: str, msg: str):
                    await send_log(source, msg)
                    
                verify_success = await verify_container_startup(
                    image_tag=image_tag,
                    port=custom_port,
                    env_vars=custom_env_vars,
                    log_callback=verify_logger
                )
                
                if verify_success:
                    await send_step("success")
                    await websocket.send_json({"type": "status", "status": "success", "message": "Manual Re-Build succeeded!"})
                else:
                    await send_step("failed")
                    await websocket.send_json({"type": "status", "status": "failed", "message": "Container verification failed."})
                    
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        # Cleanup cloned repository on socket closure to save disk space
        if active_temp_path and os.path.exists(active_temp_path):
            logger.info(f"Cleaning up repository folder: {active_temp_path}")
            try:
                rmtree_compat(active_temp_path, lambda func, path, exc_info: os.chmod(path, 0o777) or shutil.rmtree(path))
            except Exception as clean_err:
                logger.error(f"Failed to delete repository temp path: {clean_err}")

from fastapi.staticfiles import StaticFiles

if os.path.exists(frontend_dist_path):
    logger.info(f"Serving frontend from {frontend_dist_path}")
    app.mount("/", StaticFiles(directory=frontend_dist_path, html=True), name="static")
elif os.path.exists(static_dir_path):
    logger.info(f"Serving frontend from {static_dir_path}")
    app.mount("/", StaticFiles(directory=static_dir_path, html=True), name="static")
else:
    logger.warning("Frontend static build directory not found. Serving API routes only.")

import os
import docker
import asyncio
import logging
from typing import Callable, Coroutine, List, Dict, Any

logger = logging.getLogger("dockercraft.docker_ops")

class BuildError(Exception):
    """Custom exception raised when docker build fails."""
    def __init__(self, message: str, logs: List[str]):
        super().__init__(message)
        self.logs = logs

def get_docker_client():
    """Attempts to initialize Docker client from environment or default host."""
    try:
        return docker.from_env()
    except Exception as e:
        logger.error(f"Failed to connect to Docker daemon: {e}")
        # On Windows, Docker might be using named pipes. docker.from_env() usually resolves this.
        # But if it fails, we raise a clear explanation.
        raise RuntimeError(
            "Could not connect to the Docker daemon. Please ensure Docker Desktop is running "
            "and active on your system."
        ) from e

async def build_docker_image(
    repo_path: str,
    dockerfile_content: str,
    image_tag: str,
    log_callback: Callable[[str, str], Coroutine[Any, Any, None]]
) -> List[str]:
    """
    Writes the Dockerfile to the repo directory and starts a build.
    Streams logs in real-time over the callback.
    Raises BuildError if compilation fails.
    """
    client = get_docker_client()
    
    # Write the Dockerfile
    dockerfile_path = os.path.join(repo_path, "Dockerfile")
    with open(dockerfile_path, "w", encoding="utf-8") as f:
        f.write(dockerfile_content)
        
    await log_callback("docker", f"Dockerfile written to {dockerfile_path}\nStarting Docker build for tag: {image_tag}...")
    
    build_logs = []
    
    try:
        # Use low-level api.build to stream logs as dictionary chunks
        # rm=True removes intermediate containers on successful build
        stream = client.api.build(
            path=repo_path,
            dockerfile="Dockerfile",
            tag=image_tag,
            rm=True,
            decode=True
        )
        
        # We run the synchronous generator in an executor or execute blocking loop inside async context
        # Since this is standard python generator, we loop over it.
        # To avoid blocking the event loop completely, we can yield control after each line.
        for chunk in stream:
            # A chunk can contain 'stream', 'errorDetail', 'status', etc.
            if "stream" in chunk:
                line = chunk["stream"]
                build_logs.append(line)
                # Stream to frontend
                await log_callback("docker", line.rstrip())
            elif "status" in chunk:
                status = chunk["status"]
                progress = chunk.get("progress", "")
                await log_callback("docker", f"{status} {progress}".rstrip())
            elif "error" in chunk:
                error_msg = chunk["error"]
                error_detail = chunk.get("errorDetail", {})
                await log_callback("docker", f"BUILD ERROR: {error_msg}")
                # Gather all logs for debugging
                raise BuildError(error_msg, build_logs)
                
            # Yield control to the event loop
            await asyncio.sleep(0.001)
            
        await log_callback("docker", f"Successfully built image: {image_tag}")
        return build_logs
        
    except BuildError as be:
        raise be
    except Exception as e:
        logger.error(f"Unexpected build error: {e}")
        await log_callback("docker", f"UNEXPECTED BUILD ERROR: {str(e)}")
        raise BuildError(str(e), build_logs) from e

async def verify_container_startup(
    image_tag: str,
    port: int,
    env_vars: Dict[str, str],
    log_callback: Callable[[str, str], Coroutine[Any, Any, None]]
) -> bool:
    """
    Spins up the built container in detached mode, maps the target port, 
    waits 5 seconds while streaming status updates, verifies it stays running,
    collects its startup stdout/stderr logs, and cleans up the container.
    """
    client = get_docker_client()
    container = None
    success = False
    
    await log_callback("agent", f"Launching container for verification: {image_tag}")
    await log_callback("agent", f"Mapping container port {port} to host ephemeral port...")
    
    try:
        # Port bindings: map target port to random high host port
        ports_dict = {f"{port}/tcp": None}
        
        # Start container
        container = client.containers.run(
            image=image_tag,
            detach=True,
            ports=ports_dict,
            environment=env_vars
        )
        
        # Check mapped host port
        container.reload()
        ports_config = container.attrs.get("NetworkSettings", {}).get("Ports", {})
        host_port_info = ports_config.get(f"{port}/tcp")
        
        if host_port_info:
            host_port = host_port_info[0].get("HostPort")
            await log_callback("agent", f"Container running! Mapped to host port: {host_port}")
        else:
            await log_callback("agent", f"Container running in host network mode (no specific port mapping found).")
            
        # Countdown 5 seconds with spinner logs
        for i in range(5, 0, -1):
            await log_callback("agent", f"Verifying container stability... {i}s remaining ⏳")
            await asyncio.sleep(1)
            
        # Inspect status
        container.reload()
        status = container.status
        await log_callback("agent", f"Container status after 5s: {status.upper()}")
        
        # Pull startup logs
        startup_logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="ignore")
        await log_callback("docker", "=== Container Boot Logs ===")
        for line in startup_logs.splitlines():
            await log_callback("docker", f"[container] {line}")
        await log_callback("docker", "===========================")
        
        if status.lower() in ("running", "exited") and "error" not in startup_logs.lower():
            # If status is running, it's a success. If it was short-lived but completed with no error (e.g. CLI tool task), we accept.
            # Usually we expect a web server to stay running.
            if status.lower() == "running":
                await log_callback("agent", "Container verification SUCCEEDED! Container is active and stable.")
                success = True
            else:
                await log_callback("agent", "Container exited immediately. Testing failed.")
                success = False
        else:
            await log_callback("agent", f"Container verification FAILED. Container status is: {status}")
            success = False
            
    except Exception as e:
        logger.error(f"Container verification failed: {e}")
        await log_callback("agent", f"VERIFICATION ERROR: {str(e)}")
        success = False
        
    finally:
        # Cleanup guarantee
        if container:
            await log_callback("agent", "Cleaning up container resources...")
            try:
                container.stop(timeout=2)
                await log_callback("agent", "Container stopped.")
            except Exception as stop_err:
                logger.debug(f"Stop container error (already stopped?): {stop_err}")
                
            try:
                container.remove()
                await log_callback("agent", "Container deleted.")
            except Exception as rm_err:
                logger.error(f"Remove container error: {rm_err}")
                
    return success

import os
import subprocess
import time
import http.client
import json
import socket
from celery import Celery

# Celery configuration
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND')
app = Celery('tasks', broker=CELERY_BROKER_URL, backend=CELERY_RESULT_BACKEND)

# Firecracker paths
FIRECRACKER_PATH = os.getenv("FIRECRACKER_PATH", "/usr/local/bin/firecracker")
KERNEL_PATH = "/opt/vmlinux-5.10.225"
ROOTFS_TEMPLATE = "/opt/ubuntu-24.04.ext4"

def firecracker_api_request(socket_path, endpoint, data):
    """Send an HTTP request to Firecracker over a UNIX domain socket."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(socket_path)

    conn = http.client.HTTPConnection("localhost", timeout=10)
    conn.sock = sock  # Attach the UNIX socket

    headers = {"Content-Type": "application/json"}
    json_data = json.dumps(data)

    conn.request("PUT", endpoint, body=json_data, headers=headers)
    response = conn.getresponse()

    return response.status, response.read().decode()


@app.task
def run_sandboxed_module(module_code: str, requirements: list):
    """Runs arbitrary user-provided module inside an isolated Firecracker microVM."""

    # Step 1: Create a unique instance directory
    instance_id = f"vm_{int(time.time())}"
    print("Created instance ID:", instance_id)
    instance_dir = f"/var/lib/firecracker/vms/{instance_id}"
    os.makedirs(instance_dir, exist_ok=True)

    # Step 2: Copy and configure a new root filesystem for the microVM
    rootfs_path = f"{instance_dir}/rootfs.ext4"
    subprocess.run(["cp", ROOTFS_TEMPLATE, rootfs_path])

    # Step 3: Start Firecracker microVM
    api_socket = f"/tmp/{instance_id}.socket"
    print(f"Starting Firecracker with API socket: {api_socket}")

    firecracker_process = subprocess.Popen(
        [FIRECRACKER_PATH, "--api-sock", api_socket, "--config-file", "/opt/firecracker-config.json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    time.sleep(1)  # Give Firecracker time to start

    # Step 4: Wait for Firecracker to be ready
    def wait_for_firecracker(api_socket, timeout=5):
        """Wait for Firecracker socket to appear before making API requests."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if os.path.exists(api_socket):
                return True
            time.sleep(0.5)
        return False

    if not wait_for_firecracker(api_socket):
        raise RuntimeError(f"Firecracker API socket {api_socket} did not appear in time.")

    # Step 6: Inject the module code and dependencies
    module_path = f"{instance_dir}/module.py"
    requirements_path = f"{instance_dir}/requirements.txt"

    with open(module_path, "w") as f:
        f.write(module_code)

    with open(requirements_path, "w") as f:
        f.write("\n".join(requirements))

    # Step 7: Install dependencies inside the Firecracker VM using `uv`
    print(f"running in {instance_dir} with {requirements_path} and module {module_path}")
    subprocess.run(["ls", f"{instance_dir}/opt"])
    # subprocess.run([
    #     "chroot", instance_dir, "/bin/sh", "-c",
    #     f"uv pip install -r {requirements_path} && python3 {module_path}"
    # ])

    # Step 8: Cleanup
    firecracker_process.terminate()
    #subprocess.run(["rm", "-rf", instance_dir])

    return "Execution completed inside Firecracker VM"
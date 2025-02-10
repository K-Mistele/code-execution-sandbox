from tasks import run_sandboxed_module

module_code = "print('Hello from Firecracker VM!')"
requirements = ["numpy"]
run_sandboxed_module.delay(module_code, requirements)
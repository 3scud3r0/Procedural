"""Run a project, optionally using a killable process for a wall-clock bound."""

import multiprocessing
from .vm import VirtualMachine, Limits
from .errors import Diagnostic
from .geometry import svg, png


def execute_project(project, limits=None, trace=False, preview=True):
    limits = limits or Limits()
    vm = None
    try:
        program, modules = project.compile()
        vm = VirtualMachine(project.seed, limits, modules, trace)
        vm.execute(program)
        vm.artifacts.emit("scene.json", vm.scene.to_dict())
        if preview and vm.scene.objects:
            vm.artifacts.emit("scene.svg", svg(vm.scene.to_dict()))
            vm.artifacts.emit("scene.png", png(vm.scene.to_dict()))
        if trace:
            vm.artifacts.emit("trace.json", vm.trace)
        return {
            "ok": True,
            "report": vm.report(),
            "files": vm.artifacts.files,
            "program_hash": program.digest,
            "module_hashes": {name: p.digest for name, p in sorted(modules.items())},
        }
    except Exception as error:
        diagnostic = (
            error if isinstance(error, Diagnostic) else Diagnostic(type(error).__name__, str(error))
        )
        return {
            "ok": False,
            "error": diagnostic.to_dict(),
            "report": vm.report() if vm else {},
            "files": {},
        }


def _worker(sender, project, limits, trace, preview):
    try:
        sender.send(execute_project(project, limits, trace, preview))
    finally:
        sender.close()


def run_isolated(project, limits=None, trace=False, preview=True, wall_seconds=None):
    """Hard process termination bounds capabilities as well as VM instructions.

    This does not configure filesystem/network sandboxing or OS memory limits.
    Only built-in capabilities are exposed by the PCL interpreter.
    """
    limits = limits or Limits()
    timeout = limits.seconds + 3 if wall_seconds is None else float(wall_seconds)
    if timeout <= 0 or timeout > 3600:
        raise ValueError("wall_seconds must be in (0, 3600]")
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_worker, args=(sender, project, limits, trace, preview))
    process.start()
    sender.close()
    try:
        if receiver.poll(timeout):
            try:
                result = receiver.recv()
            except EOFError:
                return {
                    "ok": False,
                    "error": Diagnostic("PROCESS", "worker exited without a result").to_dict(),
                    "report": {},
                    "files": {},
                }
            return result
        return {
            "ok": False,
            "error": Diagnostic("WALL_LIMIT", f"worker exceeded {timeout} seconds").to_dict(),
            "report": {},
            "files": {},
        }
    finally:
        receiver.close()
        process.join(timeout=0.2)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join()

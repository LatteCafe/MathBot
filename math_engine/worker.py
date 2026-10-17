"""Worker process entry point: ``python -m math_engine.worker``.

Reads one JSON request from stdin, writes one JSON response to stdout. Running each calculation in
a separate process lets the bot kill it on timeout (SymPy cannot be interrupted safely in a thread)
and lets us cap its memory. Limits are applied BEFORE SymPy is imported.
"""
import json
import os
import sys
import traceback


def _apply_limits() -> None:
    try:
        import resource  # POSIX only; on Windows only the wall-clock timeout applies
    except ImportError:
        return
    mem_mb = int(os.environ.get("MATH_MEMORY_LIMIT_MB", "0") or 0)
    if mem_mb > 0:
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024,) * 2)
    cpu = int(os.environ.get("MATH_CPU_LIMIT_SECONDS", "0") or 0)
    if cpu > 0:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))


_apply_limits()

from dataclasses import asdict  # noqa: E402

from math_engine import operations  # noqa: E402  (deliberately imported after limits are set)
from math_engine.errors import InputError  # noqa: E402


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
        result = operations.run(payload["op"], payload["args"], payload.get("max_input_length", 200))
        out = {"ok": True, "result": asdict(result)}
    except InputError as exc:
        out = {"ok": False, "error_type": "input", "message": str(exc)}
    except MemoryError:
        out = {"ok": False, "error_type": "internal", "message": "The calculation ran out of memory."}
    except RecursionError:
        out = {"ok": False, "error_type": "internal", "message": "The expression is too deeply nested to compute."}
    except Exception as exc:  # noqa: BLE001 - last line of defence; details go to stderr (the bot's log)
        traceback.print_exc(file=sys.stderr)
        out = {"ok": False, "error_type": "internal", "message": f"The calculation failed ({type(exc).__name__})."}
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()

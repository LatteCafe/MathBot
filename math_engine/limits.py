"""Resource limits for worker processes. Must be applied BEFORE importing heavy libraries."""
import os


def apply_limits() -> None:
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

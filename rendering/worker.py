"""Rendering worker: ``python -m rendering.worker`` (same JSON protocol as math_engine.worker)."""
import base64
import json
import sys
import traceback

from math_engine.limits import apply_limits

apply_limits()  # before matplotlib is imported

from math_engine.errors import InputError  # noqa: E402
from rendering.draw import render_png  # noqa: E402
from rendering.parse import parse_latex  # noqa: E402


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
        segments = parse_latex(payload["latex"], payload["max_length"])
        png = render_png(segments, fontsize=payload["fontsize"], dpi=payload["dpi"])
        out = {"ok": True, "result": {"png": base64.b64encode(png).decode("ascii")}}
    except InputError as exc:
        out = {"ok": False, "error_type": "input", "message": str(exc)}
    except MemoryError:
        out = {"ok": False, "error_type": "internal", "message": "Rendering ran out of memory."}
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        out = {"ok": False, "error_type": "internal", "message": f"Rendering failed ({type(exc).__name__})."}
    sys.stdout.write(json.dumps(out))


if __name__ == "__main__":
    main()

"""Private binary IPC. Import and execute trusted upstream code only in this process."""

import argparse
import contextlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from animecinemavfi.core.errors import OutOfMemoryError
from animecinemavfi.interpolation.model_loader import load_model
from animecinemavfi.interpolation.worker_runtime import MAX_TIMESTEPS, TensorPairCache
from animecinemavfi.utils.process import read_exact, write_all


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    output, source = sys.stdout.buffer, sys.stdin.buffer

    def reply(data: dict[str, Any]) -> None:
        write_all(output, (json.dumps(data) + "\n").encode())
        output.flush()

    try:
        with contextlib.redirect_stdout(sys.stderr):
            model = load_model(args.model, args.repository, args.device, args.version)
        reply({"status": "ok", "version": model.version})
        cache = TensorPairCache(model, args.device)
        try:
            while line := source.readline(65536):
                try:
                    command = json.loads(line)
                    with contextlib.redirect_stdout(sys.stderr):
                        if command["op"] == "pair":
                            width, height = int(command["width"]), int(command["height"])
                            if not 1 <= width <= 16384 or not 1 <= height <= 16384:
                                raise ValueError("Invalid dimensions")
                            size = width * height * 3
                            cache.set_pair(
                                read_exact(source, size), read_exact(source, size), width, height
                            )
                            reply({"status": "ok"})
                        elif command["op"] == "infer_many":
                            times, scale = command["timesteps"], float(command["scale"])
                            if not isinstance(times, list) or not 1 <= len(times) <= MAX_TIMESTEPS:
                                raise ValueError("Invalid batch size")
                            if scale not in {1.0, 0.5, 0.25} or any(
                                not 0 < float(t) < 1 for t in times
                            ):
                                raise ValueError("Invalid timestep/scale")
                            # Stream frames; OOM ends request and host retries only remaining times.
                            for index, timestep in enumerate(times):
                                data = cache.infer(float(timestep), scale)
                                reply({"status": "ok", "index": index})
                                write_all(output, data)
                                output.flush()
                        elif command["op"] == "stats":
                            reply({"status": "ok", **cache.statistics()})
                        else:
                            raise ValueError("Unknown operation")
                except OutOfMemoryError as exc:
                    reply({"status": "error", "kind": "oom", "message": str(exc)})
                except Exception as exc:
                    traceback.print_exc(file=sys.stderr)
                    reply({"status": "error", "kind": "inference", "message": str(exc)})
        finally:
            cache.close()
        return 0
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        reply({"status": "error", "kind": "load", "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

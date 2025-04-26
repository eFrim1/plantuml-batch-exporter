from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import zlib
from contextlib import contextmanager
from typing import Iterator, Tuple, Optional

import requests


# Docker helpers

@contextmanager
def docker_plantuml(image: str, port: int) -> Iterator[str]:
    """Run *image* detached mapping 8080→*port*; yield base URL until exit."""
    if not shutil.which("docker"):
        raise RuntimeError("Docker executable not found in PATH – install Docker or drop --docker.")

    print(f"🚢 Starting PlantUML container {image} on port {port}…", flush=True)
    cid = subprocess.check_output([
        "docker", "run", "-d", "--rm", "-p", f"{port}:8080", image
    ], text=True).strip()

    try:
        _wait_for_server(port)
        yield f"http://localhost:{port}"
    finally:
        print("🛑 Stopping container…", flush=True)
        subprocess.call(["docker", "stop", cid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_for_server(port: int, timeout: int = 60) -> None:
    tiny = "@startuml\n@enduml\n"
    code = plantuml_encode(tiny)
    url = f"http://localhost:{port}/png/{code}"
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code in (200, 400):
                print("✅ PlantUML server is up.")
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(1.5)
    raise RuntimeError("Timed out waiting for local PlantUML server to start.")


# Source parsing
_START_RE = re.compile(r"@startuml(?:\s+([^\s]+))?", re.IGNORECASE)
_END_DIRECTIVE = "@enduml"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def iter_diagrams(text: str) -> Iterator[Tuple[str, str]]:
    lines = text.splitlines()
    i, count = 0, 1
    while i < len(lines):
        m = _START_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        raw = m.group(1) or f"diagram_{count:02}"
        count += 1
        name = re.sub(r"[^\w\-_.]", "_", raw)
        buf = [lines[i]]
        i += 1
        while i < len(lines) and _END_DIRECTIVE not in lines[i]:
            buf.append(lines[i])
            i += 1
        if i < len(lines):
            buf.append(lines[i])
        yield name, "\n".join(buf) + "\n"
        i += 1


# Stand‑alone PlantUML encoder (no external package)
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"

def _enc6(b: int) -> str:
    return _ALPHABET[b & 0x3F]

def _encode_bytes(data: bytes) -> str:
    out = []
    for i in range(0, len(data), 3):
        b1 = data[i]
        b2 = data[i + 1] if i + 1 < len(data) else 0
        b3 = data[i + 2] if i + 2 < len(data) else 0
        out.append(_enc6(b1 >> 2))
        out.append(_enc6(((b1 & 0x3) << 4) | (b2 >> 4)))
        out.append(_enc6(((b2 & 0xF) << 2) | (b3 >> 6)))
        out.append(_enc6(b3 & 0x3F))
    return "".join(out)

def plantuml_encode(text: str) -> str:
    raw = text.encode()
    comp = zlib.compress(raw, 9)
    return _encode_bytes(comp[2:-4])  # strip zlib header+checksum


# HTTP helpers
_HEADERS = {
    "Content-Type": "text/plain; charset=utf-8",
    "Accept": "image/png",
    "User-Agent": "batch_export/3.1",
}

def _is_png(resp: requests.Response) -> bool:
    return resp.content.startswith(_PNG_MAGIC)

def _export_post(diagram: str, base: str) -> Optional[bytes]:
    r = requests.post(base + "/png", data=diagram.encode(), headers=_HEADERS, timeout=30)
    return r.content if _is_png(r) else None

def _export_get(diagram: str, base: str) -> bytes:
    code = plantuml_encode(diagram)
    r = requests.get(f"{base.rstrip('/')}/png/{code}", headers={"User-Agent": _HEADERS["User-Agent"]}, timeout=30)
    if _is_png(r):
        return r.content
    raise RuntimeError(f"GET failed: HTTP {r.status_code}")

def export_png(diagram: str, base: str, method: str) -> bytes:
    method = method.upper()
    if method == "POST":
        img = _export_post(diagram, base)
        if img is None:
            raise RuntimeError("Server did not return PNG on POST.")
        return img
    if method == "GET":
        return _export_get(diagram, base)
    # AUTO
    return _export_post(diagram, base) or _export_get(diagram, base)


def run_exports(source: str, base: str, method: str, out_dir: str) -> None:
    ok = fail = 0
    failures = []
    for name, text in iter_diagrams(source):
        out_path = os.path.join(out_dir, f"{name}.png")
        print(f"▶ {name}: exporting…", end=" ")
        try:
            img = export_png(text, base, method)
            with open(out_path, "wb") as fh:
                fh.write(img)
            print("✓")
            ok += 1
        except Exception as e:
            print("✗", e)
            fail += 1
            failures.append((name, str(e)))
    print(textwrap.dedent(f"""
        Finished. {ok} succeeded, {fail} failed.
        Output dir: {os.path.abspath(out_dir)}
    """))
    if failures:
        print("Failures:")
        for n, err in failures:
            print(f"  • {n}: {err}")
        if fail:
            sys.exit(1)


# CLI
def main():
    ap = argparse.ArgumentParser(description="Batch‑export PlantUML diagrams to PNG, with optional auto‑Docker.")
    ap.add_argument("file", help="PlantUML source file")
    ap.add_argument("-o", "--output", default="./exported", help="Output directory [./exported]")

    ap.add_argument("-s", "--server", help="Existing PlantUML base URL (e.g. http://localhost:8080). If omitted and --docker is not set, defaults to the public server.")
    ap.add_argument("-m", "--method", choices=["AUTO", "POST", "GET"], default="AUTO", help="Transport method")

    ap.add_argument("--docker", action="store_true", help="Launch a local PlantUML server in Docker automatically")
    ap.add_argument("-p", "--port", type=int, default=18080, help="Host port for the Docker container [18080]")
    ap.add_argument("-i", "--image", default="plantuml/plantuml-server", help="Docker image to use [plantuml/plantuml-server]")

    args = ap.parse_args()

    if not os.path.isfile(args.file):
        sys.exit(f"Input file '{args.file}' not found.")
    os.makedirs(args.output, exist_ok=True)

    with open(args.file, encoding="utf-8") as f:
        source = f.read()

    if args.server:
        run_exports(source, args.server.rstrip("/"), args.method, args.output)
    elif args.docker:
        with docker_plantuml(args.image, args.port) as base:
            run_exports(source, base, args.method, args.output)
    else:
        run_exports(source, "https://www.plantuml.com/plantuml", args.method, args.output)


if __name__ == "__main__":
    main()

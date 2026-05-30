#!/usr/bin/env python3
"""CLI test client for BridgeModeler SaaS API.

Usage:
  python test_client.py image ./sample_bridge.jpg
  python test_client.py params '{"bridge_type":"box_girder",...}'
  python test_client.py dialog
"""
from __future__ import annotations
import json
import sys
import httpx

BASE_URL = "http://localhost:8000"


def cmd_image(path: str) -> None:
    with open(path, "rb") as f:
        data = f.read()
    resp = httpx.post(
        f"{BASE_URL}/parse/image",
        files={"file": (path, data, "image/jpeg")},
        timeout=60,
    )
    resp.raise_for_status()
    _print_result(resp.json())


def cmd_params(json_str: str) -> None:
    payload = json.loads(json_str)
    resp = httpx.post(f"{BASE_URL}/parse/params", json=payload, timeout=30)
    resp.raise_for_status()
    _print_result(resp.json())


def cmd_dialog() -> None:
    history: list[dict] = []
    print("=== Bridge Modeler Dialog Mode ===")
    print("Type your answers when prompted. Ctrl+C to exit.\n")

    # Initial turn
    message = "Hello, I want to model a bridge."
    while True:
        resp = httpx.post(
            f"{BASE_URL}/parse/dialog",
            json={"message": message, "history": history},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        validation = data["validation"]

        if validation["passed"]:
            print("\n[PASSED] All parameters collected!")
            print(f"  IFC file: {data.get('ifc_path')}")
            print(f"  IRG: {json.dumps(validation.get('irg'), indent=2)}")
            break

        follow_up = data.get("follow_up_question")
        if not follow_up:
            print("\n[FAILED] Validation failed with no follow-up.")
            print(f"  Errors: {validation.get('errors')}")
            print(f"  Pending: {validation.get('pending_confirmation')}")
            break

        # Append assistant question to history
        history.append({"role": "assistant", "content": follow_up})
        print(f"\nAssistant: {follow_up}")

        user_input = input("You: ").strip()
        if not user_input:
            continue

        history.append({"role": "user", "content": user_input})
        message = user_input


def _print_result(data: dict) -> None:
    validation = data["validation"]
    print(f"passed      : {validation['passed']}")
    if validation.get("errors"):
        print(f"errors      : {validation['errors']}")
    if validation.get("warnings"):
        print(f"warnings    : {validation['warnings']}")
    if validation.get("pending_confirmation"):
        print(f"pending     : {validation['pending_confirmation']}")
    if validation.get("irg"):
        print(f"irg         : {json.dumps(validation['irg'], indent=2)}")
    if data.get("ifc_path"):
        print(f"ifc_path    : {data['ifc_path']}")
    if data.get("follow_up_question"):
        print(f"follow_up   : {data['follow_up_question']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "image":
        if len(sys.argv) < 3:
            print("Usage: python test_client.py image <path>")
            sys.exit(1)
        cmd_image(sys.argv[2])
    elif mode == "params":
        if len(sys.argv) < 3:
            print("Usage: python test_client.py params '<json>'")
            sys.exit(1)
        cmd_params(sys.argv[2])
    elif mode == "dialog":
        cmd_dialog()
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)

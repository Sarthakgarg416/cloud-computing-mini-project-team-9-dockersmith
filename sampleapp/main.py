#!/usr/bin/env python3
"""
Docksmith sample application.
Demonstrates environment variable injection and container isolation.
"""

import os
import platform
import sys

def main():
    greeting = os.environ.get("GREETING", "Hello")
    app_env = os.environ.get("APP_ENV", "unknown")
    name = os.environ.get("NAME", "World")

    print("=" * 50)
    print(f"  Docksmith Sample App")
    print("=" * 50)
    print(f"  {greeting}, {name}!")
    print(f"  Environment : {app_env}")
    print(f"  Python      : {sys.version.split()[0]}")
    print(f"  Platform    : {platform.system()} {platform.machine()}")
    print(f"  Working dir : {os.getcwd()}")
    print()
    print("  Files in /app:")
    try:
        for f in sorted(os.listdir("/app")):
            print(f"    - {f}")
    except Exception as e:
        print(f"    (error listing /app: {e})")
    print("=" * 50)

    # Isolation test: try to write outside container root
    # This should only write inside the container
    test_file = "/tmp/docksmith_isolation_test.txt"
    with open(test_file, "w") as f:
        f.write("This file should NOT appear on the host filesystem.\n")
    print(f"  Wrote isolation test file: {test_file}")
    print("  (This file must NOT appear on the host filesystem)")
    print("=" * 50)

if __name__ == "__main__":
    main()
# modified

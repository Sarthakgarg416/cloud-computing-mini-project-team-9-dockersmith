#!/usr/bin/env python3
"""
Docksmith - A simplified Docker-like build and runtime system.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cmd.cli import main

if __name__ == "__main__":
    main()

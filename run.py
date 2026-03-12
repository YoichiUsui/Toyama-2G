#!/usr/bin/env python
"""
Run script for the Serial Device Communication Test Tool.
Execute this file to launch the application.
"""

import sys
import os

# Add the current directory to the path so imports work correctly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import main

if __name__ == "__main__":
    main()

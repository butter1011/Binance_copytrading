#!/usr/bin/env python3
"""
Run the dashboard separately
"""

import sys
import os
from pathlib import Path

# Add the current directory to Python path
sys.path.append(str(Path(__file__).parent))

from dashboard import app, socketio

if __name__ == "__main__":
    print("Starting dashboard on http://localhost:5000")
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False
    )

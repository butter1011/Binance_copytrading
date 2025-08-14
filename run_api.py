#!/usr/bin/env python3
"""
Run the API server separately
"""

import uvicorn
import sys
import os
from pathlib import Path

# Add the current directory to Python path
sys.path.append(str(Path(__file__).parent))

# Set test mode environment variables
os.environ["TEST_MODE"] = "true"
os.environ["SKIP_CREDENTIAL_VALIDATION"] = "true"

from api import app

if __name__ == "__main__":
    print("Starting API server on http://localhost:8000 (TEST MODE)")
    print("Credential validation is disabled for testing")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True
    )

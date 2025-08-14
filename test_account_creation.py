#!/usr/bin/env python3
"""
Test script to create an account with test credentials
"""

import requests
import json

def test_account_creation():
    """Test account creation with test credentials"""
    api_base_url = "http://127.0.0.1:8000"
    api_token = "your-secret-token"
    
    print("Testing account creation...")
    print(f"API Base URL: {api_base_url}")
    print("-" * 50)
    
    # Test data
    test_data = {
        "name": "Test Master Account",
        "api_key": "test_api_key_12345",
        "secret_key": "test_secret_key_12345",
        "is_master": True,
        "leverage": 10,
        "risk_percentage": 10.0
    }
    
    try:
        headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
        response = requests.post(f"{api_base_url}/accounts", headers=headers, json=test_data, timeout=15)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            print("✅ Account created successfully!")
        elif response.status_code == 400:
            print("❌ Invalid API credentials (expected in test mode)")
        elif response.status_code == 500:
            print("❌ Server error")
        else:
            print(f"❌ Unexpected status code: {response.status_code}")
            
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection error: {e}")
    except requests.exceptions.Timeout as e:
        print(f"❌ Timeout error: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    test_account_creation()

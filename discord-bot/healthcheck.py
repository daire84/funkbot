#!/usr/bin/env python3
import sys
import os
import mysql.connector

def check_health():
    """Simple health check for Docker"""
    try:
        # Check if we can connect to database
        db_config = {
            'host': os.getenv('DB_HOST', 'mariadb'),
            'database': os.getenv('DB_NAME', 'funkbot_db'),
            'user': os.getenv('DB_USER', 'funkbot_user'),
            'password': os.getenv('DB_PASSWORD'),
            'connection_timeout': 5
        }
        
        connection = mysql.connector.connect(**db_config)
        connection.close()
        
        print("Health check passed")
        return True
    except Exception as e:
        print(f"Health check failed: {e}")
        return False

if __name__ == "__main__":
    if check_health():
        sys.exit(0)
    else:
        sys.exit(1)

import subprocess
import webbrowser
import time
import sys
import os
import socket

def is_port_in_use(port):
    """Check if Streamlit is already running on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def main():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)

    # Don't start if already running
    if is_port_in_use(8501):
        subprocess.Popen(['cmd', '/c', 'start', 'http://localhost:8501'])
        return

    # Start Streamlit once
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.headless", "true",
         "--browser.gatherUsageStats", "false",
         "--server.port", "8501",
         "--browser.serverAddress", "localhost"],
        cwd=app_dir
    )

    # Wait for Streamlit to be fully ready
    print("Starting AI Router...")
    for _ in range(10):
        time.sleep(1)
        if is_port_in_use(8501):
            break

    # Extra second for Streamlit to finish initializing
    time.sleep(2)

    # Open browser exactly once
    subprocess.Popen(['cmd', '/c', 'start', 'http://localhost:8501'])
    print("AI Router is running. Close this window to stop.")
    process.wait()

if __name__ == "__main__":
    main()
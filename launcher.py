import subprocess
import webbrowser
import time
import sys
import os

def main():
    # Set working directory to app location
    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)
    
    # Start Streamlit
    process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py",
         "--server.headless", "true",
         "--browser.gatherUsageStats", "false",
         "--server.port", "8501"],
        cwd=app_dir
    )
    
    # Wait for Streamlit to start
    print("Starting AI Router...")
    time.sleep(3)
    
    # Open browser
    webbrowser.open("http://localhost:8501")
    
    print("AI Router is running.")
    print("Close this window to stop the app.")
    
    # Keep running until closed
    process.wait()

if __name__ == "__main__":
    main()
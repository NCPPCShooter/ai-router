#!/bin/bash
# launch_cindy.sh — Start Cindy's Job Board on port 8502
# Run once; accessible at http://192.168.1.35:8502

cd "$(dirname "$0")"

# Activate virtual environment
source venv/bin/activate

# Start Streamlit bound to all network interfaces
streamlit run cindy_app.py \
    --server.port 8502 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false

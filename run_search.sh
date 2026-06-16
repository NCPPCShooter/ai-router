#!/bin/bash
# run_search.sh — cron wrapper for daily job search

cd /home/kirk-keller/ai-router

# Load environment variables
while IFS='=' read -r key value; do
    export "$key=$value"
done < /home/kirk-keller/ai-router/.env

# Activate venv and run
source /home/kirk-keller/ai-router/venv/bin/activate
python scheduled_search.py

#!/bin/bash
# Build script for Render deployment
# Ensures all Python dependencies are installed before starting the app
set -e
pip install --upgrade pip
pip install -r requirements.txt

#!/bin/bash
# Start the Flask web application server

echo "Starting Nifty Options Backtest Web App..."
echo ""

# Check if virtual environment exists and activate it
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Check if Flask is installed
if ! python3 -c "import flask" 2>/dev/null; then
    echo "Flask is not installed."
    echo ""
    
    if [ -d "venv" ]; then
        echo "Installing Flask in virtual environment..."
        pip install Flask
    else
        echo "Please install Flask using one of these methods:"
        echo ""
        echo "1. Using virtual environment (recommended):"
        echo "   python3 -m venv venv"
        echo "   source venv/bin/activate"
        echo "   pip install Flask"
        echo ""
        echo "2. Using --user flag:"
        echo "   python3 -m pip install --user Flask"
        echo ""
        echo "3. Using --break-system-packages (if needed):"
        echo "   python3 -m pip install Flask --break-system-packages"
        echo ""
        exit 1
    fi
fi

echo "Starting server on http://localhost:3003"
echo "Press Ctrl+C to stop the server"
echo ""

python3 app.py


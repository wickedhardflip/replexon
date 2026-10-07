#!/bin/bash
python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:9847/health', timeout=5)" 2>/dev/null

#!/bin/sh
# ==============================================================================
# Entrypoint script for API 3 - EXPORT Automation System Container
# Enforces TEST_MODE safety checks and initializes datastores before WSGI start
# ==============================================================================

set -e

echo "============================================================"
echo "    API 3 - EXPORT AUTOMATION SYSTEM (PRODUCTION WSGI)      "
echo "============================================================"
echo "Safety Mode        : TEST_MODE=${TEST_MODE:-true}"
echo "Listening Port     : ${PORT:-5000}"
echo "Process Model      : Gunicorn (1 worker, 4 threads)"
echo "Target Keyword     : ${SEARCH_KEYWORD:-Singing Bowls}"
echo "Daily Send Ceiling : ${DAILY_SEND_LIMIT:-10}"
echo "============================================================"

# Enforce safety guard: Warn if TEST_MODE is not true
if [ "${TEST_MODE}" != "true" ]; then
    echo "WARNING: LIVE SENDING IS RESTRICTED. ENSURE PROPER AUTHORIZATION."
fi

# Execute custom command if provided, else launch default Gunicorn WSGI server
if [ $# -gt 0 ]; then
    exec "$@"
else
    exec gunicorn \
        --bind 0.0.0.0:${PORT:-5000} \
        --workers 1 \
        --threads 4 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile - \
        web_app:app
fi

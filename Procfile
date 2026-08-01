web: gunicorn --worker-class uvicorn.workers.UvicornWorker --workers 4 --timeout 60 --bind 0.0.0.0:${PORT:-4241} main:app

# Gunicorn automatically loads gunicorn.conf.py from the working directory.
# Keep this in-repo because the existing Render service has a dashboard-level
# start command (`gunicorn commercial_app:app`) that overrides render.yaml.
timeout = 300
graceful_timeout = 30
workers = 1

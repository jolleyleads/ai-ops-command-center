"""Keep customer requests responsive while provider operations wait on I/O."""
workers = 1
worker_class = "gthread"
threads = 4
timeout = 120

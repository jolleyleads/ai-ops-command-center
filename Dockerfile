FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
# Smart Search + evidence verification can legitimately exceed Gunicorn's
# 30-second default. Keep the request bounded by the acceptance harness while
# allowing the worker to finish instead of being killed mid-verification.
CMD ["gunicorn", "--timeout", "300", "universal_app:app"]

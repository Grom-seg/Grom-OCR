FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -r requirements.txt
CMD ["py", "-3", "tools/run_benchmark_suite.py", "--mode", "standard"]

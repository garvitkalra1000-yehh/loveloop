FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Set default port and expose
ENV PORT=8000
EXPOSE 8000

CMD ["python", "web_app.py"]

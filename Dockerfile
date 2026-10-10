# A small official Python image, so the tool runs the same on any machine with Docker.
FROM python:3.12-slim

WORKDIR /app

# Installed before the code is copied, so changing the code doesn't redo the install.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Bytecode files aren't needed in a container, and unbuffered output shows up in the terminal straight away.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

EXPOSE 5000

# Runs the dashboard by default; any other command, like python src/main.py --attack, can follow the image name.
CMD ["python", "src/dashboard.py", "--host", "0.0.0.0", "--port", "5000"]

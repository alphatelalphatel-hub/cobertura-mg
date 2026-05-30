FROM python:3.11-slim
WORKDIR /app
RUN pip install flask --no-cache-dir
COPY servidor_cobertura.py .
COPY cobertura_mg.json .
EXPOSE 5000
CMD ["python", "servidor_cobertura.py"]

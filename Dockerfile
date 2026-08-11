FROM python:3.14-slim

### Execution Server
WORKDIR /app
COPY ./image /app
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

###
EXPOSE 9999
CMD ["python", "execution_server.py"]

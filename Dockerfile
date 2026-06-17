FROM cae-artifactory.jpl.nasa.gov:17001/python:3.7.2

MAINTAINER Hongman Kim <hongman.kim@jpl.nasa.gov>

### Execution Server
WORKDIR /app
COPY ./image /app
RUN pip install --trusted-host cae-artifactory.jpl.nasa.gov  -r requirements.txt

###
EXPOSE 9999
CMD ["python", "execution_server.py"]

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY hisense_remote ./hisense_remote
ENV HISENSE_REMOTE_HOME=/data
VOLUME ["/data"]
EXPOSE 8765
ENTRYPOINT ["python", "-m", "hisense_remote"]
CMD ["serve"]

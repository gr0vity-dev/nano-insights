FROM python:3
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
RUN mv config_gather_stats.json.docker config_gather_stats.json
CMD [ "python", "./gather_stats_kibana.py" ]
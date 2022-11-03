import json
import websocket
import threading
from src.stats_logger import WebsocketConfirmationStats, WebsocketVoteStats, WebsocketStartedElectionStats
import time
import ssl


class RepeatedTimer(object):

    def __init__(self, interval, function, *args, **kwargs):
        self._timer = None
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.is_running = False
        self.start()

    def _run(self):
        self.is_running = False
        self.start()
        self.function(*self.args, **self.kwargs)

    def start(self):
        if not self.is_running:
            self._timer = threading.Timer(self.interval, self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        self._timer.cancel()
        self.is_running = False


class SimpleWs:

    def __init__(self,
                 ws_url: str,
                 node_name: str,
                 node_version: str,
                 ws_topics=["confirmation"]):

        self.ws_url = ws_url
        self.is_closed = False
        self.write_stats = False
        self.node_name = node_name
        self.ws_topics = ws_topics
        self.start_timer = time.time()
        if "confirmation" in ws_topics:
            self.stats_conf = WebsocketConfirmationStats(
                node_name, node_version)
        #if "vote" in ws_topics: self.stats_vote = WebsocketVoteStats()
        if "vote" in ws_topics:
            self.stats_vote = WebsocketVoteStats(node_name, node_version)
        if "started_election" in ws_topics:
            self.stats_started_election = WebsocketStartedElectionStats(
                node_name, node_version)

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_message=lambda ws, msg: self.on_message(msg),
            on_error=lambda ws, msg: self.on_error(msg),
            on_close=lambda ws, msg, error: self.on_close(ws, msg, error),
            on_open=lambda ws: self.on_open())
        # self.ws.run_forever()
        if ws_url.startswith("wss"):
            self.wst = threading.Thread(
                target=self.ws.run_forever,
                kwargs={"sslopt": {
                    "cert_reqs": ssl.CERT_NONE
                }},
                daemon=True)
        else:
            self.wst = threading.Thread(target=self.ws.run_forever,
                                        daemon=True)
        #self.wst.daemon = True
        self.wst.start()

    def topic_selector(self, message):
        json_msg = json.loads(message)

        if json_msg["topic"] == "confirmation":
            self.p_confirmation(json_msg)
        elif json_msg["topic"] == "vote":
            self.p_vote(json_msg)
        elif json_msg["topic"] == "started_election":
            self.p_started_election(json_msg)
        #     self.p_stopped_election(json_msg)
        # elif json_msg["topic"] == "new_unconfirmed_block":
        #     self.p_new_unconfirmed_block(json_msg)
        # elif json_msg["topic"] == "stopped_election":
        #     self.p_stopped_election(json_msg)
        else:
            pass
            #print("select else")

    def p_vote(self, json_msg):
        self.stats_vote.update_vote_count(json_msg)

    def append_votes_to_hash_list(self, hash_list):
        print(">>>>DEBUG", len(hash_list), hash_list[0],
              hash_list[len(hash_list) - 1])
        return self.stats_vote.get_hash_stats_for_list(hash_list)

    def p_started_election(self, json_msg):
        self.stats_started_election.update_election_count(json_msg)

    def log_started_elections(self, run_id, log_at_count, write_to_db=False):
        return self.stats_started_election.log_hash_stats(
            run_id, log_at_count, write_to_db=write_to_db)

    def append_election_to_hash_list(self, hash_list):
        print(">>>>DEBUG", len(hash_list), hash_list[0],
              hash_list[len(hash_list) - 1])
        return self.stats_started_election.get_hash_stats_for_list(hash_list)

    def p_confirmation(self, json_msg):

        self.stats_conf.inc_confirmation_counter()
        block_hash = json_msg["message"]["hash"]
        self.stats_conf.receive_hash(block_hash)

    def on_message(self, message):
        self.topic_selector(message)

    def on_error(self, error):
        print(error)

    def on_close(self, ws, msg, error):
        self.ws.close()
        self.is_closed = True
        print(f"### websocket connection closed"
              )  # after { time.time() - self.start_timer} ###")

    def terminate(self):
        print("websocket thread terminating...")
        self.stats_conf.log_stats()
        #self.stats_conf.log_hash_stats()
        #return self.data_collection

    def on_open(self):
        #self.ws.send(json.dumps({"action": "subscribe", "topic": "new_unconfirmed_block"}))
        if "confirmation" in self.ws_topics:
            self.ws.send(
                json.dumps({
                    "action": "subscribe",
                    "topic": "confirmation",
                    "options": {
                        "include_election_info": "false",
                        "include_block": "true"
                    }
                }))

        if "vote" in self.ws_topics:
            self.ws.send(
                json.dumps({
                    "action": "subscribe",
                    "topic": "vote",
                    "options": {
                        "include_replays": "true",
                        "include_indeterminate": "true"
                    }
                }))

        if "started_election" in self.ws_topics:
            self.ws.send(
                json.dumps({
                    "action": "subscribe",
                    "topic": "started_election"
                }))

        # ws.send(json.dumps({"action": "subscribe", "topic": "confirmation", "options": {"include_election_info": "true"}}))
        print("### websocket connection opened ###")

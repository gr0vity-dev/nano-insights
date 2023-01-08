#!./venv_nano_stats/bin/python

from socket import timeout
from time import time
import copy
import time
from time import strftime, gmtime
from datetime import datetime
import argparse
import threading
import ctypes
import json
import traceback
import aiohttp
import asyncio
from src.simple_ws import SimpleWs
import secrets

#nodes_stat returns a list with 1 stat for all nodes
#node_stats retruns a dict with all stats for 1 node
#nodes_stats retruns a list with all stats for all nodes

#ws0 = SimpleWs("ws://192.168.178.88:47000", "nl_gen", "V24DB20", "vote")
# ws1 = SimpleWs("ws://192.168.178.88:47001", "nl_pr1", "V24DB20", "vote")
# ws2 = SimpleWs("ws://192.168.178.88:47002", "nl_pr2", "V24DB20", "vote")
# ws3 = SimpleWs("ws://192.168.178.88:47003", "nl_pr3", "V24DB20", "vote")

ws1 = SimpleWs("ws://192.168.178.88:47001", "nl_pr1", "V24DB20",
               "started_election")
ws2 = SimpleWs("ws://192.168.178.88:47002", "nl_pr2", "V24DB20",
               "started_election")
ws3 = SimpleWs("ws://192.168.178.88:47003", "nl_pr3", "V24DB20",
               "started_election")
run_id = secrets.token_hex(10)


def wait_mod(interval=5):
    #default : sleep until time is either XX:XX:00 or XX:XX:05
    time.sleep(0.199)
    sleep_counter = 0
    while True:
        sleep_counter = sleep_counter + 1
        if time.time() % interval > 0 and time.time() % 5 < 0.2:
            break
        time.sleep(0.1)
        #libc.usleep(100000)


class ConfigReadWrite():

    def write_json(self, path, json_dict):
        with open(path, "w") as f:
            json.dump(json_dict, f)

    def append_json(self, path, json_dict):
        with open(path, "a") as f:
            json.dump(json_dict, f)
            f.write('\n')

    def read_json(self, path):
        with open(path, "r") as f:
            return json.load(f)


class ParallelPost():

    def __init__(self):
        self.loop = self.get_or_create_eventloop()
        self.aio_conn = self.set_aio_connection()
        self.aio_results = []

    def get_or_create_eventloop(self):
        try:
            return asyncio.get_event_loop()
        except RuntimeError as ex:
            if "There is no current event loop in thread" in str(ex):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                return asyncio.get_event_loop()

    async def set_aio_connection(self):
        # 0.1s for 1million connections
        if self.aio_conn is None:
            self.aio_conn = aiohttp.TCPConnector(limit_per_host=50,
                                                 limit=50,
                                                 verify_ssl=False,
                                                 force_close=True)

    def exec_parallel_post(self, post_requests, sync=False):
        res = []
        errors = self.get_new_aio_error()
        self.loop.run_until_complete(
            self.post_requests_parallel(post_requests,
                                        sync=sync,
                                        aio_results=res,
                                        aio_errors=errors,
                                        include_request=True))
        if errors["error_count"] > 0: print(json.dumps(errors, indent=4))
        return res

    def get_new_aio_error(self):
        return {"error_count": 0, "last_request": "", "last_error": ""}

    async def post_requests_parallel(self,
                                     data,
                                     sync=True,
                                     aio_results=[],
                                     include_request=False,
                                     ignore_errors=[],
                                     aio_errors=None):
        #data = {"username|password" : [{"url" : "http://...", "request" : {"json_object"}}, {"url" : ...} , ...] }
        parallel_requests = 1 if sync else 5
        semaphore = asyncio.Semaphore(parallel_requests)
        for auth, requests in data.items():
            username, password = auth.split("|")
            auth = aiohttp.BasicAuth(username, password)
            async with aiohttp.ClientSession(auth=auth) as session:

                async def do_req(el, aio_errors):
                    async with semaphore:
                        try:
                            async with session.post(url=el["url"],
                                                    json=el["request"],
                                                    ssl=False) as response:
                                obj = {
                                    "response": json.loads(await
                                                           response.read())
                                }
                                if include_request:
                                    obj["request"] = el["request"]
                                    obj["url"] = el["url"]
                                if obj is None:
                                    aio_errors["error_count"] = aio_errors[
                                        "error_count"] + 1
                                    aio_errors[
                                        "last_error"] = f'Request failed: {el}'
                                if "error" in obj:
                                    if not obj["error"] in ignore_errors:
                                        aio_errors["error_count"] = aio_errors[
                                            "error_count"] + 1
                                        aio_errors["last_error"] = obj["error"]
                                        aio_errors["last_request"] = el
                                aio_results.append(obj)
                        except:
                            print("Request failed", el)

                aio_errors = self.get_new_aio_error(
                ) if aio_errors != self.get_new_aio_error() else aio_errors
                await asyncio.gather(*(do_req(el, aio_errors)
                                       for el in requests))


class NanoStats():

    config = None

    def __init__(self):
        self.ppost = ParallelPost()
        self.conf_rw = ConfigReadWrite()
        self.conf_path = "./config_gather_stats.json"
        self.rpcs = self.get_rpcs()

    def read_config(self):
        if self.config is None:
            self.config = self.conf_rw.read_json(self.conf_path)
        return self.config

    def get_rpcs(self):
        json_config = self.read_config()
        return json_config["nodes"]

    def get_source(self):
        json_config = self.read_config()
        json_config["source"] = json_config.get("source") if json_config.get(
            "source") is not None else "default"
        return json_config["source"]

    def get_rpcs_pr(self, name_only=False):
        rpcs = self.get_rpcs()
        prs = []
        for rpc in rpcs:
            if "is_pr" in rpc and rpc["is_pr"]:
                if name_only: prs.append(rpc["name"])
                else: prs.append(rpc)
        return prs

    def get_req_object(self, url, request):
        return {"url": url, "request": request}

    def extract_raw_merge_stats(self, node_stats, rpc_res):
        self.add_key_if_not_exists(node_stats, "delta", {})
        if rpc_res is not None:
            if rpc_res is not None and "entries" in rpc_res:
                for stat in rpc_res["entries"]:
                    node_stats["delta"][
                        f'stats_{stat["type"]}_{stat["dir"]}_{stat["detail"]}'] = int(
                            stat["value"])

    def extract_raw_merge_object_stats(self, node_stats, rpc_res):
        for l1 in rpc_res:
            for l2 in rpc_res[l1]:
                if "size" in rpc_res[l1][l2]:
                    node_stats["delta"][f'objectsize_{l1}_{l2}'] = int(
                        rpc_res[l1][l2]["size"])
                    node_stats["delta"][f'objectcount_{l1}_{l2}'] = int(
                        rpc_res[l1][l2]["count"])
                else:
                    for l3 in rpc_res[l1][l2]:
                        if "size" in rpc_res[l1][l2][l3]:
                            node_stats["delta"][
                                f'objectsize_{l1}_{l2}_{l3}'] = int(
                                    rpc_res[l1][l2][l3]["size"])
                            node_stats["delta"][
                                f'objectcount_{l1}_{l2}_{l3}'] = int(
                                    rpc_res[l1][l2][l3]["count"])

    def get_node_name_from_rpc_url(self, url):
        for node in self.get_rpcs():
            if node["rpc_url"] == url: return node["name"]

    def values_to_integer(self, flat_json, skip_keys=[]):
        pop_keys = []
        for key, value in flat_json.items():
            if key in skip_keys: continue
            try:
                flat_json[key] = float(value)
            except:
                pop_keys.append(key)

        for key in pop_keys:
            flat_json.pop(key)
        return flat_json

    def get_nodes_stat_by_key(self, node_stats, key, pr_only=False):
        nodes_stat = {}
        for node_stats_key, node_stats in node_stats.items():
            if pr_only:
                if "_node_name" in node_stats and node_stats[
                        "_node_name"] not in self.get_rpcs_pr(name_only=True):
                    continue
            if key in node_stats: nodes_stat[node_stats_key] = node_stats[key]
        return nodes_stat

    def get_node_count(self, nodes_stats):
        return len(nodes_stats) - 1  #exclude shared stats

    def add_key_if_not_exists(self, dict_l, key, default):
        if key not in dict_l: dict_l[key] = default

    def extend_node_stats_with_delta(self, node_stats, previous_stats):

        for action, stats in node_stats.items():
            if action == "block_count":
                stats[action]["uncemented"] = stats[action]["count"] - stats[
                    action]["cemented"]

    def get_single_request(self, request_responses, action, rpc_url):
        return request_responses[action][rpc_url]

    def get_all_requests(self, request_responses, action):
        sorted_requests = []
        for rpc in self.rpcs:
            sorted_requests.append(request_responses[action][rpc["rpc_url"]])
        return sorted_requests

    def get_overlap_percent(self, union_length, avg_aec_size):
        return round((union_length / max(1, avg_aec_size)) * 100, 2)

    def get_path(self, filename):
        return f"./log/{datetime.now().strftime('%j')}_{filename}"

    def get_keys_as_list(self, nodes_stats):
        return [x for x in nodes_stats.keys()]

    def log_file_kibana(self, nodes_stats):
        day_of_year = datetime.now().strftime('%j')
        filename = f"run_stats_kibana.log"  #prepended by day_of_year
        nodes_stats_copy = copy.deepcopy(nodes_stats)
        node_names = self.get_keys_as_list(nodes_stats)

        #create copy of object to write log without delta object but keep delta to compare it with next iteration
        for i in range(0, self.get_node_count(nodes_stats)):
            if "delta" in nodes_stats[node_names[i]]:
                nodes_stats_copy[node_names[i]].pop("delta")

    #add 1 line per node + 1 line for shared stats
        for node_stats in nodes_stats_copy.values():
            #TODO: ENABLE THIS LINE           #self.conf_rw.append_json(self.get_path(filename), node_stats)
            pass

    def map_aec_content_to_votes(self, hash_set, ws, name):

        hash_list = [x for x in hash_set]
        res_ws = ws.append_votes_to_hash_list(hash_list)
        with open(
                f"./{datetime.now().hour}|{datetime.now().minute}|{datetime.now().second}_{name}_vote_stats.json",
                "w") as f:
            json.dump(res_ws, f)

    def write_overlapping_elections(self, hash_set):
        if hash_set == set():
            print(">>DEBUG", "set empty")
            return
        with open(
                f"./{datetime.now().hour}|{datetime.now().minute}|{datetime.now().second}_overlapping_elections.json",
                "w") as f:
            json.dump(list(hash_set), f)

    def add_websocket_data_to_overlap(self, hash_set):
        if hash_set == set():
            print(">>DEBUG", "set empty")
            return

        hash_list = [x for x in hash_set]
        res_ws1 = ws1.append_votes_to_hash_list(hash_list)
        res_ws2 = ws2.append_votes_to_hash_list(hash_list)
        res_ws3 = ws3.append_votes_to_hash_list(hash_list)
        with open(
                f"./{datetime.now().hour}|{datetime.now().minute}|{datetime.now().second}_ws1_hash_stats.json",
                "w") as f:
            json.dump(res_ws1, f)
        with open(
                f"./{datetime.now().hour}|{datetime.now().minute}|{datetime.now().second}_ws2_hash_stats.json",
                "w") as f:
            json.dump(res_ws2, f)
        with open(
                f"./{datetime.now().hour}|{datetime.now().minute}|{datetime.now().second}_ws3_hash_stats.json",
                "w") as f:
            json.dump(res_ws3, f)

    def map_aec_overlap_to_elections(self, hash_set):
        if hash_set == set():
            print(">>DEBUG", "set empty")
            return

        hash_list = [x for x in hash_set]
        hash_list.append("total_elections")
        res_ws1 = ws1.append_election_to_hash_list(hash_list)
        res_ws2 = ws2.append_election_to_hash_list(hash_list)
        res_ws3 = ws3.append_election_to_hash_list(hash_list)
        with open(
                f"./{datetime.now().hour}|{datetime.now().minute}|{datetime.now().second}_ws1_election_stats.json",
                "w") as f:
            json.dump(res_ws1, f)
        with open(
                f"./{datetime.now().hour}|{datetime.now().minute}|{datetime.now().second}_ws2_election_stats.json",
                "w") as f:
            json.dump(res_ws2, f)
        with open(
                f"./{datetime.now().hour}|{datetime.now().minute}|{datetime.now().second}_ws3_election_stats.json",
                "w") as f:
            json.dump(res_ws3, f)

    def log_started_elections(self):
        print("=" * 64)
        print("=" * 32, run_id)
        print("=" * 64)
        ws1.log_started_elections(run_id)
        ws2.log_started_elections(run_id)
        ws3.log_started_elections(run_id)

    def extend_node_stats_shared_stats(
            self, node_stats, nano_nodes_version,
            timestamp):  #prepare_node_stats step3 (last)
        self.add_key_if_not_exists(node_stats, "shared_stats",
                                   {"_stats_source": self.get_source()})

        node_stats["shared_stats"]["calc_timestamp"] = timestamp
        ##### version #####
        node_stats["shared_stats"][
            "user_nano_nodes_version"] = nano_nodes_version
        #####AEC overlap#######old screenshots

        delta_stats = self.get_nodes_stat_by_key(node_stats, "delta")
        aecs = [stats["aecs"] for stats in delta_stats.values()]
        union = aecs[0]
        aec_avg_size = sum(len(x) for x in aecs) / len(aecs)

        for aec in aecs:
            union = union.intersection(aec)
            union_length = len(union)
        node_stats["shared_stats"][
            "calc_overlap_all_nodes"] = self.get_overlap_percent(
                union_length, aec_avg_size)
        node_stats["shared_stats"]["calc_overlap_all_nodes_abs"] = union_length

        delta_stats_pr = self.get_nodes_stat_by_key(node_stats,
                                                    "delta",
                                                    pr_only=True)
        if len(delta_stats_pr) > 0:
            aecs_pr = [stats["aecs"] for stats in delta_stats_pr.values()]
            union_pr = aecs_pr[0]
            aec_pr_avg_size = sum(len(x) for x in aecs_pr) / len(aecs_pr)

            #AEC overlap for all PRs
            for aec in aecs_pr:
                union_pr = union_pr.intersection(aec)
                union_length = len(union_pr)
            node_stats["shared_stats"][
                "calc_overlap_prs"] = self.get_overlap_percent(
                    union_length, aec_pr_avg_size)
        else:
            print(
                "Config file holds no PRs (is_pr either missing or false on all nodes)"
            )
        self.write_overlapping_elections(union_pr)
        # self.add_websocket_data_to_overlap(union)
        # if union_length == 0:
        #     for count, aec in enumerate(aecs_pr):
        #         if len(aec) == 0: continue
        #         if count == 0: self.map_aec_content_to_votes(aec, ws1, "ws1")
        #         if count == 1: self.map_aec_content_to_votes(aec, ws2, "ws2")
        #         if count == 2: self.map_aec_content_to_votes(aec, ws3, "ws3")

        # #self.map_aec_overlap_to_elections(union)

        max_overlap = 0
        #max AEC overlap of 2 PRs
        for i in range(0, len(aecs)):
            for j in range(i, len(aecs)):
                if i == j: continue  #no need to compare to itself
                overlap_pr_i_j = len(aecs[i].intersection(aecs[j]))
                aec_avg_size_i_j = (len(aecs[i]) + len(aecs[j])) / 2
                node_stats["shared_stats"][
                    f'calc_{i}_{j}_abs'] = overlap_pr_i_j
                node_stats["shared_stats"][
                    f'calc_{i}_{j}_perc'] = self.get_overlap_percent(
                        overlap_pr_i_j, aec_avg_size_i_j)
                max_overlap = max(
                    max_overlap,
                    self.get_overlap_percent(overlap_pr_i_j, aec_avg_size_i_j))
        node_stats["shared_stats"]["calc_overlap_max"] = max_overlap

    def extend_node_stats_all_nodes(self, nodes_stats,
                                    timestamp):  #prepare_node_stats step2
        #for key in node_stats.keys():
        node_stats = [x for x in nodes_stats.values()
                      ]  #returns list of node_stats

        block_count_cemented = self.get_nodes_stat_by_key(
            nodes_stats, "block_count_cemented")
        block_count_count = self.get_nodes_stat_by_key(nodes_stats,
                                                       "block_count_count")
        keys = [x for x in nodes_stats.keys()]  #returns list of node_stats

        for i in range(0, len(nodes_stats)):
            #for i in range(0, len(block_count_cemented)) :
            node_stats[i][f"calc_uncemented"] = round(
                max(block_count_count.values()) -
                block_count_cemented[keys[i]], 2)
            node_stats[i][f"calc_uncemented_node_view"] = round(
                block_count_count[keys[i]] - block_count_cemented[keys[i]], 2)
            node_stats[i][f"calc_sync_block_count"] = round(
                block_count_count[keys[i]] / max(block_count_count.values()) *
                100, 2)
            node_stats[i][f"calc_sync_cemented"] = round(
                block_count_cemented[keys[i]] /
                max(block_count_cemented.values()) * 100, 2)
            node_stats[i][f"calc_percent_cemented"] = round(
                block_count_cemented[keys[i]] /
                max(block_count_count.values()) * 100, 2)
            node_stats[i][f"calc_missing_cemented"] = round(
                max(block_count_cemented.values()) -
                block_count_cemented[keys[i]], 2)
            node_stats[i][f"calc_timestamp"] = timestamp

    def set_node_stats(self, request_responses):  #prepare_node_stats step1
        node_stats = {}
        for action, urls in request_responses.items():
            for url, response in urls.items():
                node_name = self.get_node_name_from_rpc_url(url)
                if node_name not in node_stats:
                    node_stats[node_name] = {
                        "_node_name": node_name,
                        "_stats_source": self.get_source()
                    }
                self.add_key_if_not_exists(node_stats[node_name], "delta", {})

                if action == "stats_counters":
                    self.extract_raw_merge_stats(node_stats[node_name],
                                                 response)
                elif action == "stats_objects":
                    self.extract_raw_merge_object_stats(
                        node_stats[node_name], response)
                elif action == "confirmation_active":
                    confirmations_key = "confirmation_active_confirmations"
                    #confirmations_key = "confirmation_active_blocks"
                    #convert to integer except "confirmations"
                    for key, value in self.values_to_integer(
                            #response, skip_keys=["blocks"]).items():
                            response,
                            skip_keys=["confirmations"]).items():
                        node_stats[node_name][f'{action}_{key}'] = value
                    #convert "confirmations" to set()
                    if node_stats[node_name][confirmations_key] == '':
                        node_stats[node_name][confirmations_key] = set(
                        )  #convert '' to set
                    else:
                        node_stats[node_name][confirmations_key] = set(
                            node_stats[node_name][confirmations_key])
                    #move "confirmations" to delta["aecs"]
                    node_stats[node_name]["delta"]["aecs"] = (
                        node_stats[node_name].pop(confirmations_key))
                elif action == "version":
                    for key, value in self.values_to_integer(response,
                                                             skip_keys=[
                                                                 "node_vendor",
                                                                 "node_store",
                                                                 "build_info",
                                                             ]).items():
                        if key == "build_info": value = value.split(" ")[0]
                        node_stats[node_name][f'{action}_{key}'] = value

                else:  #convert values to float. drop all keys whose values can't be converted to float
                    for key, value in self.values_to_integer(response).items():
                        node_stats[node_name][f'{action}_{key}'] = value

        return node_stats

    def calc_delta_stats(self, current, previous,
                         interval):  #compare_active_elections step4 (last)
        if previous is None: return

        #get list of 1 stat for all nodes
        block_count_cemented_current = self.get_nodes_stat_by_key(
            current, "block_count_cemented")
        block_count_cemented_previous = self.get_nodes_stat_by_key(
            previous, "block_count_cemented")
        block_count_count_current = self.get_nodes_stat_by_key(
            current, "block_count_count")
        block_count_count_previous = self.get_nodes_stat_by_key(
            previous, "block_count_count")

        keys = [x for x in current.keys()]  #returns list of node_stats

        for i in range(0, self.get_node_count(current)):
            if keys[i] not in previous:
                print(f'skip {keys[i]} : not in previous stats')
                continue

            current[keys[i]]["calc_delta_bps_last_5s"] = (
                block_count_count_current[keys[i]] -
                block_count_count_previous[keys[i]]) / interval  #calc bps
            current[keys[i]]["calc_delta_cps_last_5s"] = (
                block_count_cemented_current[keys[i]] -
                block_count_cemented_previous[keys[i]]) / interval  #calc cps

            if "delta" in current[keys[i]]:
                #calc churn
                aec_union = current[keys[i]]["delta"]["aecs"].union(
                    previous[keys[i]]["delta"]["aecs"])
                aec_inter = current[keys[i]]["delta"]["aecs"].intersection(
                    previous[keys[i]]["delta"]["aecs"])
                current[keys[i]]["calc_delta_churn"] = len(aec_union) - len(
                    aec_inter)

                #compute delta stats
                for key, node_stat in current[keys[i]]["delta"].items():
                    if str(key).startswith("stats"):
                        current[
                            keys[i]][f"delta_{key}"] = node_stat - previous[
                                keys[i]]["delta"].get(key, 0)

    def prepare_node_stats(self, request_responses,
                           nano_node_version):  #compare_active_elections step3
        timestamp = datetime.now().strftime("%Y-%d-%m, %H:%M:%S")
        node_stats = self.set_node_stats(request_responses)
        self.extend_node_stats_all_nodes(node_stats, timestamp)
        self.extend_node_stats_shared_stats(node_stats, nano_node_version,
                                            timestamp)
        return node_stats

    def exec_requests(self,
                      collected_requests):  #compare_active_elections step2
        result = {}
        counter = 0
        try:
            res = self.ppost.exec_parallel_post(collected_requests)
            #{"action" : {"url1" : {}, "url2" : {}, ...}}
            for request in res:
                counter = counter + 1
                action = request["request"]["action"]
                type = request["request"].get("type")
                if type is not None: action = f'{action}_{type}'
                url = request["url"]
                response = request["response"]
                if action not in result: result[action] = {}
                if url not in result[action]: result[action][url] = {}
                result[action][url] = response
        except:
            print("DEBUG", traceback.print_exc)
        print(datetime.now().strftime('%H:%M:%S'),
              "DEBUG collected_requests | len(result)", counter, len(result))
        return result

    def collect_requests(self):  #compare_active_elections step1
        requests = {}
        for rpc in self.rpcs:
            auth = rpc["rpc_auth"] if "rpc_auth" in rpc else {
                "user": None,
                "password": None
            }
            auth_key = f'{auth["user"]}|{auth["password"]}'
            if auth_key not in requests: requests[auth_key] = []
            requests[auth_key].append(
                self.get_req_object(rpc["rpc_url"], {
                    "action": "stats",
                    "type": "counters"
                }))
            requests[auth_key].append(
                self.get_req_object(rpc["rpc_url"], {
                    "action": "stats",
                    "type": "objects"
                }))
            requests[auth_key].append(
                self.get_req_object(rpc["rpc_url"], {"action": "block_count"}))
            requests[auth_key].append(
                self.get_req_object(rpc["rpc_url"],
                                    {"action": "confirmation_active"}))
            requests[auth_key].append(
                self.get_req_object(rpc["rpc_url"],
                                    {"action": "confirmation_quorum"}))
            requests[auth_key].append(
                self.get_req_object(rpc["rpc_url"], {"action": "version"}))
        return requests

    def compare_active_elections(self,
                                 previous_nodes_stats=None,
                                 nano_node_version=None,
                                 interval=None):

        requests = self.collect_requests()
        request_responses = self.exec_requests(requests)
        current_nodes_stats = self.prepare_node_stats(request_responses,
                                                      nano_node_version)
        self.calc_delta_stats(current_nodes_stats, previous_nodes_stats,
                              interval)
        self.log_file_kibana(current_nodes_stats)
        self.log_started_elections()
        return current_nodes_stats


class ReturnValueThread(threading.Thread):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.result = None

    def run(self):
        if self._target is None:
            return  # could alternatively raise an exception, depends on the use case
        try:
            self.result = self._target(*self._args, **self._kwargs)
        except Exception as exc:
            traceback.print_exc()
            print(f'{type(exc).__name__}: {exc}'
                  )  # properly handle the exception

    def join(self, *args, **kwargs):
        super().join(*args, **kwargs)
        return self.result


def run_threaded(job_func, *args, **kwargs):
    job_thread = ReturnValueThread(target=job_func, *args, **kwargs)
    job_thread.start()
    return job_thread


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-v',
        '--version',
        help=
        'mandatory, specify the nano_node version you are running (for logging purpose)'
    )
    return parser.parse_args()


def main():
    s = NanoStats()
    args = parse_args()
    # if args.version is None :
    #     raise Exception("Please specify a nano_node version for logging purpose")

    interval = 5
    wait_mod(interval=interval)

    previous_nodes_stats = None
    while True:

        t1 = run_threaded(s.compare_active_elections,
                          kwargs={
                              "previous_nodes_stats": previous_nodes_stats,
                              "nano_node_version": args.version,
                              "interval": interval
                          })
        previous_nodes_stats = t1.join(timeout=300)
        if previous_nodes_stats is None:
            print(">>> WARNING: compare_active_elections TIMEOUT")
        wait_mod(interval=interval)


if __name__ == "__main__":
    main()

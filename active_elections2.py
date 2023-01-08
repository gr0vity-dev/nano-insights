#!./venv_nano_stats/bin/python

from time import strftime, gmtime, time, sleep
from datetime import datetime
import argparse
import json
import traceback
import aiohttp
import asyncio
import numpy as np
import pandas as pd
import csv


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
        #self.aio_conn = self.set_aio_connection()
        self.aio_results = []

    def get_or_create_eventloop(self):
        try:
            return asyncio.get_event_loop()
        except RuntimeError as ex:
            if "There is no current event loop in thread" in str(ex):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                return asyncio.get_event_loop()

    # async def set_aio_connection(self):
    #     # 0.1s for 1million connections
    #     if self.aio_conn is None:
    #         self.aio_conn = aiohttp.TCPConnector(limit_per_host=50,
    #                                              limit=50,
    #                                              verify_ssl=False,
    #                                              force_close=True)

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

    def collect_requests(
            self,
            block_hash=None,
            active_elections=False):  #compare_active_elections step1
        requests = {}
        for rpc in self.rpcs:
            auth = rpc["rpc_auth"] if "rpc_auth" in rpc else {
                "user": None,
                "password": None
            }
            auth_key = f'{auth["user"]}|{auth["password"]}'
            if auth_key not in requests: requests[auth_key] = []
            #
            requests[auth_key].append(
                self.get_req_object(rpc["rpc_url"], {"action": "block_count"}))
            #requests[auth_key].append(self.get_req_object(rpc["rpc_url"], {"action": "channels"}))
            requests[auth_key].append(
                self.get_req_object(rpc["rpc_url"], {
                    "action": "representatives_online",
                    "weight": "true"
                }))
            requests[auth_key].append(
                self.get_req_object(rpc["rpc_url"], {"action": "peers"}))
            requests[auth_key].append(
                self.get_req_object(rpc["rpc_url"], {"action": "version"}))
            if active_elections:
                requests[auth_key].append(
                    self.get_req_object(rpc["rpc_url"],
                                        {"action": "active_elections"}))
            if block_hash is not None:
                requests[auth_key].append(
                    self.get_req_object(rpc["rpc_url"], {
                        "action": "block_info",
                        "hash": block_hash
                    }))

        return requests

    def read_config(self):
        if self.config is None:
            self.config = self.conf_rw.read_json(self.conf_path)
        return self.config

    def get_rpcs(self):
        json_config = self.read_config()
        return json_config["nodes"]

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

    def get_req_object(self, url, request):
        return {"url": url, "request": request}


def get_mapping():
    return {
        "http://192.168.178.88:45200": "6",
        "http://192.168.178.88:45201": "0",
        "http://192.168.178.88:45202": "1",
        "http://192.168.178.88:45203": "2",
        "http://192.168.178.88:45204": "3",
        "http://192.168.178.88:45205": "4",
        "http://192.168.178.88:45206": "5",
        "nano_1fzwxb8tkmrp8o66xz7tcx65rm57bxdmpitw39ecomiwpjh89zxj": "6",
        "nano_1ge7edbt774uw7z8exomwiu19rd14io1nocyin5jwpiit3133p9eaaxn74ub":
        "0",
        "nano_3sz3bi6mpeg5jipr1up3hotxde6gxum8jotr55rzbu9run8e3wxjq1rod9a6":
        "1",
        "nano_3z93fykzixk7uoswh8fmx7ezefdo7d78xy8sykarpf7mtqi1w4tpg7ejn18h":
        "2",
        "nano_137xfpc4ynmzj3rsf3nej6mzz33n3f7boj6jqsnxpgqw88oh8utqcq7nska8":
        "3",
        "nano_338h8cteza4qnehychggdjoe5teuqoyz8eyed31r81odre76rqtppcn7dbi6":
        "4",
        "nano_3jtewgdxz3yhmojpsb9s1tx3ide4m376t66tio9dsh37bh6ppyzip3dkpnpk":
        "5"
    }


def parse_active_elections(rpc_responses, election, a, b, start_time):

    # |--------------------|-----|-----|-----|-----|-----|-----|
    # | column             | pr1 | pr2 | pr3 | pr4 | pr5 | pr6 |
    # |--------------------|-----|-----|-----|-----|-----|-----|
    # | has final_vote pr1 |  1  |     |     |     |     |     |
    # |--------------------|-----|-----|-----|-----|-----|-----|
    # | has final_vote pr2 |     | 1   |     |     | X   |     |
    # |--------------------|-----|-----|-----|-----|-----|-----|
    # | has final_vote pr3 |     |     | 3   |     |     |     |
    # |--------------------|-----|-----|-----|-----|-----|-----|
    # | has final_vote pr4 | X   | X   | X   | 4   | X   | X   |
    # |--------------------|-----|-----|-----|-----|-----|-----|
    # | has final_vote pr5 |     |     |     |     |  2  |     |
    # |--------------------|-----|-----|-----|-----|-----|-----|
    # | has final_vote pr6 |     |     |     |     |     |  2  |
    # |--------------------|-----|-----|-----|-----|-----|-----|
    # | confirmed          |     |     |     |     |     |  5  |
    # |--------------------|-----|-----|-----|-----|-----|-----|

    nodes = [0, 1, 2, 3, 4, 5, 6]

    elections = {}
    rows = []
    for key1, items in rpc_responses["active_elections"].items():
        if items["elections"] == "": continue  # no elections
        node_name = int(get_mapping()[key1])
        for root, election_details in items["elections"].items():
            if root != election: continue
            elections.setdefault(root, {})

            for stat, value in election_details.items():
                if stat == "votes":
                    for pr_address, vote in value.items():
                        pr_name = int(get_mapping()[pr_address])
                        if vote["final"] == "true":
                            if b[pr_name][node_name] == 0:
                                b[pr_name][node_name] = round(
                                    time() - start_time, 2)

                        elif vote["final"] == "false":
                            if a[pr_name][node_name] == 0:
                                a[pr_name][node_name] = round(
                                    time() - start_time, 2)
                else:
                    continue

    for pr, block_info in rpc_responses["block_info"].items():
        node_name = int(get_mapping()[pr])
        if "confirmed" in block_info and block_info["confirmed"] == "true":
            if b[6][node_name] == 0:
                b[6][node_name] = round(time() - start_time, 2)

    return a, b


def query_hash_in_active_elections(active_elections, query_hash):

    nodes = ["pr1", "pr2", "pr3", "pr4", "pr5", "pr6", "genesis"]
    prs = {}
    pr_keys = []
    current_election = None
    for key1, items in active_elections["active_elections"].items():
        if items["blocks"] == "": continue  # no elections
        node_name = get_mapping()[key1]
        for b, e in items["blocks"].items():
            if b == query_hash:
                current_election = e
                confirmed = active_elections["block_info"][key1][
                    "confirmed"] if "confirmed" in active_elections[
                        "block_info"][key1] else "block_missing"
                pr_keys.append(node_name)
                prs[node_name] = {
                    "confirmed": confirmed,
                    "AEC_size": len(items["blocks"])
                }
        else:
            continue

    sorted_pr_keys = sorted(pr_keys)

    simple_string = ""
    for node in nodes:
        if node in sorted_pr_keys:
            row = prs[node]["confirmed"]
            if prs[node]["confirmed"] == "false":
                row = "active"
            simple_string = "{}| {:11}".format(simple_string, row)
        else:
            simple_string = simple_string + "|            "
    #print("|", "| ".join(["{:11}".format(x) for x in nodes]))
    #print(simple_string)
    return current_election


def print_to_console(action, args):
    if action == 1:
        print(
            "",
            "-" * 64,
            "\n",
            "-" * 32,
            args[0],
            "\n",
            "-" * 64,
        )


def main_gather_elections(query_hash, interval):
    s = NanoStats()
    a = np.zeros((6, 6))
    b = np.zeros((7, 6))
    start_time = time()
    while True:
        requests = s.collect_requests(active_elections=True,
                                      block_hash=query_hash)
        request_responses = s.exec_requests(requests)

        election = query_hash_in_active_elections(request_responses,
                                                  query_hash)
        a, b = parse_active_elections(request_responses, election, a, b,
                                      start_time)

        if np.all(b[6]):
            cols = ["PR1", "PR2", "PR3", "PR4", "PR5", "PR6"]
            idx = [
                "has vote PR1", "has vote PR2", "has vote PR3", "has vote PR4",
                "has vote PR5", "has vote PR6"
            ]
            idx2 = [
                "has final PR1", "has final PR2", "has final PR3",
                "has final PR4", "has final PR5", "has final PR6", "confirmed"
            ]

            df = pd.DataFrame(a, columns=cols, index=idx)
            df2 = pd.DataFrame(b, columns=cols, index=idx2)
            print(df, "\n", df2)

            break

        sleep(interval)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-w',
                        '--wait',
                        type=int,
                        default=5,
                        help='interval wait time')
    parser.add_argument('--block_hash', help='block_hash')
    #parser.add_argument('-e', '--election', help='election')
    parser.add_argument('command', help='hash', default='create')
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # main_gather_elections(
    #     "C093163E9AAEB6118141E3BAFD19F410E414E1A030EE6ED225F55669A28E2D8D", 5)

    if args.command == "hash":
        main_gather_elections(args.block_hash, args.wait)

    #main_overlap("c900a7eb359ee50f48d7")
    #main_parse_active_elections("D62E61AF0C477207C80F0762227B53108125FC9598FAA5C5E2A6A099494C8DE60000000000000000000000000000000000000000000000000000000000000000","c900a7eb359ee50f48d7")
    #main()

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
import csv
import os


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

    def collect_requests(self,
                         active_elections=False
                         ):  #compare_active_elections step1
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
        "http://192.168.178.88:45200": "genesis",
        "http://192.168.178.88:45201": "pr1",
        "http://192.168.178.88:45202": "pr2",
        "http://192.168.178.88:45203": "pr3",
        "http://192.168.178.88:45204": "pr4",
        "http://192.168.178.88:45205": "pr5",
        "http://192.168.178.88:45206": "pr6",
        "nano_1fzwxb8tkmrp8o66xz7tcx65rm57bxdmpitw39ecomiwpjh89zxj": "genesis",
        "nano_1ge7edbt774uw7z8exomwiu19rd14io1nocyin5jwpiit3133p9eaaxn74ub":
        "pr1",
        "nano_3sz3bi6mpeg5jipr1up3hotxde6gxum8jotr55rzbu9run8e3wxjq1rod9a6":
        "pr2",
        "nano_3z93fykzixk7uoswh8fmx7ezefdo7d78xy8sykarpf7mtqi1w4tpg7ejn18h":
        "pr3"
    }


def query_hash_in_active_elections(active_elections, query_hash):

    nodes = ["pr1", "pr2", "pr3", "pr4", "pr5", "pr6", "genesis"]

    prs = []
    for key1, items in active_elections["active_elections"].items():
        if items["blocks"] == "": continue  # no elections
        node_name = get_mapping()[key1]
        for b, e in items["blocks"].items():
            if b == query_hash:
                prs.append(node_name)
        else:
            continue
    return prs


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
    while True:
        requests = s.collect_requests(active_elections=True)
        request_responses = s.exec_requests(requests)

        print(query_hash_in_active_elections(request_responses, query_hash))

        time.sleep(interval)


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
    # args = parse_args()

    main_gather_elections(
        "E6E5E2DEDD4A51869F91CF81AFAA4A29ADF9031A402ABFD1956D6A0B0B482149", 5)

    # if args.command == "hash":
    #     main_gather_elections(args.block_hash, args.wait)

    #main_overlap("c900a7eb359ee50f48d7")
    #main_parse_active_elections("D62E61AF0C477207C80F0762227B53108125FC9598FAA5C5E2A6A099494C8DE60000000000000000000000000000000000000000000000000000000000000000","c900a7eb359ee50f48d7")
    #main()

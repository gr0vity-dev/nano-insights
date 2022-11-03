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

#nodes_stat returns a list with 1 stat for all nodes
#node_stats retruns a dict with all stats for 1 node
#nodes_stats retruns a list with all stats for all nodes

#ws0 = SimpleWs("ws://192.168.178.88:47000", "nl_gen", "V24DB20", "vote")
# ws1 = SimpleWs("ws://192.168.178.88:47001", "nl_pr1", "V24DB20", "vote")
# ws2 = SimpleWs("ws://192.168.178.88:47002", "nl_pr2", "V24DB20", "vote")
# ws3 = SimpleWs("ws://192.168.178.88:47003", "nl_pr3", "V24DB20", "vote")


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


def get_mapping():
    return {
        "http://192.168.178.88:45000": "genesis",
        "http://192.168.178.88:45001": "pr1",
        "http://192.168.178.88:45002": "pr2",
        "http://192.168.178.88:45003": "pr3",
        "nano_1fzwxb8tkmrp8o66xz7tcx65rm57bxdmpitw39ecomiwpjh89zxj": "genesis",
        "nano_1ge7edbt774uw7z8exomwiu19rd14io1nocyin5jwpiit3133p9eaaxn74ub":
        "pr1",
        "nano_3sz3bi6mpeg5jipr1up3hotxde6gxum8jotr55rzbu9run8e3wxjq1rod9a6":
        "pr2",
        "nano_3z93fykzixk7uoswh8fmx7ezefdo7d78xy8sykarpf7mtqi1w4tpg7ejn18h":
        "pr3"
    }


def parse_active_elections(active_elections, election, log_time):

    # winner (91504779326E8D03E1125EDA144E7CA07E55951B73ECD926E46F3E4A4F9F093F)
    #                       | pr1       | pr2       |   pr3
    #has vote pr1           |           |           |
    #has vote pr2           |           |           |
    #has vote pr3           |           |           |
    #dependents_confirmed   |
    #tally
    #final_tally
    #Quorum

    nodes = ["pr1", "pr2", "pr3", "genesis"]

    elections = {}
    rows = []
    for key1, items in active_elections["active_elections"].items():
        if items["elections"] == "": continue  # no elections
        node_name = get_mapping()[key1]
        row_index = nodes.index(node_name)
        for root, election_details in items["elections"].items():
            elections.setdefault(root, {})

            for stat, value in election_details.items():
                if value == "": continue
                if stat == "blocks": continue
                if stat == "votes":
                    for pr_address, vote in value.items():
                        pr_name = get_mapping()[pr_address]
                        if vote["final"] == "true":
                            row_name = f"has final_vote {pr_name}"
                        elif vote["final"] == "false":
                            row_name = f"has vote {pr_name}"

                        row_index_l = nodes.index(node_name)
                        elections[root].setdefault(row_name, ["", "", "", ""])
                        elections[root][row_name][row_index_l] = "X"
                    continue
                elections[root].setdefault(stat, ["", "", "", ""])
                elections[root][stat][row_index] = value

    current_index = 0
    rows = []
    header = ["column"]
    header.extend(nodes)
    rows.append(header)
    for key, value in elections.items():
        if key != election: continue
        for row_name, row_details in value.items():
            if row_name == "root": continue
            if row_name == "qualified_root": continue
            if row_name == "winner":
                rows.insert(current_index, [log_time, row_details[0]])
                current_index = current_index + 1
                continue
            row = [row_name]
            row.extend(row_details)
            rows.append(row)
            current_index = current_index + 1
        current_index = current_index + 1

    rows.append(["=" * 12])  # empty line spacing between files
    return rows


def init_websockets(s: NanoStats, websockets):

    nodes = s.get_rpcs()
    websockets = [ws for ws in websockets if not ws.is_closed]
    while (len(nodes) != len(websockets)):
        time.sleep(0.5)
        print(len(websockets))

        if len(websockets) == len(nodes):
            continue

        requests = s.collect_requests()
        request_responses = s.exec_requests(requests)
        if len(request_responses) == 0:
            continue

        versions = [
            f'{version["node_vendor"]} {version["build_info"].split(" ")[0]}'
            for version in request_responses["version"].values()
        ]
        if len(versions) != len(nodes):
            websockets = []
            continue

        for i, node in enumerate(nodes):
            websockets.append(
                SimpleWs(node["ws_url"], node["name"], versions[i],
                         "started_election"))
    return websockets


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


def find_overlap(election_overlap, active_elections):
    # {
    #  "election1" : "overlap_count",
    #  "election2" : "overlap_count",
    #  ....
    # }

    #put all elections into a set, the iterate over all elections and see which elections ar present for every PR
    unique_elections_in_file = set()
    all_elections = {}

    active_elections.pop("http://192.168.178.88:45000")  # kick no pr node

    # for key1, items in active_elections.items():
    #     if items["elections"] == "": continue  # no elections
    #     node_name = get_mapping()[key1]
    #     for election in items["elections"].keys():
    #         unique_elections_in_file.add(election)
    #         all_elections.append(election)

    # for election in unique_elections_in_file:
    #     if all_elections.count(election) == 3:
    #         election_overlap.setdefault(election, 0)
    #         election_overlap[election] = election_overlap[election] + 1

    for key1, items in active_elections.items():
        if items["elections"] == "": continue  # no elections
        node_name = get_mapping()[key1]
        for election, stats in items["elections"].items():
            unique_elections_in_file.add(election)
            all_elections.setdefault(election, {"count": 0})
            all_elections[election]["hash"] = stats["winner"]
            all_elections[election][
                "count"] = all_elections[election]["count"] + 1

    for election in unique_elections_in_file:
        if all_elections[election]["count"] == 3:
            election_overlap.setdefault(election, {"count": 0})
            election_overlap[election]["hash"] = all_elections[election][
                "hash"]
            election_overlap[election][
                "count"] = election_overlap[election]["count"] + 1

    return election_overlap


def main_gather_elections():
    ''' Gathers started elections every 5s {iteration_duration}
        if no new active elections occur between runs, "active_elections" is called and the result dumped to file
        Generates a .json file .{run_id}/HH:MM:SS_election_started.json 
         that contains the information from the active_elections rpc (and the other defined)'''
    expected_started_elections = 50000
    iteration_duration = 5

    s = NanoStats()
    websockets = []
    conf_rw = ConfigReadWrite()

    run_id = secrets.token_hex(10)
    os.mkdir(run_id)
    os.mkdir(run_id + "_long_running")

    prev_count = 0
    while True:
        websockets = init_websockets(s, websockets)
        print_to_console(1, [run_id])
        for ws in websockets:
            election_count = ws.log_started_elections(
                run_id, expected_started_elections, write_to_db=True)
            if election_count > 0 and election_count == prev_count:
                requests = s.collect_requests(active_elections=True)
                request_responses = s.exec_requests(requests)
                file_name = f'{str(datetime.now().hour).rjust(2, "0")}:{str(datetime.now().minute).rjust(2, "0")}:{str(datetime.now().second).rjust(2, "0")}'
                conf_rw.write_json(
                    f"./{run_id}/{file_name}_election_started.json",
                    request_responses)
                print("executed election_started rpc")

            prev_count = election_count
        time.sleep(iteration_duration)


def main_overlap(run_id):
    ''' Generates a file .{run_id}/___OVERLAP___.json that contains all overlapping elections with the block_hash and the number of occurences'''
    conf_rw = ConfigReadWrite()
    #run_id = "c900a7eb359ee50f48d7"

    all_overlap = {}

    files = os.listdir(run_id)

    for file in files:
        if file.startswith("___"): continue
        data = conf_rw.read_json(run_id + "/" + file)
        all_overlap = find_overlap(all_overlap, data["active_elections"])

    file_name = f"./{run_id}/___OVERLAP___.json"
    conf_rw.write_json(file_name, all_overlap)
    print("Found", len(all_overlap), "overlapping elections")
    print("File written to disk:", file_name)


def main_detail(election, run_id):
    ''' Reads all files in ./{run_id} folder
        Per file , the script gathers data for the selected {election} and writes it to .csv format for better overview 
        Generates a .csv file .{run_id}/___DETAIL___{elections}.csv '''

    conf_rw = ConfigReadWrite()
    files = sorted(os.listdir(run_id))

    rows = []
    for file in files:
        if file.startswith("___"): continue
        #file = files[key]

        data = conf_rw.read_json(run_id + "/" + file)
        rows.extend(
            parse_active_elections(data, election,
                                   file.split("_")[0].replace("|", ":")))

    file_name = f'./{run_id}/___DETAIL___{election}.csv'
    file = open(file_name, 'w+', newline='')
    # writing the data into the file
    with file:
        write = csv.writer(file)
        write.writerows(rows)
    print("Parsed", len(files), "files")
    print("File written to disk:", file_name)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-r',
                        '--runid',
                        default=secrets.token_hex(10),
                        help='runid')
    parser.add_argument('-e', '--election', help='election')
    parser.add_argument('command',
                        help='gather ,overlap, detail',
                        default='create')
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.command == "gather":
        main_gather_eelctions()
    elif args.command == "overlap":
        main_overlap(args.runid)
    elif args.command == "detail":
        main_detail(args.election, args.runid)

    #main_overlap("c900a7eb359ee50f48d7")
    #main_parse_active_elections("D62E61AF0C477207C80F0762227B53108125FC9598FAA5C5E2A6A099494C8DE60000000000000000000000000000000000000000000000000000000000000000","c900a7eb359ee50f48d7")
    #main()

from datetime import datetime
import time
from copy import deepcopy
import secrets
import json
import threading

from sql.insert_testcase import NanoSql


class StatsLogger():

    env = ""
    test_name = ""
    suite_id = ""

    def new_testsuite(self, env_l, test_name_l):
        global env, test_name, suite_id
        env = env_l
        test_name = test_name_l
        self.start_date = datetime.now().strftime('%y-%m-%d %H:%M:%S')
        suite_id = secrets.token_hex(32)


class BlockCreateStats(StatsLogger):

    def __init__(self, node_name=""):
        self.start_time = time.time()
        self.node_name = node_name

    def set_stats(self, block_count, log_type="console"):
        self.end_time = time.time()
        self.duration_s = self.end_time - self.start_time
        self.block_count = block_count
        self.bps = block_count / self.duration_s
        if log_type == "console":
            print(vars(self))


class PublishStats(StatsLogger):

    def __init__(self, nodename=""):
        self.start_date = datetime.now().strftime('%y-%m-%d %H:%M:%S')
        self.start_time = time.time()
        self.node_is_publisher = True
        self.node_name = nodename

    def set_stats(self,
                  block_count,
                  sync,
                  log_type="console"):  #TODO add sync to sql
        self.end_time = time.time()
        self.duration_s = self.end_time - self.start_time
        self.block_count = block_count
        self.bps = block_count / self.duration_s
        if log_type == "console":
            print(vars(self))


class WebsocketConfirmationStats(StatsLogger):

    # class HashSats():

    #     def __init__(self, hash):

    #         self.votes = 0
    #         self.final_votes = 0
    #         self.replay = 0
    #         self.vote = 0
    #         self.indeterminate = 0

    def __init__(self, node_name, node_version):
        self.stats_is_logged = False

        self.expected_hashes = []
        self.remaining_hashes = []
        self.confirmed_hashes_in_expected = []
        self.confirmed_hashes_out_expected = []

        self.expected_count = 0

        self.start_date = datetime.now().strftime('%y-%m-%d %H:%M:%S')
        self.start_timer = time.time()
        self.duration_first_conf = 0
        self.timer_first_conf = None
        self.end_date = None
        self.duration_s = 0

        self.conf_10p = 0
        self.conf_25p = 0
        self.conf_50p = 0
        self.conf_75p = 0
        self.conf_90p = 0
        self.conf_99p = 0
        self.conf_100p = 0

        self.cps_10p = 0
        self.cps_25p = 0
        self.cps_50p = 0
        self.cps_75p = 0
        self.cps_90p = 0
        self.cps_99p = 0
        self.cps_100p = 0

        #self.bps = 0
        #self.block_count = 0
        self.node_is_publisher = None
        self.node_name = node_name
        self.version = node_version
        self.conf_count_all = 0
        self.conf_count_in_expected = 0

        self.conf_100p_all = 0
        self.cps_100p_all = 0

    def set_expected_hashes(self, hash_list):
        hash_copy = []
        if any(isinstance(i, list) for i in hash_list):  #nested list :
            for i in range(0, len(hash_list)):
                self.expected_count = self.expected_count + len(hash_list[i])
                hash_copy.extend(deepcopy(hash_list[i]))
        else:
            hash_copy = deepcopy(hash_list)
            self.expected_count = len(hash_copy)

        self.expected_hashes = hash_copy
        self.remaining_hashes = deepcopy(hash_copy)

    def inc_confirmation_counter(self):
        self.conf_count_all = self.conf_count_all + 1

    def receive_hash(self, hash):
        self.update_hash_lists(hash)
        self.update_confirmation_count()

    def update_hash_lists(self, hash):
        if hash in self.expected_hashes:
            self.remaining_hashes.remove(hash)
            self.confirmed_hashes_in_expected.append(hash)
            if self.timer_first_conf == None:
                self.timer_first_conf = time.time()
                self.duration_first_conf = round(time.time() -
                                                 self.start_timer)
        else:
            self.confirmed_hashes_out_expected.append(hash)

    def update_confirmation_count(self):
        #conf_perc =(confirmed / expected) * 100
        confirmed_count = self.get_confirmed_hashes_count_expected()
        conf_count_all = self.get_confirmed_hashes_count_all()
        conf_perc = (confirmed_count / self.expected_count) * 100

        if self.conf_10p == 0 and conf_perc >= 10:
            self.conf_10p = time.time() - self.timer_first_conf
            self.cps_10p = (self.expected_count *
                            (conf_perc / 100)) / self.conf_10p
            self.print_advancement(conf_perc, self.conf_10p, self.cps_10p)

        if self.conf_25p == 0 and conf_perc >= 25:
            self.conf_25p = time.time() - self.timer_first_conf
            self.cps_25p = (self.expected_count *
                            (conf_perc / 100)) / self.conf_25p
            self.print_advancement(conf_perc, self.conf_25p, self.cps_25p)

        if self.conf_50p == 0 and conf_perc >= 50:
            self.conf_50p = time.time() - self.timer_first_conf
            self.cps_50p = (self.expected_count *
                            (conf_perc / 100)) / self.conf_50p
            self.print_advancement(conf_perc, self.conf_50p, self.cps_50p)

        if self.conf_75p == 0 and conf_perc >= 75:
            self.conf_75p = time.time() - self.timer_first_conf
            self.cps_75p = (self.expected_count *
                            (conf_perc / 100)) / self.conf_75p
            self.print_advancement(conf_perc, self.conf_75p, self.cps_75p)

        if self.conf_90p == 0 and conf_perc >= 90:
            self.conf_90p = time.time() - self.timer_first_conf
            self.cps_90p = (self.expected_count *
                            (conf_perc / 100)) / self.conf_90p
            self.print_advancement(conf_perc, self.conf_90p, self.cps_90p)

        if self.conf_99p == 0 and conf_perc >= 99:
            self.conf_99p = time.time() - self.timer_first_conf
            self.cps_99p = (self.expected_count *
                            (conf_perc / 100)) / self.conf_99p
            self.print_advancement(conf_perc, self.conf_99p, self.cps_99p)

        if self.conf_100p == 0 and conf_perc >= 100:
            self.conf_100p = time.time() - self.timer_first_conf
            self.cps_100p = (self.expected_count *
                             (conf_perc / 100)) / self.conf_100p
            self.print_advancement(conf_perc, self.conf_100p, self.cps_100p)

        if self.conf_100p_all == 0 and conf_count_all >= self.expected_count:
            self.conf_100p_all = time.time() - self.timer_first_conf
            self.cps_100p_all = self.expected_count / self.conf_100p_all
            self.print_advancement(conf_perc, self.conf_100p_all,
                                   self.cps_100p_all)

    def print_advancement(self, conf_perc, duration, cps_np):
        #print(f">>>> {round(duration,2)}s for {round(conf_perc,2)}%  @{round(cps_np,2)} cps ")
        print(">>> {:>10} {:>6}% in {:<9}s @{:>8}cps -- {}".format(
            self.node_name, round(conf_perc, 2), round(duration, 2),
            round(cps_np, 2), self.version))

    def set_conf_stats(self, conf_np, cps_np, conf_perc, conf_value):
        if self.timer_first_conf is None: return

        #print("DEBUG1 perc, _s, _cps, _conf_perc", conf_value,  conf_var, cps_var,conf_perc )
        if conf_np == 0 and conf_perc >= conf_value:
            conf_np = time.time() - self.timer_first_conf
            cps_np = (self.expected_count * (conf_perc / 100)) / conf_np
            #return(conf_np, cps_np)

    def get_remaining_hashes(self):
        return self.remaining_hashes

    def get_remaining_hashes_count(self):
        count = len(self.remaining_hashes)
        return count

    def get_confirmed_hashes_count_expected(self):
        return len(self.confirmed_hashes_in_expected)

    def get_confirmed_hashes_count_all(self):
        return len(self.confirmed_hashes_in_expected) + len(
            self.confirmed_hashes_out_expected)

    def log_stats(self, log_type="console"):
        if self.stats_is_logged: return

        self.end_date = datetime.now().strftime('%y-%m-%d %H:%M:%S')
        self.duration_s = time.time() - self.start_timer

        if log_type == "console":
            print([{
                key: value
            } if not isinstance(value, list) else {
                key: f'length={len(value)}'
            } for key, value in vars(self).items()])
            self.stats_is_logged = True


class WebsocketVoteStats(StatsLogger):

    # def __init__(self):
    #     self.start_time = datetime.now().strftime('%y-%m-%d %H:%M:%S')
    #     self.end_time = ""
    #     self.duration_s = ""
    #     self.bps = ""
    #     self.vote_count = 0
    #     self.node_is_publisher = None
    #     node_name = ""
    #     version = ""

    def __init__(self, node_name, node_version):
        self.node_name = node_name
        self.version = node_version
        self.hash_stats = {
            "hash": {
                "vote_count": 0,
                "final_vote_count": 0,
                "voters": {
                    "pr1": {
                        "replay": 0,
                        "vote": 0,
                        "indeterminate": 0,
                    },
                    "pr2": {
                        "replay": 0,
                        "vote": 0,
                        "indeterminate": 0,
                    },
                    "pr3": {
                        "replay": 0,
                        "vote": 0,
                        "indeterminate": 0,
                    }
                }
            }
        }

    def inc_counter(self, key, counter=None):
        if key not in counter:
            counter[key] = 0
        counter[key] = counter[key] + 1

    def value_match(self, json, key, value):
        if key in json and json[key] == value:
            return True
        return False

    def is_final_vote(self, json_msg):
        if json_msg["message"]["timestamp"] == "18446744073709551615":
            return True
        return False

    def custom_mapper(self, address):
        mapper = {
            "nano_1ge7edbt774uw7z8exomwiu19rd14io1nocyin5jwpiit3133p9eaaxn74ub":
            "nl_pr1",
            "nano_3sz3bi6mpeg5jipr1up3hotxde6gxum8jotr55rzbu9run8e3wxjq1rod9a6":
            "nl_pr2",
            "nano_3z93fykzixk7uoswh8fmx7ezefdo7d78xy8sykarpf7mtqi1w4tpg7ejn18h":
            "nl_pr3"
        }
        return mapper[address]

    def init_hash_stats(self):
        return {
            "first_vote_t": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "last_vote_t": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "alive_s": 0,
            "vote_count": 0,
            "vote_count_by_voter": {},
            "vote": 0,
            "vote_final": 0,
            "replay": 0,
            "replay_final": 0,
            "indeterminate": 0,
            "indeterminate_final": 0,
            "voters_vote": {},
            "voters_replay": {},
            "voters_indeterminate": {},
            "voters_final_vote": {},
            "voters_final_replay": {},
            "voters_final_indeterminate": {},
        }

    def append_if_new(self, key_l, list_l: list):
        if key_l in list_l: return
        list_l.append(key_l)

    def update_vote_count(self, json_msg):

        # print(">>>DEBUG", self.node_name, json_msg["time"], json_msg["topic"],
        #       len(json_msg["message"]["blocks"]))

        for block_hash in json_msg["message"]["blocks"]:
            #add hash if not exists
            if block_hash not in self.hash_stats:
                self.hash_stats[block_hash] = self.init_hash_stats()
            self.hash_stats[block_hash]["last_vote_t"] = str(datetime.now())
            self.hash_stats[block_hash]["alive_s"] = str(
                (datetime.strptime(self.hash_stats[block_hash]["last_vote_t"],
                                   "%Y-%m-%d %H:%M:%S.%f") -
                 datetime.strptime(self.hash_stats[block_hash]["first_vote_t"],
                                   "%Y-%m-%d %H:%M:%S.%f")).seconds)
            account = self.custom_mapper(json_msg["message"]["account"])

            self.inc_counter(
                account,
                counter=self.hash_stats[block_hash]["vote_count_by_voter"])

            #increment votecount per hash
            self.inc_counter("vote_count", counter=self.hash_stats[block_hash])

            if self.value_match(json_msg["message"], "type", "vote"):
                if self.is_final_vote(json_msg):
                    self.inc_counter(account,
                                     counter=self.hash_stats[block_hash]
                                     ["voters_final_vote"])
                    self.inc_counter("vote_final",
                                     counter=self.hash_stats[block_hash])
                else:
                    self.inc_counter(
                        account,
                        counter=self.hash_stats[block_hash]["voters_vote"])
                    self.inc_counter("vote",
                                     counter=self.hash_stats[block_hash])
            elif self.value_match(json_msg["message"], "type", "replay"):
                if self.is_final_vote(json_msg):
                    self.inc_counter(account,
                                     counter=self.hash_stats[block_hash]
                                     ["voters_final_replay"])
                    self.inc_counter("replay_final",
                                     counter=self.hash_stats[block_hash])
                else:
                    self.inc_counter(
                        account,
                        counter=self.hash_stats[block_hash]["voters_replay"])
                    self.inc_counter("replay",
                                     counter=self.hash_stats[block_hash])
            elif self.value_match(json_msg["message"], "type",
                                  "indeterminate"):
                if self.is_final_vote(json_msg):
                    self.inc_counter(account,
                                     counter=self.hash_stats[block_hash]
                                     ["voters_final_indeterminate"])
                    self.inc_counter("indeterminate_final",
                                     counter=self.hash_stats[block_hash])
                else:
                    self.inc_counter(account,
                                     counter=self.hash_stats[block_hash]
                                     ["voters_indeterminate"])
                    self.inc_counter("indeterminate",
                                     counter=self.hash_stats[block_hash])

    def get_hash_stats_for_list(self, hash_list):
        #return self.hash_stats
        return {
            key: self.hash_stats[key] if key in self.hash_stats else None
            for key in hash_list
        }

    def log_hash_stats(self):
        with open(f"./{self.node_name}_hash_stats_{secrets.token_hex(6)}.json",
                  "w") as f:
            json.dump(self.hash_stats, f)


class WebsocketStartedElectionStats(StatsLogger):

    def __init__(self, node_name, node_version):
        self.lock = threading.Lock()
        self.node_name = node_name
        self.version = node_version
        self.time_since_previous_election = None
        self.hash_stats = {
            "total_elections": {
                "counter": 0,
                "first_seen": None,
                "last_seen": None
            },
            "blocks": {}
        }

    def inc_counter(self, key, counter=None):
        if key not in counter:
            counter[key] = 0
        counter[key] = counter[key] + 1

    def init_hash_stats(self):
        return {
            "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            "seen_after_s": 0,
            "since_previous_election_s": 0,
            "number": 0,
            "alive_s": 0,
            "counter": 0,
        }

    def append_if_new(self, key_l, list_l: list):
        if key_l in list_l: return
        list_l.append(key_l)

    def update_election_count(self, json_msg):
        self.lock.acquire()

        if self.hash_stats["total_elections"]["first_seen"] is None:
            self.hash_stats["total_elections"]["first_seen"] = time.time(
            )  #str(datetime.now())
        self.hash_stats["total_elections"]["last_seen"] = str(datetime.now())
        self.inc_counter("counter", counter=self.hash_stats["total_elections"])

        # print(">>>DEBUG", self.node_name, json_msg["time"], json_msg["topic"],
        #       len(json_msg["message"]["blocks"]))

        block_hash = json_msg["message"]["hash"]
        #add block_hash when first seen
        self.hash_stats["blocks"].setdefault(block_hash,
                                             self.init_hash_stats())
        #last seen
        self.hash_stats["blocks"][block_hash]["last_seen"] = str(
            datetime.now())
        #seen_after N seconds since the first election
        self.hash_stats["blocks"][block_hash]["seen_after_s"] = time.time(
        ) - self.hash_stats["total_elections"]["first_seen"]

        #seen_after N seconds since the previous election
        if self.time_since_previous_election is None:
            time_since_previous = 0
        else:
            time_since_previous = time.time(
            ) - self.time_since_previous_election
            self.hash_stats["blocks"][block_hash][
                "since_previous_election_s"] = time_since_previous
        self.time_since_previous_election = time.time()

        #started election number
        if self.hash_stats["blocks"][block_hash]["number"] == 0:
            self.hash_stats["blocks"][block_hash]["number"] = self.hash_stats[
                "total_elections"]["counter"]

        self.inc_counter("counter",
                         counter=self.hash_stats["blocks"][block_hash])
        if self.hash_stats["blocks"][block_hash]["number"] == 10:
            print(self.hash_stats["blocks"][block_hash])
        self.lock.release()

    def get_hash_stats_for_list(self, hash_list):
        #return self.hash_stats
        return {
            key: self.hash_stats["blocks"][key]
            if key in self.hash_stats["blocks"] else None
            for key in hash_list
        }

    def write_logrunning_elections(self, run_id):
        self.lock.acquire()
        dict_copy_l = deepcopy(self.hash_stats["blocks"])
        self.lock.release()

        elections_3s = [
            key for key, value in dict_copy_l.items()
            if value["since_previous_election_s"] > 3
        ]
        if len(self.hash_stats["blocks"].values()) > 0:
            print(next(iter(reversed(dict_copy_l.values()))))

            # print(
            #     max([
            #         x["since_previous_election_s"]
            #         for x in dict_copy_l.values()
            #     ]))

        if len(elections_3s) > 0:
            print(">>>DEBUG", self.node_name, len(elections_3s),
                  "3s_elections")
            with open(
                    f"./{run_id}_long_running/{self.node_name}_3s_elections_{secrets.token_hex(4)}.json",
                    "w") as f:
                json.dump(elections_3s, f)

        return dict_copy_l

    def log_hash_stats(self, run_id, log_at_count, write_to_db=False):

        # with open(f"./{self.node_name}_hash_stats_{run_id}.json", "w") as f:
        #     json.dump(self.hash_stats, f)

        #

        print(">>>>DEBUG", self.node_name, "started_elections:",
              len(self.hash_stats["blocks"]))

        #dict_copy = self.write_logrunning_elections(run_id)

        if write_to_db:
            if len(self.hash_stats["blocks"]) >= log_at_count:
                self.lock.acquire()
                dict_copy = deepcopy(self.hash_stats["blocks"])
                self.lock.release()
                nano_sql = NanoSql()
                #dict_copy = deepcopy(self.hash_stats["blocks"])
                for block_hash, stats in dict_copy.items():
                    params = [
                        run_id, block_hash, self.node_name, self.version,
                        stats["first_seen"], stats["last_seen"],
                        stats["seen_after_s"], stats["counter"],
                        stats["number"], stats["since_previous_election_s"]
                    ]
                    nano_sql.insert_started_elections(params)
                print(">>>>>> DEBUG",
                      f"Inserted {len(dict_copy)} rows for {self.node_name}")

                self.lock.acquire()
                for block_hash in dict_copy.keys():
                    self.hash_stats["blocks"].pop(block_hash)
                self.lock.release()
        return len(self.hash_stats["blocks"])

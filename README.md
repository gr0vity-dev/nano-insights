# nano-stats
Export nano_node stats every 5s in json format. The main purpose is to import these stats into elastic stash

prerequisites : 
* python3
* nano_node(s) with rpc enabled

nano_node needs rpc access to the folling actions :
* stats
* block_count
* confirmation_active
* confirmation_quorum
* version


## Quickstart :

#### Create a virtual python environment with all dependencies :
<code>$ ./gather_stats_kibana.py</code>

#### Export all stats :
Rename <code>config_gather_stats.json.example</code> to <code>config_gather_stats.json</code>
<code>$ ./setup_venv.sh</code>
All ouput is found in <code>log/.json</code>


#### Optional : Delete virtual python environment
To remove your virtual python environment 
<code>$ ./venv_nano_local.sh delete</code>



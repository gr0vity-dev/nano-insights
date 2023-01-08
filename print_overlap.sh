RUNID=$1
./started_election_stats.py overlap -r $1 && cat ./$1/___OVERLAP___.json

#!/bin/sh

#Script to create and delete a virtualenv to keep dependencies separate from other projects 
# ./setup_venv.sh create 
 # ./setup_venv.sh delete

action=$1

if [ "$action" = "reinstall" ];
then
    pip3 install -U --force-reinstall virtualenv
    action=""
fi

if [ "$action" = "" ]; 
then
    pip3 install virtualenv
    python3 -m venv venv_nano_stats
    . venv_nano_stats/bin/activate

    pip3 install wheel
    pip3 install -r ./requirements.txt --quiet

    echo "A new virtual environment was created. "
    echo "Quickstart to your nano-local network:"
    echo "   $ ./gather_stats_kibana.py"
    
elif [ "$action" = "delete" ];
then 
    . venv_nano_stats/bin/activate
    deactivate    
    rm -rf venv_nano_stats

else
     echo "run ./setup_venv.sh  to create a virtual python environment"
     echo "or"
     echo "run ./setup_venv.sh delete  to delete the virtual python environment"
fi


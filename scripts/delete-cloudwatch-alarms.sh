#!/bin/bash
set -euo pipefail
ALARM_PREFIX=$1
DRY_RUN=${2:-"yes"}
#ALARM_PREFIX example: ml-build-bronze-peter-p-xroyuamhttkm
#run to list alarms to be deleted with certain prefix
#scripts/delete-cloudwatch-alarms.sh  ml-build-bronze-peter-p-xroyuamhttkm yes
oldIFS=$IFS; IFS=$'\t'
for alarm in $(aws cloudwatch describe-alarms --query 'MetricAlarms[*].AlarmName' --alarm-name-prefix $ALARM_PREFIX --output text); do
    if [ "$DRY_RUN" == "no" ]
    then
        echo "Deleting cw alarm: $alarm"
        aws cloudwatch delete-alarms --alarm-names $alarm 1>/dev/null;
    else
      echo "Run with second parameter set to no to delete cw alarm named: $alarm;"
    fi
  sleep 0.5;
done
IFS=$oldIFS
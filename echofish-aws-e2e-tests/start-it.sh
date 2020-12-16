#!/bin/bash

set -ex

mvn -Daws.profile=echofish -Daws.region=us-west-2 -Pit exec:java@create-stack
#!/bin/bash

set -ex

gpg_key="$1"
gpg_key_id="$2"
gpg_key_pw="$3"
github_pat="$4"
github_username="$5"

git checkout @project.branch@
mvn -B build-helper:parse-version -Dsign.keyId=$gpg_key_id -Dsign.keyPass=$gpg_key_pw -Dsign.keyFile=/tmp/gpg.key -Dgit.username=$github_username -Dgit.password=$github_pat -Dresume=false -Dtag='v${parsedVersion.majorVersion}.${parsedVersion.minorVersion}.${parsedVersion.incrementalVersion}' -DreleaseVersion='${parsedVersion.majorVersion}.${parsedVersion.minorVersion}.${parsedVersion.incrementalVersion}' -DdevelopmentVersion='${parsedVersion.majorVersion}.${parsedVersion.minorVersion}.${parsedVersion.nextIncrementalVersion}-SNAPSHOT' release:prepare release:perform


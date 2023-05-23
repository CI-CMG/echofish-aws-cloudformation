#!/bin/bash

set -ex

github_pat="$1"
github_username="$2"

git checkout @project.mainBranch@
mvn -B build-helper:parse-version -Dgit.username=$github_username -Dgit.password=$github_pat -DskipTests -DbranchName='${parsedVersion.majorVersion}.${parsedVersion.minorVersion}' -DdevelopmentVersion='${parsedVersion.majorVersion}.${parsedVersion.nextMinorVersion}.0-SNAPSHOT' release:branch

#!/bin/bash
set -ex

version=$(jq -r '.version' target/dev-resources/stack-properties.json)
stack_name=$(jq -r '.deployStackName' target/dev-resources/stack-properties.json)
bucket_name=$(jq -r '.[] | select(.ParameterKey == "DeploymentBucketName").ParameterValue' target/dev-resources/deployment-parameters.json)

rm -rf target/echofish-aws-cloudformation-$version

unzip -d target target/echofish-aws-cloudformation-$version.zip

aws cloudformation create-stack \
  --profile echofish \
  --stack-name $stack_name \
  --template-body file://target/echofish-aws-cloudformation-$version/deploy/deployment-stack.yaml \
  --parameters file://target/dev-resources/deployment-parameters.json

sleep 60

aws --profile echofish s3 sync target/echofish-aws-cloudformation-$version s3://$bucket_name/
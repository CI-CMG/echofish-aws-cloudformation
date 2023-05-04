# https://gallery.ecr.aws/lambda/python
FROM public.ecr.aws/lambda/python:3.9-arm64

RUN yum -y install gcc
RUN yum -y install python3-devel

COPY requirements.txt .

RUN pip3 install -r requirements.txt --target ${LAMBDA_TASK_ROOT}

COPY lambda.py ${LAMBDA_TASK_ROOT}/

CMD [ "lambda.handler" ]

# https://docs.aws.amazon.com/lambda/latest/dg/images-create.html#images-create-from-base
# aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 123456789012.dkr.ecr.us-east-1.amazonaws.com
# aws ecr create-repository --repository-name hello-world --image-scanning-configuration scanOnPush=true --image-tag-mutability MUTABLE
# docker tag  hello-world:latest 123456789012.dkr.ecr.us-east-1.amazonaws.com/hello-world:latest
# docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/hello-world:latest

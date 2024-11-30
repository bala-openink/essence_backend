 - Flask app run locally using gunicorn WSGI HTTP server, inside lambda using serverless-wsgi
 - Dockerized
 - Deployed as a lambda function
 - Using the Serverless Framework for deployment, https://www.serverless.com/framework/docs/getting-started/
 - AWS API gateway for accessing API

To build, use poetry to manage dependencies
> poetry init
> poetry shell - to get into the venv

To run locally, 

1. Run dynamodb locally,
1.a Download dynamodb - https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocal.DownloadingAndRunning.html#DynamoDBLocal.DownloadingAndRunning.title

1.b Run
> java -Djava.library.path=dynamodb_local/DynamoDBLocal_lib -jar dynamodb_local/DynamoDBLocal.jar -sharedDb

It runs on port 8000 by default (let it be)

To run opensearch locally,

docker run -d \
  --name opensearch-local \
  -p 9200:9200 -p 9300:9300 \
  -v opensearch-data:/usr/share/opensearch/data \
  -e "discovery.type=single-node" \
  -e "DISABLE_SECURITY_PLUGIN=true" \
  opensearchproject/opensearch:latest


2. Run gunicorn server locally on port 4000 (not using docker for faster troubleshooting)
> gunicorn --timeout 600 --bind 0.0.0.0:4000 --workers 1  app:app

To point to the local server via ngrok
> ngrok http http://localhost:4000

To deploy in AWS lambda

1. Build the docker image. Note the platform linux/amd64 - This is needed for the lambda's unix flavor
docker buildx build --no-cache --platform linux/amd64 -t ocs-backend --load .

2. Deploy using serverless
 - for full deploy
> serverless deploy

 - for deploying only the function, without docker or env changes. Use this, as its fast
> serverless deploy function -f app --stage dev 
> serverless deploy function -f parseFeedsScheduled --stage dev


Other useful docker commands

# To stop and remove the container
docker stop opensearch-local
docker rm opensearch-local

# To check logs and volume details
docker logs opensearch-local

# To create a volume
docker volume create opensearch-data

# Check volume details
docker volume inspect opensearch-data

# Remove volume
docker volume rm opensearch-data

# After container is running, check the mount
docker inspect opensearch-local | grep -A 10 "Mounts"

docker ps -a | grep opensearch
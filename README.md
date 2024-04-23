Flask app run locally using gunicorn WSGI HTTP server, inside lambda using serverless-wsgi
Dockerized
Deployed as a lambda function
Using the Serverless Framework for deployment, https://www.serverless.com/framework/docs/getting-started/
AWS API gateway for accessing API


To run locally, 

1. Run dynamodb locally,
1.a Download dynamodb - https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/DynamoDBLocal.DownloadingAndRunning.html#DynamoDBLocal.DownloadingAndRunning.title

1.b Run
>> java -Djava.library.path=dynamodb_local/DynamoDBLocal_lib -jar dynamodb_local/DynamoDBLocal.jar -sharedDb

It runs on port 8000 by default (let it be)

2. Run gunicorn server locally on port 4000 (not using docker for faster troubleshooting)
>> gunicorn -b 0.0.0.0:4000 app:app

To deploy in AWS lambda

1. Build the docker image
docker build -t ocs-backend .

2. Deploy using serverless
 - for full deploy
serverless deploy

 - for deploying only the function, without docker or env changes. Use this, as its fast
serverless deploy -f app
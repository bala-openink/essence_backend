import boto3
from botocore.exceptions import ClientError
from services import utilities

AWS_REGION = utilities.get_secret('AWS_REGION', 'us-west-1')
SENDER_EMAIL = utilities.get_secret('SENDER_EMAIL', 'jackson@openink.co')

def send_email(recipient, subject, body):
    client = boto3.client('ses', region_name=AWS_REGION)
    
    try:
        response = client.send_email(
            Destination={
                'ToAddresses': [recipient],
            },
            Message={
                'Body': {
                    'Text': {
                        'Charset': 'UTF-8',
                        'Data': body,
                    },
                },
                'Subject': {
                    'Charset': 'UTF-8',
                    'Data': subject,
                },
            },
            Source=SENDER_EMAIL,
        )
    except ClientError as e:
        print(f"Error sending email: {e.response['Error']['Message']}")
    else:
        print(f"Email sent! Message ID: {response['MessageId']}")
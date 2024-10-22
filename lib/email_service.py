import boto3
from botocore.exceptions import ClientError
from config import SENDER_EMAIL, AWS_REGION_FOR_EMAIL

def send_email(recipient, subject, body):
    client = boto3.client('ses', region_name=AWS_REGION_FOR_EMAIL)
    
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
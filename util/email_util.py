import boto3
from botocore.exceptions import ClientError
import config

def send_email(recipient, subject, body):
    client = boto3.client('ses', region_name=config.AWS_REGION_FOR_EMAIL)
    
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
            Source=config.SENDER_EMAIL,
        )
    except ClientError as e:
        print(f"Error sending email: {e.response['Error']['Message']}")
    else:
        print(f"Email sent! Message ID: {response['MessageId']}")

def send_new_user_notification(email):
    subject = f"Essence {config.STAGE}: New user tried to register"
    body = f"A new user has tried to register with email: {email}"
    send_email(config.ADMIN_EMAIL, subject, body)

def send_processing_summary_email(batch):
    subject = f"Env::{config.STAGE}, Essence Feed Processing Summary"
    stages = ["stage1", "stage2", "stage3"]
    body = "Feed processing completed.\n\n"

    for stage in stages:
        # Fetch the correct column names from the batch record
        total_processed = batch.get(f"{stage}_processed", 0)
        total_skipped = batch.get(f"{stage}_skipped", 0)
        errors = batch.get(f"{stage}_errors", [])

        # Determine whether to use "articles" or "users"
        entity = "articles" if stage in ["stage1", "stage2"] else "users"

        body += f"Stage {stage}:\n"
        body += f"Total {entity} processed: {total_processed}\n"
        body += f"Total {entity} skipped: {total_skipped}\n"
        body += f"Total {entity} with errors: {len(errors)}\n\n"

        if errors:
            body += f"{entity.capitalize()} with errors:\n"
            for error in errors:
                body += f"- Error: {error}\n"
            body += "\n"

    send_email(config.ADMIN_EMAIL, subject, body)

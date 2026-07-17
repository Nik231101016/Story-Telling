import json
import boto3
import uuid
from datetime import datetime

s3 = boto3.client('s3')
polly = boto3.client('polly')
dynamodb = boto3.resource('dynamodb')

# 🔴 CHANGE THESE TO MATCH YOUR EXACT OUTBOUND BUCKET AND TABLE
AUDIO_BUCKET = "talesmith-audio-outbound-nikhil"
TABLE_NAME = "TalesmithCatalog"

# Common CORS response headers so your EC2 website can call this API
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
}

def lambda_handler(event, context):
    # Handle preflight OPTIONS requests from the browser
    if event.get('httpMethod') == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': ''
        }
        
    try:
        http_method = event.get('httpMethod')
        table = dynamodb.Table(TABLE_NAME)

        # ==========================================
        # 1. GET: FETCH ALL STORY ENTRIES
        # ==========================================
        if http_method == 'GET':
            print("Fetching story list from DynamoDB...")
            scan_response = table.scan()
            stories = scan_response.get('Items', [])
            
            # Sort stories by Timestamp descending (newest first)
            stories.sort(key=lambda x: x.get('Timestamp', ''), reverse=True)
            
            return {
                'statusCode': 200,
                'headers': CORS_HEADERS,
                'body': json.dumps(stories)
            }

        # ==========================================
        # 2. POST: UPLOAD AND FORGE NEW STORY
        # ==========================================
        elif http_method == 'POST':
            # Parse incoming body payload
            body = json.loads(event.get('body', '{}'))
            story_text = body.get('textContent', '').strip()
            filename = body.get('filename', 'untitled_story.txt')
            
            if not story_text:
                return {
                    'statusCode': 400,
                    'headers': CORS_HEADERS,
                    'body': json.dumps({'error': 'No story text content provided.'})
                }

            # Generate clean ID and human-readable title
            story_id = str(uuid.uuid4())[:8]
            story_title = filename.replace('.txt', '').replace('_', ' ').replace('-', ' ')

            print(f"Forging story: {story_title} (ID: {story_id}). Text length: {len(story_text)}")

            # Stream text through Amazon Polly Voice Synthesis
            polly_response = polly.synthesize_speech(
                Text=story_text,
                OutputFormat='mp3',
                VoiceId='Joanna' # Warm, clear storyteller voice perfect for kids
            )

            # Upload the generated MP3 bytes to S3
            audio_key = f"{story_id}.mp3"
            s3.put_object(
                Bucket=AUDIO_BUCKET,
                Key=audio_key,
                Body=polly_response['AudioStream'].read(),
                ContentType='audio/mpeg'
            )
            print(f"Audio master synthesized and saved to S3 target: {audio_key}")

            # Build the public streaming link
            audio_url = f"https://{AUDIO_BUCKET}.s3.amazonaws.com/{audio_key}"
            current_time_str = datetime.utcnow().isoformat()

            # Index everything inside the DynamoDB Meta Catalog
            story_item = {
                'StoryId': story_id,
                'Title': story_title,
                'TextContent': story_text,
                'AudioUrl': audio_url,
                'Timestamp': current_time_str
            }
            
            table.put_item(Item=story_item)
            print("Metadata catalog index ledger entry logged inside DynamoDB successfully.")
            
            return {
                'statusCode': 200,
                'headers': CORS_HEADERS,
                'body': json.dumps({
                    'message': 'Story forged successfully!',
                    'story': story_item
                })
            }

        else:
            return {
                'statusCode': 405,
                'headers': CORS_HEADERS,
                'body': json.dumps({'error': f'Method {http_method} not allowed.'})
            }

    except Exception as e:
        print(f"PIPELINE CRASH LOG DETAILS: {str(e)}")
        return {
            'statusCode': 500,
            'headers': CORS_HEADERS,
            'body': json.dumps({'error': f"Pipeline Failed: {str(e)}"})
        }
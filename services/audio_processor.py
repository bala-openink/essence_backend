from gtts import gTTS

import time
import os
import boto3
from concurrent.futures import ThreadPoolExecutor, as_completed

from services import util
import config

# def text_to_audio_fb(video_id, text):
#     model = VitsModel.from_pretrained("facebook/mms-tts-eng")
#     tokenizer = AutoTokenizer.from_pretrained("facebook/mms-tts-eng")

#     inputs = tokenizer(text, return_tensors="pt")

#     with torch.no_grad():
#         output = model(**inputs).waveform

#     # Save the audio in WAV format using torchaudio
#     summary_audio_file = f"/tmp/{video_id}_summary.wav"
#     torchaudio.save(summary_audio_file, output, model.config.sampling_rate)

#     # Upload the audio summary file to s3
#     index, url = util.upload_to_s3(summary_audio_file, config.S3_BUCKET_AUDIO_OUTPUT, f"{video_id}/summary/{summary_audio_file}")

#     return url, summary_audio_file

polly = boto3.client('polly', region_name='us-east-1')
output_format = "mp3"

# Set the voice ID (for a list of available voices, refer to the documentation)
voice_id = "Matthew"
engine = "neural"


def text_to_audio_gtts(id, text):
    summary_audio_file = f"{id}_summary.mp3"
    tts = gTTS(text, lang='en', slow=False)
    file_path = f"/tmp/{summary_audio_file}"
    tts.save(file_path)

    folder_by_day = time.strftime("%Y-%m-%d", time.localtime()) # One folder per day
    index, url = util.upload_to_s3(file_path, config.S3_BUCKET_AUDIO_OUTPUT, f"{folder_by_day}/{id}/summary/{summary_audio_file}")
    return url, file_path

def text_to_audio_polly(id, text):
    response = polly.synthesize_speech(
    Text=text,
    OutputFormat=output_format,
    VoiceId=voice_id,
    Engine=engine
    )

    summary_audio_file = f"{id}_summary.mp3"
    file_path = f"/tmp/{summary_audio_file}"
    file = open(file_path, "wb")
    file.write(response["AudioStream"].read())
    file.close()

    folder_by_day = time.strftime("%Y-%m-%d", time.localtime()) # One folder per day
    index, url = util.upload_to_s3(file_path, config.S3_BUCKET_AUDIO_OUTPUT, f"{folder_by_day}/{id}/summary/{summary_audio_file}")
    return url, file_path

import logging
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import numpy as np
from moviepy import VideoClip, ImageClip, TextClip, AudioFileClip, CompositeAudioClip, CompositeVideoClip, ColorClip
from moviepy.video.compositing.CompositeVideoClip import concatenate_videoclips
from moviepy.audio.AudioClip import concatenate_audioclips

import os
import shutil
import tempfile
from datetime import datetime
from lib.log import logger
from util import llm_util, file_util
from services import podcaster
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

class VideoGenerator:
    def __init__(self):
        """Initialize video generator with default settings"""
        self.settings = {
            # Video settings
            'width': 1280,
            'height': 720,
            'fps': 24,
            'transition_duration': 1,    # seconds
            'output_format': 'mp4',
            
            # Subtitle settings
            'subtitle_font': 'Arial',
            'subtitle_size': 40,
            'subtitle_stroke_width': 1,
            'speaker_colors': {
                'male': 'lightblue',
                'female': 'pink'
            },
            
            # Audio settings
            'background_music_volume': 0.1,
            'speech_volume': 1.0,
            'music_fade_duration': 2.0,
            'ducking_percentage': 0.7,
            
            # Speech timing
            'words_per_minute': 150,  # average speaking rate
        }
        self.temp_dir = tempfile.mkdtemp()
        logger.info(f"Initialized VideoGenerator with temp directory: {self.temp_dir}")

    def generate_video(
        self, 
        conversation: List[Dict], 
        articles: List[Dict],
        background_music_path: Optional[str] = None,
        output_path: Optional[str] = None,
        language: str = "en",
        region: str = "UK"
    ) -> str:
        """
        Main method to generate video from conversation and articles
        """
        try:
            logger.info("Starting video generation process")
            self._validate_inputs(conversation)

            # Generate audio from conversation
            conversation_audio = podcaster.create_audio_for_conversation(
                conversation=conversation,
                language=language,
                add_background=False
            )

            # Prepare images for each conversation segment
            conversation_with_images = self._find_images_for_conversation(conversation, articles)
            image_paths = self._prepare_images(conversation_with_images, region)
            subtitles = self._prepare_subtitles(conversation_with_images)
            video_sequence = self._create_image_sequence(image_paths, subtitles)

            # Prepare subtitles
            total_duration = sum(sub['duration'] for sub in subtitles)
            # subtitle_clips = self._create_subtitle_clips(subtitles, total_duration)

            # Convert conversation audio to MoviePy audio clip
            temp_audio_path = os.path.join(self.temp_dir, "conversation_audio.wav")
            conversation_audio.export(temp_audio_path, format="wav")
            conversation_audio_clip = AudioFileClip(temp_audio_path)

            # Prepare background music if provided
            if background_music_path:
                bg_music = self._prepare_audio(total_duration, background_music_path)
                if bg_music:
                    # Combine conversation audio with background music
                    final_audio = CompositeAudioClip([
                        conversation_audio_clip,
                        bg_music
                    ])
                else:
                    final_audio = conversation_audio_clip
            else:
                final_audio = conversation_audio_clip

            # Combine all elements
            final_video = CompositeVideoClip([
                video_sequence
            ]).with_audio(final_audio)

            # Generate output path if not provided
            if not output_path:
                output_path = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{self.settings['output_format']}"

            # Write final video
            logger.info(f"Writing video to {output_path}")
            final_video.write_videofile(
                output_path,
                fps=self.settings['fps'],
                codec='libx264',
                audio_codec='aac',
                preset='veryfast',  # Faster encoding
                threads=4,        # Utilize multiple CPU cores
                bitrate='1500k'   # Lower bitrate for faster processing
            )

            return output_path

        except Exception as e:
            logger.error(f"Error generating video: {str(e)}")
            raise
        finally:
            self._cleanup_temp_files()

    def _prepare_images(self, conversation: List[Dict], region: str) -> List[str]:
        """Prepare and validate images for each conversation segment"""
        logger.info("Preparing images for video")
        image_paths = []
        fallback_image = "resources/images/ecommerce.jpg"

        for idx, segment in enumerate(conversation):
            image_path = f"{self.temp_dir}/image_{idx}.jpg"
            image_saved = False

            try:
                if idx == 0 or idx == len(conversation) - 1:
                    # Use podcast image for the first segment
                    image_path = "resources/images/podcastNew.png"
                    if os.path.exists(image_path):
                        # Verify the image can be opened
                        ImageClip(image_path)
                        image_saved = True
                    else:
                        logger.warning("Podcast image not found, falling back to generated image")
                        image_saved = False

                if not image_saved:
                    # Use image from conversation segment if available
                    image_url = segment['image']
                    if image_url:
                        image_saved = file_util.save_image(image_url, image_path)
                        # Verify the saved image can be opened
                        ImageClip(image_path)
                
                if not image_saved:
                    # Generate image using DALL-E based on conversation text
                    prompt = f"Visual representation for: {segment['text']}"
                    result = llm_util.generate_image_from_text(prompt, region=region)
                    logger.debug(f"Generated image for conversation segment {idx}: {result}")
                    if result and 'url' in result:
                        image_saved = file_util.save_image(result['url'], image_path)
                        # Verify the generated image can be opened
                        ImageClip(image_path)
                    else:
                        logger.warning(f"Failed to generate image for conversation segment {idx}")
                
                if not image_saved:
                    logger.info(f"Using fallback image for segment {idx}")
                    image_path = fallback_image
                    # Verify fallback image exists and can be opened
                    if os.path.exists(fallback_image):
                        ImageClip(fallback_image)
                        image_saved = True
                    else:
                        raise ValueError("Fallback image not found")

                logger.debug(f"Using image for conversation segment {idx}: {image_path}")
                image_paths.append(image_path)

            except Exception as e:
                logger.error(f"Error processing image for segment {idx}: {str(e)}")
                # Use fallback image as last resort
                image_paths.append(fallback_image)

        if not image_paths:
            raise ValueError("No valid images could be prepared")

        return image_paths

    def _create_image_sequence(self, image_paths: List[str], subtitles: List[Dict]) -> VideoClip:
        """Create video sequence from images with Ken Burns effect and dissolve transitions"""
        logger.info("Creating image sequence with Ken Burns effect and transitions")
        clips = []

        for idx, image_path in enumerate(image_paths):
            # Get the duration from the corresponding subtitle
            duration = subtitles[idx]['duration']

            # Create base image clip with the correct duration
            img_clip = ImageClip(image_path, duration=duration)

            # Apply Ken Burns effect
            ken_burns_clip = self._apply_ken_burns_effect(img_clip)

            clips.append(ken_burns_clip)

        # Add dissolve transitions between clips
        final_clips = []
        for i, clip in enumerate(clips):
            if i > 0:  # Add dissolve transition
                transition_duration = self.settings['transition_duration']
                previous_clip = final_clips[-1]

                # Create a transition clip by overlaying the current clip with the previous one
                transition_clip = CompositeVideoClip([
                    previous_clip.with_end(previous_clip.duration + transition_duration),
                    clip.with_start(previous_clip.duration).with_duration(clip.duration + transition_duration)
                ], size=(self.settings['width'], self.settings['height']))

                final_clips[-1] = transition_clip
                logger.debug(f"Added transition clip for {previous_clip.duration} to {clip.duration}")
            else:
                final_clips.append(clip)

        return concatenate_videoclips(final_clips, method="compose")

    def _prepare_subtitles(self, conversation: List[Dict]) -> List[Dict]:
        """Convert conversation to timed subtitles"""
        logger.info("Preparing subtitles")
        subtitles = []
        current_time = 0
        
        for segment in conversation:
            duration = self._estimate_speech_duration(segment['text'])
            subtitles.append({
                'start': current_time,
                'end': current_time + duration,
                'text': segment['text'],
                'speaker': segment['speaker'],
                'duration': duration
            })
            current_time += duration
        logger.debug(f"Prepared subtitles: {len(subtitles)}")
        return subtitles

    def _create_subtitle_clips(self, subtitles: List[Dict], duration: float) -> CompositeVideoClip:
        """Create subtitle clips with proper styling"""
        logger.info("Creating subtitle clips")
        subtitle_clips = []

        for subtitle in subtitles:
            color = self.settings['speaker_colors'].get(
                subtitle['speaker'].lower(), 
                'white'
            )
            
            # Create a text clip
            text_clip = TextClip(
                text=subtitle['text'],
                font=self.settings['subtitle_font'],
                font_size=self.settings['subtitle_size'],
                color='white',
                stroke_color='white',
                stroke_width=1,
                method='caption',
                size=(self.settings['width'] - 40, None)  # Add padding by reducing width
            )
            
            text_clip = text_clip.with_start(subtitle['start']).with_duration(subtitle['duration']).with_position(('center', 'bottom')).with_background_color(color=(0, 0, 0), opacity=0.5)

            subtitle_clips.append(text_clip)

        logger.debug(f"Created subtitle clips: {len(subtitle_clips)}")
        return CompositeVideoClip(subtitle_clips)

    def _apply_ken_burns_effect(self, image_clip: ImageClip) -> VideoClip:
        """Apply Ken Burns effect to static image with random movement patterns"""
        w, h = image_clip.size
        video_w, video_h = self.settings['width'], self.settings['height']

        # Calculate scale to fit the video size
        scale_factor = max(video_w / w, video_h / h)
        scaled_w, scaled_h = int(w * scale_factor), int(h * scale_factor)

        # Randomly choose effect parameters
        import random
        effect_type = random.choice(['zoom_in', 'zoom_out', 'pan_zoom'])
        
        # Define scale ranges based on effect type
        if effect_type == 'zoom_in':
            start_scale, end_scale = 1.0, 1.2
        elif effect_type == 'zoom_out':
            start_scale, end_scale = 1.2, 1.0
        else:  # pan_zoom
            start_scale, end_scale = 1.1, 1.1

        # Random pan directions (-1 to 1)
        pan_x = random.uniform(-0.1, 0.1)
        pan_y = random.uniform(-0.1, 0.1)

        def make_frame(t):
            progress = t / image_clip.duration
            scale = start_scale + (end_scale - start_scale) * progress

            # Calculate scaled dimensions
            current_w = int(scaled_w * scale)
            current_h = int(scaled_h * scale)

            # Calculate position with panning
            if effect_type == 'pan_zoom':
                x = (video_w - current_w) / 2 + (pan_x * video_w * progress)
                y = (video_h - current_h) / 2 + (pan_y * video_h * progress)
            else:
                x = (video_w - current_w) / 2
                y = (video_h - current_h) / 2

            # Ensure image stays within frame bounds
            x = max(min(x, 0), video_w - current_w)
            y = max(min(y, 0), video_h - current_h)

            return image_clip.resized((current_w, current_h)).with_position((x, y)).get_frame(t)

        logger.debug(f"Creating ken burns effect: {effect_type} for duration: {image_clip.duration}")
        return VideoClip(make_frame, duration=image_clip.duration)

    def _estimate_speech_duration(self, text: str) -> float:
        """Estimate duration of spoken text in seconds"""
        words = len(text.split())
        return (words / self.settings['words_per_minute']) * 60

    def _prepare_audio(self, duration: float, background_music_path: str) -> AudioFileClip:
        """Prepare background music track"""
        logger.info("Preparing background music")
        try:
            audio = AudioFileClip(background_music_path)
            
            # Loop if needed
            if audio.duration < duration:
                n_loops = int(np.ceil(duration / audio.duration))
                audio = concatenate_audioclips([audio] * n_loops)
            
            # Trim to exact duration
            audio = audio.with_duration(duration)
            
            # Apply fade effects
            audio = audio.audio_fadein(self.settings['music_fade_duration'])
            audio = audio.audio_fadeout(self.settings['music_fade_duration'])
            
            # Set volume
            return audio.volumex(self.settings['background_music_volume'])
            
        except Exception as e:
            logger.error(f"Error preparing background music: {str(e)}")
            return None

    @staticmethod
    def _validate_inputs(conversation: List[Dict]):
        """Validate input data structure and content"""
        if not conversation or not isinstance(conversation, list):
            raise ValueError("Invalid conversation format")
            
        for segment in conversation:
            if not all(key in segment for key in ['speaker', 'text']):
                raise ValueError("Invalid conversation segment format")
                
    def _cleanup_temp_files(self):
        """Clean up temporary files"""
        try:
            if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                logger.info(f"Cleaned up temporary directory: {self.temp_dir}")
        except Exception as e:
            logger.error(f"Error cleaning up temporary files: {str(e)}")

    def _find_images_for_conversation(self, conversation: List[Dict], articles: List[Dict]) -> List[Dict]:
        """Find images for each conversation segment from articles"""
        logger.info("Finding images for conversation segments")
        
        # Extract summaries from articles
        article_summaries = [article['summary_50'] for article in articles]
        article_images = [article['image'] for article in articles]

        # Prepare a list to store conversation segments with images
        conversation_with_images = []

        # Initialize TF-IDF Vectorizer with the vocabulary of article summaries
        vectorizer = TfidfVectorizer().fit(article_summaries)

        # Vectorize the article summaries
        article_vectors = vectorizer.transform(article_summaries)

        for segment in conversation:
            # Vectorize the conversation text
            segment_vector = vectorizer.transform([segment['text']])

            # Compute cosine similarity between the segment and each article summary
            similarities = cosine_similarity(segment_vector, article_vectors).flatten()

            # Find the index of the most similar article
            best_match_index = similarities.argmax()

            # Add the image from the best matching article to the conversation segment
            segment_with_image = segment.copy()
            segment_with_image['image'] = article_images[best_match_index]

            conversation_with_images.append(segment_with_image)

        return conversation_with_images
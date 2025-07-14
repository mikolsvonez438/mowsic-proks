from flask import Flask, request, jsonify, send_file, Response
import yt_dlp
import requests
from urllib.parse import unquote, quote
from flask_cors import CORS
from random import choice
import os
import json
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# List of Invidious instances to try as fallbacks
INVIDIOUS_INSTANCES = [
    "https://invidious.snopyta.org",
    "https://yewtu.be",
    "https://invidious.kavin.rocks",
    "https://vid.puffyan.us",
    "https://invidious.namazso.eu",
    "https://inv.riverside.rocks"
]

# Configure yt-dlp with more resilient options
YDL_OPTS_BASE = {
    'quiet': True,
    'no_warnings': True,
    'ignoreerrors': True,
    'nocheckcertificate': True,
    'geo_bypass': True,
    'extractor_retries': 3,
    'socket_timeout': 30,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    }
}

def get_video_id_from_url(url):
    """Extract video ID from YouTube URL"""
    if 'youtube.com/watch?v=' in url:
        return url.split('youtube.com/watch?v=')[1].split('&')[0]
    elif 'youtu.be/' in url:
        return url.split('youtu.be/')[1].split('?')[0]
    return None

def try_invidious_api(video_id):
    """Try to get video info from Invidious API"""
    for instance in INVIDIOUS_INSTANCES:
        try:
            api_url = f"{instance}/api/v1/videos/{video_id}"
            logger.info(f"Trying Invidious instance: {instance} for video {video_id}")
            
            response = requests.get(api_url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                
                # Find the best audio format
                formats = data.get('adaptiveFormats', [])
                if not formats:
                    continue
                
                # Sort by quality (prefer audio)
                audio_formats = [f for f in formats if f.get('type', '').startswith('audio')]
                if audio_formats:
                    best_format = max(audio_formats, key=lambda x: x.get('bitrate', 0))
                else:
                    # If no audio formats, get video format
                    best_format = max(formats, key=lambda x: x.get('bitrate', 0))
                
                stream_url = best_format.get('url')
                if stream_url:
                    logger.info(f"Successfully got stream URL from Invidious: {instance}")
                    return {
                        "stream_url": stream_url,
                        "title": data.get('title', 'Unknown Title'),
                        "source": "invidious"
                    }
            
        except Exception as e:
            logger.error(f"Error with Invidious instance {instance}: {str(e)}")
            continue
    
    return None

@app.route("/api/search")
def api_search():
    query = request.args.get("q")
    if not query:
        return jsonify({"error": "Missing query"}), 400
    
    # Try direct YouTube search first
    try:
        ydl_opts = YDL_OPTS_BASE.copy()
        ydl_opts.update({
            'extract_flat': True,
            'force_generic_extractor': True,
            'skip_download': True,
        })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            results = ydl.extract_info(f"ytsearch10:{query}", download=False)
            entries = results.get("entries", [])
            
            # Filter out None entries
            entries = [entry for entry in entries if entry is not None]
            
            if entries:
                logger.info(f"Found {len(entries)} results for query: {query}")
                return jsonify(entries)
    except Exception as e:
        logger.error(f"YouTube search error: {str(e)}")
    
    # Fallback to Invidious search if YouTube fails
    try:
        instance = choice(INVIDIOUS_INSTANCES)
        search_url = f"{instance}/api/v1/search?q={quote(query)}&type=video"
        logger.info(f"Trying Invidious search: {instance}")
        
        response = requests.get(search_url, timeout=10)
        if response.status_code == 200:
            invidious_results = response.json()
            
            # Convert to format similar to yt-dlp results
            entries = []
            for result in invidious_results:
                entries.append({
                    "id": result.get("videoId"),
                    "title": result.get("title"),
                    "url": f"https://www.youtube.com/watch?v={result.get('videoId')}",
                    "ie_key": "Youtube",
                    "duration": result.get("lengthSeconds"),
                    "view_count": result.get("viewCount"),
                    "thumbnail": result.get("videoThumbnails", [{}])[0].get("url"),
                    "_type": "url"
                })
            
            logger.info(f"Found {len(entries)} results from Invidious search")
            return jsonify(entries)
    except Exception as e:
        logger.error(f"Invidious search error: {str(e)}")
    
    return jsonify({"error": "No results found"}), 404

@app.route("/api/stream_url")
def api_stream_url():
    video_url = request.args.get("url")
    if not video_url:
        return jsonify({"error": "Missing video URL"}), 400
    
    logger.info(f"Fetching stream URL for: {video_url}")
    video_id = get_video_id_from_url(video_url)
    
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Try direct YouTube extraction first
    formats_to_try = [
        'bestaudio[ext=m4a]/bestaudio/best[height<=480]/best',
        'bestaudio/best[height<=480]/best',
        'best[ext=mp4]/best'
    ]
    
    for format_string in formats_to_try:
        try:
            ydl_opts = YDL_OPTS_BASE.copy()
            ydl_opts.update({
                'format': format_string,
                'noplaylist': True
            })
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
                if not info:
                    logger.warning(f"No info extracted for {video_url}")
                    continue
                    
                stream_url = info.get('url')
                if not stream_url:
                    logger.warning(f"No stream URL found in format {format_string}")
                    continue
                    
                title = info.get("title", "Untitled")
                logger.info(f"Successfully extracted stream URL for: {title}")
                return jsonify({"stream_url": stream_url, "title": title, "source": "youtube"})
                
        except Exception as e:
            logger.error(f"Error extracting with format {format_string}: {str(e)}")
    
    # If YouTube extraction fails, try Invidious
    logger.info(f"YouTube extraction failed, trying Invidious for video ID: {video_id}")
    invidious_result = try_invidious_api(video_id)
    
    if invidious_result:
        return jsonify(invidious_result)
    
    # If all methods fail
    return jsonify({"error": "Could not extract stream URL. Video may be unavailable or restricted."}), 500

@app.route("/api/proxy")
def api_proxy():
    raw_url = request.args.get("url")
    if not raw_url:
        return "Missing URL", 400
    
    video_url = unquote(raw_url)
    
    # Rotate user agents to avoid detection
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36'
    ]
    
    headers = {
        'User-Agent': choice(user_agents),
        'Accept': '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.youtube.com/'
    }
    
    def generate():
        try:
            with requests.get(video_url, stream=True, headers=headers, timeout=30) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
        except Exception as e:
            logger.error(f"Proxy streaming error: {str(e)}")
            yield b''
    
    return Response(generate(), content_type='video/mp4')

@app.route("/api/related")
def api_related():
    video_url = request.args.get("url")
    if not video_url:
        return jsonify({"error": "Missing video URL"}), 400
    
    video_id = get_video_id_from_url(video_url)
    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    # Try direct YouTube extraction first
    try:
        ydl_opts = YDL_OPTS_BASE.copy()
        ydl_opts.update({
            'extract_flat': False,
            'skip_download': True,
        })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            if info:
                related = info.get("related_videos", [])
                candidates = [v for v in related if v.get("id")]
                
                if candidates:
                    selected = choice(candidates)
                    return jsonify({
                        "id": selected["id"],
                        "title": selected.get("title", "Untitled")
                    })
    except Exception as e:
        logger.error(f"YouTube related videos error: {str(e)}")
    
    # Fallback to Invidious for related videos
    try:
        instance = choice(INVIDIOUS_INSTANCES)
        api_url = f"{instance}/api/v1/videos/{video_id}"
        
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            recommended = data.get('recommendedVideos', [])
            
            if recommended:
                selected = choice(recommended)
                return jsonify({
                    "id": selected.get("videoId"),
                    "title": selected.get("title", "Untitled")
                })
    except Exception as e:
        logger.error(f"Invidious related videos error: {str(e)}")
    
    # Fallback to a popular music video if all else fails
    return jsonify({
        "id": "dQw4w9WgXcQ",  # Never Gonna Give You Up
        "title": "Recommended Music"
    })

@app.route("/")
def index():
    try:
        return send_file("templates/index.html")
    except Exception as e:
        logger.error(f"Error serving index: {str(e)}")
        return f"Error: {str(e)}", 500

# Health check endpoint for Render
@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

from flask import Flask, request, jsonify, send_file, Response
import yt_dlp
import requests
from urllib.parse import unquote
from flask_cors import CORS
from random import choice
import os
import time
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

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

@app.route("/api/search")
def api_search():
    query = request.args.get("q")
    if not query:
        return jsonify({"error": "Missing query"}), 400
    
    ydl_opts = YDL_OPTS_BASE.copy()
    ydl_opts.update({
        'extract_flat': True,
        'force_generic_extractor': True,
        'skip_download': True,
    })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            results = ydl.extract_info(f"ytsearch10:{query}", download=False)
            entries = results.get("entries", [])
            
            # Filter out None entries (which can happen with errors)
            entries = [entry for entry in entries if entry is not None]
            
            if not entries:
                logger.warning(f"No results found for query: {query}")
                return jsonify({"error": "No results found"}), 404
                
            return jsonify(entries)
    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        return jsonify({"error": f"Search failed: {str(e)}"}), 500

@app.route("/api/stream_url")
def api_stream_url():
    video_url = request.args.get("url")
    if not video_url:
        return jsonify({"error": "Missing video URL"}), 400
    
    logger.info(f"Fetching stream URL for: {video_url}")
    
    # Try multiple formats in case one fails
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
                return jsonify({"stream_url": stream_url, "title": title})
                
        except Exception as e:
            logger.error(f"Error extracting with format {format_string}: {str(e)}")
            # Continue to next format
    
    # If we get here, all formats failed
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
                r.raise_for_status()  # Raise an exception for 4XX/5XX responses
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
        except Exception as e:
            logger.error(f"Proxy streaming error: {str(e)}")
            yield b''  # Return empty to end stream
    
    return Response(generate(), content_type='video/mp4')

@app.route("/api/related")
def api_related():
    video_url = request.args.get("url")
    if not video_url:
        return jsonify({"error": "Missing video URL"}), 400
    
    ydl_opts = YDL_OPTS_BASE.copy()
    ydl_opts.update({
        'extract_flat': False,
        'skip_download': True,
    })
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            
            if not info:
                return jsonify({"error": "Could not extract video info"}), 500
                
            related = info.get("related_videos", [])
            candidates = [v for v in related if v.get("id")]
            
            if not candidates:
                # Try to return at least something
                return jsonify({
                    "id": "dQw4w9WgXcQ",  # Fallback video if nothing else works
                    "title": "Recommended Music"
                })
            
            selected = choice(candidates)
            return jsonify({
                "id": selected["id"],
                "title": selected.get("title", "Untitled")
            })
            
    except Exception as e:
        logger.error(f"Related videos error: {str(e)}")
        return jsonify({"error": str(e)}), 500

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

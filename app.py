from flask import Flask, request, jsonify, send_file, Response
import yt_dlp
import requests
from urllib.parse import unquote
from flask_cors import CORS
from random import choice
import os

app = Flask(__name__)
CORS(app)

@app.route("/api/search")
def api_search():
    query = request.args.get("q")
    if not query:
        return jsonify({"error": "Missing query"}), 400

    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
        'force_generic_extractor': True,
        'skip_download': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        results = ydl.extract_info(f"ytsearch10:{query}", download=False)
        entries = results.get("entries", [])

    return jsonify(entries)

@app.route("/api/stream_url")
def api_stream_url():
    video_url = request.args.get("url")
    if not video_url:
        return jsonify({"error": "Missing video URL"}), 400

    ydl_opts = {
        'quiet': True,
        'format': 'best[ext=mp4]',
        'noplaylist': True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            stream_url = info['url']
            title = info.get("title", "Untitled")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"stream_url": stream_url, "title": title})

@app.route("/api/proxy")
def api_proxy():
    raw_url = request.args.get("url")
    if not raw_url:
        return "Missing URL", 400
    video_url = unquote(raw_url)

    headers = {'User-Agent': 'Mozilla/5.0'}
    def generate():
        with requests.get(video_url, stream=True, headers=headers) as r:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk

    return Response(generate(), content_type='video/mp4')

@app.route("/api/related")
def api_related():
    video_url = request.args.get("url")
    if not video_url:
        return jsonify({"error": "Missing video URL"}), 400

    ydl_opts = {
        'quiet': True,
        'extract_flat': False,
        'skip_download': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            related = info.get("related_videos", [])
            candidates = [v for v in related if v.get("id")]

            if not candidates:
                return jsonify({"error": "No related videos found"}), 404

            selected = choice(candidates)
            return jsonify({
                "id": selected["id"],
                "title": selected.get("title", "Untitled")
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/")
def index():
    return send_file("templates/index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

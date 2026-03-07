"""
YouTube AI Video Summarizer
Flask + Groq API + youtube-transcript-api
"""

import re
import os
import tempfile
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from groq import Groq
import yt_dlp
import webvtt
import uuid

# Try loading environment variables from a .env file (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # If python-dotenv is not installed, expect env vars to be set externally.
    pass


# ─────────────────────────────────────
# Flask Setup
# ─────────────────────────────────────
app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────
# Groq Setup
# ─────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env or environment variables.")

client = Groq(api_key=GROQ_API_KEY)

MODEL = "llama-3.3-70b-versatile"


# ─────────────────────────────────────
# Call Groq LLM
# ─────────────────────────────────────
def call_llm(prompt):

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    return response.choices[0].message.content


# ─────────────────────────────────────
# Extract YouTube Video ID
# ─────────────────────────────────────
def extract_video_id(url):

    patterns = [
        r"v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"shorts/([a-zA-Z0-9_-]{11})"
    ]

    for pattern in patterns:

        match = re.search(pattern, url)

        if match:
            return match.group(1)

    return None


# ─────────────────────────────────────
# Fetch Transcript
# ─────────────────────────────────────
def get_transcript(video_id):
    try:
        temp_dir = tempfile.gettempdir()
        temp_filename = os.path.join(temp_dir, f"{str(uuid.uuid4())}.%(ext)s")
        expected_filename = temp_filename.replace('%(ext)s', 'en.vtt')
        
        ydl_opts = {
            'writesubtitles': True, 
            'writeautomaticsub': True,
            'subtitleslangs': ['en'], 
            'skip_download': True, 
            'quiet': True, 
            'outtmpl': temp_filename
        }
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not os.path.exists(expected_filename):
            raise ValueError("No transcript found")

        vtt = webvtt.read(expected_filename)
        
        transcript_list = []
        full_text_parts = []
        
        for caption in vtt:
            text = caption.text.replace('\n', ' ').strip()
            
            # Convert timestamp (e.g., '00:00:12.240') to total seconds
            try:
                h, m, s = caption.start.split(':')
                s, ms = s.split('.')
                total_seconds = int(h) * 3600 + int(m) * 60 + int(s) + float(ms) / 1000
            except:
                total_seconds = 0
                
            transcript_list.append({
                "text": text,
                "start": total_seconds
            })
            full_text_parts.append(text)

        full_text = " ".join(full_text_parts)
        
        # Cleanup
        try:
            os.remove(expected_filename)
        except:
            pass
            
        return full_text, transcript_list

    except Exception as e:
        raise ValueError(str(e))



# ─────────────────────────────────────
# Convert Seconds → Timestamp
# ─────────────────────────────────────
def seconds_to_timestamp(seconds):

    seconds = int(seconds)

    m, s = divmod(seconds, 60)

    return f"{m:02d}:{s:02d}"


# ─────────────────────────────────────
# Home Route
# ─────────────────────────────────────
@app.route("/")
def home():

    return render_template("index.html")


# ─────────────────────────────────────
# Summarize Endpoint
# ─────────────────────────────────────
@app.route("/summarize", methods=["POST"])
def summarize():

    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    url = data.get("url")

    if not url:
        return jsonify({"error": "URL required"}), 400

    video_id = extract_video_id(url)

    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400

    try:
        full_text, transcript_list = get_transcript(video_id)

    except ValueError as e:
        return jsonify({"error": str(e)}), 422

    # Build timestamp context
    context = ""

    for seg in transcript_list:

        ts = seconds_to_timestamp(seg["start"])

        context += f"[{ts}] {seg['text']}\n"

    prompt = f"""
You are an expert YouTube video summarizer.

Transcript:
{context}

Return strictly in this format:

Summary:
Key Points:
Important Moments:
Takeaways:
"""

    try:
        summary = call_llm(prompt)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({

        "video_id": video_id,
        "summary": summary,
        "transcript": full_text[:100000]

    })


# ─────────────────────────────────────
# Ask Question Endpoint
# ─────────────────────────────────────
@app.route("/ask", methods=["POST"])
def ask():

    data = request.get_json()

    if not data:
        return jsonify({"error": "JSON body required"}), 400

    question = data.get("question")
    transcript = data.get("transcript")

    if not question:
        return jsonify({"error": "Question required"}), 400

    if not transcript:
        return jsonify({"error": "Transcript missing"}), 400

    prompt = f"""
Answer the question using ONLY the transcript.

Transcript:
{transcript}

Question:
{question}
"""

    try:
        answer = call_llm(prompt)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "answer": answer
    })


# ─────────────────────────────────────
# Run Server
# ─────────────────────────────────────
if __name__ == "__main__":

    print("Server running at http://localhost:5000")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
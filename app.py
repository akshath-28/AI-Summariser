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
import uuid
import webvtt


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

# Switched model to standard Llama 3 8B to avoid rate limiting on the 70B model free tier.
# You can also try "mixtral-8x7b-32768" or "llama-3.1-8b-instant"
# Switched model to Llama 3.1 8B Instant to avoid rate limiting and use a supported model
# You can also try "mixtral-8x7b-32768"
MODEL = "llama-3.1-8b-instant"


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
        
        # Bypassing the Render IP ban
        ydl_opts = {
            'writesubtitles': True, 
            'writeautomaticsub': True,
            'subtitleslangs': ['en'], 
            'skip_download': True,
            'ignore_no_formats_error': True,
            'format': 'bestaudio/best',
            'quiet': True, 
            'outtmpl': temp_filename,
            'extractor_args': {'youtube': {'player_client': ['web_safari', 'android']}},
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        # Integrate Cookies if available in Environment Variables
        youtube_cookies = os.getenv("YOUTUBE_COOKIES")
        cookie_file = None
        if youtube_cookies:
            cookie_file = os.path.join(temp_dir, "youtube_cookies.txt")
            with open(cookie_file, "w") as f:
                f.write(youtube_cookies)
            ydl_opts['cookiefile'] = cookie_file
        
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not os.path.exists(expected_filename):
            raise ValueError("No transcript found (the video may not have English captions)")

        vtt = webvtt.read(expected_filename)
        
        transcript_list = []
        full_text_parts = []
        
        for caption in vtt:
            text = caption.text.replace('\n', ' ').strip()
            text = re.sub(r'<[^>]+>', '', text) # clean any residual VTT tags
            
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
        
        try:
            os.remove(expected_filename)
        except:
            pass
            
        if cookie_file and os.path.exists(cookie_file):
            try:
                os.remove(cookie_file)
            except:
                pass
                
        return full_text, transcript_list

    except Exception as e:
        raise ValueError(f"Transcript fetch failed: {str(e)}")



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
# Helpers: Chunking / Prompt Building
# ─────────────────────────────────────

def build_transcript_context(transcript_segment):
    """Build a timestamped transcript string for a list of transcript segments."""
    lines = []
    for seg in transcript_segment:
        ts = seconds_to_timestamp(seg["start"])
        lines.append(f"[{ts}] {seg['text']}")
    return "\n".join(lines)


def chunk_transcript(transcript_list, max_chars=12000):
    """Chunk transcript segments so each chunk is small enough for the model.

    Args:
        transcript_list: list of transcript dicts with `text` and `start`
        max_chars: approximate maximum number of characters per chunk.

    Returns:
        List of transcript segments (each is a list of dicts).
    """

    chunks = []
    current = []
    current_len = 0

    for seg in transcript_list:
        line = f"[{seconds_to_timestamp(seg['start'])}] {seg['text']}\n"

        # If adding this line would exceed the chunk size, finalize current chunk
        if current and current_len + len(line) > max_chars:
            chunks.append(current)
            current = []
            current_len = 0

        current.append(seg)
        current_len += len(line)

    if current:
        chunks.append(current)

    return chunks


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

    # Chunk the transcript so we don't exceed token limits
    chunks = chunk_transcript(transcript_list, max_chars=12000)

    summaries = []

    for index, chunk in enumerate(chunks, start=1):
        context = build_transcript_context(chunk)

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
            chunk_summary = call_llm(prompt)
            summaries.append(chunk_summary.strip())
        except Exception as e:
            return jsonify({"error": str(e), "chunk": index}), 500

    # If we generated multiple summaries, combine them into one final output
    if len(summaries) > 1:
        combine_prompt = """
You are an expert YouTube video summarizer.

Combine the following chunk summaries into a single summary in the same format.
If there is overlap, merge similar points.

"""

        for idx, s in enumerate(summaries, start=1):
            combine_prompt += f"--- Chunk {idx} ---\n{s}\n\n"

        try:
            summary = call_llm(combine_prompt)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    else:
        summary = summaries[0]

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
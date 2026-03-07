/**
 * YTLens — Frontend Logic
 * ========================
 * Handles:
 *  - Summarize button: calls /summarize API
 *  - Chat interface: calls /ask API
 *  - Timestamp parsing & clickable links
 *  - Copy summary button
 *  - Animated particle background canvas
 */

/* ── State ─────────────────────────────────────────── */
let currentTranscript = "";  // Stores the transcript for Q&A
let currentVideoId    = "";  // Current YouTube video ID
let chatHistory       = [];  // Q&A history for context

/* ── DOM References ────────────────────────────────── */
const urlInput      = document.getElementById("yt-url");
const summarizeBtn  = document.getElementById("summarize-btn");
const errorMsg      = document.getElementById("error-msg");
const videoWrapper  = document.getElementById("video-wrapper");
const ytIframe      = document.getElementById("yt-iframe");
const videoIdBadge  = document.getElementById("video-id-badge");
const loadingCard   = document.getElementById("loading-card");
const emptyState    = document.getElementById("empty-state");
const summaryCard   = document.getElementById("summary-card");
const summaryContent= document.getElementById("summary-content");
const chatCard      = document.getElementById("chat-card");
const chatMessages  = document.getElementById("chat-messages");
const chatInput     = document.getElementById("chat-input");

/* ── Summarize Video ───────────────────────────────── */
async function summarizeVideo() {
  const url = urlInput.value.trim();

  // Basic validation
  if (!url) {
    showError("Please paste a YouTube URL first.");
    return;
  }
  if (!url.includes("youtube") && !url.includes("youtu.be")) {
    showError("This doesn't look like a YouTube URL. Please try again.");
    return;
  }

  // Reset UI state
  hideError();
  setLoading(true);
  emptyState.classList.add("hidden");
  summaryCard.classList.add("hidden");
  chatCard.classList.add("hidden");
  chatHistory = [];

  try {
    // ── Call /summarize endpoint ──
    const res = await fetch("/summarize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url })
    });

    const data = await res.json();

    if (!res.ok) {
      showError(data.error || "Something went wrong. Please try again.");
      setLoading(false);
      return;
    }

    // Store transcript & video ID for later Q&A
    currentTranscript = data.transcript;
    currentVideoId    = data.video_id;

    // Embed the YouTube video
    showVideo(data.video_id);

    // Render the summary with markdown-like formatting
    renderSummary(data.summary);

    // Show chat interface
    chatCard.classList.remove("hidden");
    resetChatMessages();

  } catch (err) {
    console.error("Fetch error:", err);
    showError("Network error — make sure the Flask server is running on port 5000.");
  }

  setLoading(false);
}

/* ── Render Summary ────────────────────────────────── */
function renderSummary(rawText) {
  /**
   * Converts the AI's markdown-style text into clean HTML.
   * Also makes timestamps clickable to jump the video player.
   */
  let html = rawText

    // Convert ## Heading → <h2>
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")

    // Convert • bullet → <li>
    .replace(/^[•\-\*] (.+)$/gm, "<li>$1</li>")

    // Wrap consecutive <li> tags in <ul>
    .replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`)

    // Make timestamp patterns clickable: "01:23 – Description"
    .replace(
      /(\d{1,2}:\d{2}(?::\d{2})?)\s*[–—-]\s*(.+)/g,
      (_, ts, desc) => {
        const seconds = timestampToSeconds(ts);
        return `<span class="ts-link" onclick="seekVideo(${seconds})" title="Jump to ${ts}">▶ ${ts}</span> ${desc}`;
      }
    )

    // Convert newlines to <br> (outside block elements)
    .replace(/\n/g, "<br>");

  summaryContent.innerHTML = html;
  summaryCard.classList.remove("hidden");
  summaryCard.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ── Show Embedded Video ───────────────────────────── */
function showVideo(videoId) {
  ytIframe.src = `https://www.youtube.com/embed/${videoId}?enablejsapi=1`;
  videoIdBadge.textContent = videoId;
  videoWrapper.classList.remove("hidden");
}

/* ── Seek Video to Timestamp ───────────────────────── */
function seekVideo(seconds) {
  /**
   * Updates the iframe src with start= parameter to jump to a timestamp.
   * The YouTube embed API uses start= for initial seek.
   */
  if (!currentVideoId) return;
  ytIframe.src = `https://www.youtube.com/embed/${currentVideoId}?start=${seconds}&autoplay=1&enablejsapi=1`;
  videoWrapper.scrollIntoView({ behavior: "smooth" });
}

/* ── Convert "MM:SS" or "HH:MM:SS" to seconds ─────── */
function timestampToSeconds(ts) {
  const parts = ts.split(":").map(Number);
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  return 0;
}

/* ── Copy Summary ──────────────────────────────────── */
function copySummary() {
  // Get plain text (strip HTML tags)
  const plainText = summaryContent.innerText || summaryContent.textContent;

  navigator.clipboard.writeText(plainText).then(() => {
    const copyIcon = document.getElementById("copy-icon");
    const copyBtn  = document.getElementById("copy-btn");
    copyIcon.textContent = "✓";
    copyBtn.style.color = "var(--accent)";
    copyBtn.style.borderColor = "var(--accent)";
    setTimeout(() => {
      copyIcon.textContent = "⎘";
      copyBtn.style.color = "";
      copyBtn.style.borderColor = "";
    }, 2000);
  }).catch(() => {
    showError("Could not copy to clipboard. Please select and copy manually.");
  });
}

/* ── Send Chat Question ────────────────────────────── */
async function sendQuestion() {
  const question = chatInput.value.trim();
  if (!question) return;
  if (!currentTranscript) {
    addChatBubble("assistant", "Please summarize a video first before asking questions!");
    return;
  }

  // Append user bubble
  addChatBubble("user", question);
  chatInput.value = "";

  // Show typing indicator
  const typingId = addTypingIndicator();

  try {
    const res = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        transcript: currentTranscript,
        history: chatHistory
      })
    });

    const data = await res.json();
    removeTypingIndicator(typingId);

    if (!res.ok) {
      addChatBubble("assistant", `Error: ${data.error || "Something went wrong."}`);
      return;
    }

    // Add AI response bubble
    addChatBubble("assistant", data.answer);

    // Save to history for context
    chatHistory.push({ question, answer: data.answer });

  } catch (err) {
    removeTypingIndicator(typingId);
    addChatBubble("assistant", "Network error. Please check the server is running.");
  }
}

/* ── Enter key in chat sends message ──────────────── */
function handleChatKey(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendQuestion();
  }
}

/* ── Add Chat Bubble ───────────────────────────────── */
function addChatBubble(role, text) {
  const isAssistant = role === "assistant";
  const div = document.createElement("div");
  div.className = `chat-bubble ${isAssistant ? "assistant-bubble" : "user-bubble"}`;

  // Format assistant text (basic markdown)
  const formattedText = isAssistant
    ? text
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\n/g, "<br>")
    : escapeHtml(text);

  div.innerHTML = `
    <span class="bubble-icon">${isAssistant ? "◈" : "◉"}</span>
    <div class="bubble-body"><p>${formattedText}</p></div>
  `;

  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

/* ── Typing Indicator ──────────────────────────────── */
function addTypingIndicator() {
  const id = "typing-" + Date.now();
  const div = document.createElement("div");
  div.className = "chat-bubble assistant-bubble typing-bubble";
  div.id = id;
  div.innerHTML = `
    <span class="bubble-icon">◈</span>
    <div class="bubble-body">
      <span class="dot"></span>
      <span class="dot"></span>
      <span class="dot"></span>
    </div>
  `;
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return id;
}

function removeTypingIndicator(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

/* ── Reset Chat Messages ───────────────────────────── */
function resetChatMessages() {
  chatMessages.innerHTML = `
    <div class="chat-bubble assistant-bubble intro-bubble">
      <span class="bubble-icon">◈</span>
      <div class="bubble-body">
        <p>I've analyzed the video. Ask me anything about its content!</p>
      </div>
    </div>
  `;
}

/* ── Error Display ─────────────────────────────────── */
function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.remove("hidden");
}

function hideError() {
  errorMsg.classList.add("hidden");
}

/* ── Loading State ─────────────────────────────────── */
function setLoading(isLoading) {
  if (isLoading) {
    loadingCard.classList.remove("hidden");
    summarizeBtn.disabled = true;
  } else {
    loadingCard.classList.add("hidden");
    summarizeBtn.disabled = false;
  }
}

/* ── Escape HTML (for user messages) ──────────────── */
function escapeHtml(text) {
  const div = document.createElement("div");
  div.appendChild(document.createTextNode(text));
  return div.innerHTML;
}

/* ── Allow Enter key on URL input ──────────────────── */
urlInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") summarizeVideo();
});

/* ══════════════════════════════════════════════════════
   ANIMATED PARTICLE BACKGROUND
   Subtle floating nodes connected by lines
══════════════════════════════════════════════════════ */
(function initCanvas() {
  const canvas = document.getElementById("bg-canvas");
  const ctx    = canvas.getContext("2d");
  let W, H, particles;
  const COUNT = 55;
  const CONNECT_DIST = 130;

  function resize() {
    W = canvas.width  = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function createParticles() {
    particles = Array.from({ length: COUNT }, () => ({
      x:  Math.random() * W,
      y:  Math.random() * H,
      vx: (Math.random() - 0.5) * 0.35,
      vy: (Math.random() - 0.5) * 0.35,
      r:  Math.random() * 1.8 + 0.5,
    }));
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);

    // Draw connections
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx   = particles[i].x - particles[j].x;
        const dy   = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < CONNECT_DIST) {
          const alpha = (1 - dist / CONNECT_DIST) * 0.25;
          ctx.strokeStyle = `rgba(232,255,71,${alpha})`;
          ctx.lineWidth = 0.6;
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.stroke();
        }
      }
    }

    // Draw dots
    particles.forEach(p => {
      ctx.fillStyle = "rgba(232,255,71,0.45)";
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();

      // Move
      p.x += p.vx;
      p.y += p.vy;

      // Bounce off walls
      if (p.x < 0 || p.x > W) p.vx *= -1;
      if (p.y < 0 || p.y > H) p.vy *= -1;
    });

    requestAnimationFrame(draw);
  }

  window.addEventListener("resize", () => { resize(); });
  resize();
  createParticles();
  draw();
})();

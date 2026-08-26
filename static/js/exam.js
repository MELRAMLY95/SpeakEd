(function () {
  const room = document.querySelector("[data-exam-room]");
  if (!room) return;

  const attemptId = room.dataset.attemptId;
  const statusEl = room.querySelector("[data-status]");
  const questionEl = room.querySelector("[data-question]");
  const micEl = room.querySelector("[data-mic]");
  const repeatEl = room.querySelector("[data-repeat]");
  const liveEl = room.querySelector("[data-live-transcript]");
  const micState = room.querySelector("[data-mic-state]");
  const noteEl = room.querySelector("[data-practice-note]");
  const timerEl = room.querySelector("[data-timer]");
  const errorEl = room.querySelector("[data-exam-error]");
  let lastSpoken = "";
  let listening = false;
  let submitting = false;
  let autoStartMic = true;

  function setStatus(label) {
    statusEl.textContent = label;
    micState.textContent = label;
  }

  function setError(message) {
    if (!errorEl) return;
    if (!message) {
      errorEl.hidden = true;
      errorEl.textContent = "";
      return;
    }
    errorEl.hidden = false;
    errorEl.textContent = message;
  }

  function speak(text) {
    if (!text) return Promise.resolve();
    lastSpoken = text;
    setStatus("🔊 Speaking");
    return new Promise((resolve) => {
      window.SpeakEdRecorder.speak(text, () => {
        resolve();
      });
    });
  }

  async function loadState(speakNow) {
    const response = await fetch(`/exam/${attemptId}/state`);
    const state = await response.json();
    if (state.prompt) {
      questionEl.textContent = state.prompt.display || state.prompt.spoken;
      if (speakNow !== false) {
        await speak(state.prompt.spoken || state.prompt.display);
        if (autoStartMic && !listening) {
          setTimeout(() => startListen(), 500);
        }
      }
    }
    if (state.prompt && state.prompt.timer) {
      timerEl.hidden = false;
      window.SpeakEdTimer.start(state.prompt.timer, (s) => {
        timerEl.textContent = window.SpeakEdTimer.format(s);
      }, () => {
        if (listening) finishTurn();
      });
    }
    return state;
  }

  async function finishTurn() {
    if (window.SpeakEdRecorder.isSpeaking() || submitting) return;
    listening = false;
    submitting = true;
    micEl.textContent = "🎤 Tap to speak";
    micEl.classList.remove("active");
    setStatus("⏳ Processing");
    setError("");
    let captured;
    try {
      captured = await window.SpeakEdRecorder.stop();
    } catch (err) {
      submitting = false;
      setError("Recording could not be stopped. Please try again.");
      setStatus("🎤 Ready");
      return;
    }
    const transcript = captured.transcript || "";
    liveEl.textContent = transcript;
    if (!transcript && !captured.blob) {
      submitting = false;
      setError("No speech was captured. Check the microphone and try again.");
      setStatus("🎤 Ready");
      return;
    }
    const form = new FormData();
    form.append("transcript", transcript);
    form.append("metrics", JSON.stringify(captured.metrics || {}));
    if (captured.blob) {
      const ext = (captured.mimeType || "audio/webm").includes("mp4") ? "m4a" : "webm";
      form.append("audio", captured.blob, `turn.${ext}`);
    }
    let state;
    try {
      const response = await fetch(`/exam/${attemptId}/turn`, {
        method: "POST",
        headers: window.SpeakEdCsrf ? window.SpeakEdCsrf.headers() : {},
        body: form,
      });
      state = await response.json();
      if (!response.ok) {
        submitting = false;
        setError(state.error || "The examiner could not process that answer. Please retry.");
        setStatus("🎤 Ready");
        return;
      }
    } catch (err) {
      submitting = false;
      setError("Network error while sending your answer. Please retry.");
      setStatus("🎤 Ready");
      return;
    }
    if (state.practice_note && noteEl) noteEl.textContent = state.practice_note;
    if (state.redirect) {
      window.location.href = state.redirect;
      return;
    }
    submitting = false;
    if (state.stage && state.stage !== room.dataset.stage) {
      window.location.reload();
      return;
    }
    if (state.prompt) {
      questionEl.textContent = state.prompt.display;
      await speak(state.prompt.spoken || state.prompt.display);
      if (autoStartMic) {
        setTimeout(() => startListen(), 500);
      }
    }
    setStatus("🎤 Ready");
  }

  async function startListen() {
    if (window.SpeakEdRecorder.isSpeaking() || listening || submitting) return;
    setError("");
    listening = true;
    micEl.textContent = "🛑 Stop recording";
    micEl.classList.add("active");
    setStatus("🎙️ Listening...");
    try {
      await window.SpeakEdRecorder.start((text) => {
        liveEl.textContent = text;
      });
    } catch (err) {
      listening = false;
      micEl.textContent = "🎤 Tap to speak";
      micEl.classList.remove("active");
      const denied = err && (err.name === "NotAllowedError" || err.name === "PermissionDeniedError");
      setError(denied
        ? "Microphone permission was denied. Allow the microphone and try again."
        : "The microphone could not be started. Check your browser settings.");
      setStatus("🎤 Ready");
    }
  }

  micEl.addEventListener("click", () => {
    if (listening) {
      finishTurn();
    } else {
      startListen();
    }
  });

  repeatEl.addEventListener("click", () => {
    window.SpeakEdRecorder.stopSpeaking();
    speak(lastSpoken);
  });

  window.SpeakEdRecorder.setSpeakingCallback((isSpeaking) => {
    if (isSpeaking) {
      micEl.disabled = true;
      micEl.style.opacity = "0.5";
    } else {
      micEl.disabled = false;
      micEl.style.opacity = "1";
    }
  });

  if (window.speechSynthesis) {
    window.speechSynthesis.onvoiceschanged = () => {
      window.speechSynthesis.getVoices();
    };
  }

  loadState(true);
})();

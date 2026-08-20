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
  let lastSpoken = "";
  let listening = false;
  let autoStartMic = true;

  function setStatus(label) {
    statusEl.textContent = label;
    micState.textContent = label;
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
        // Auto-start microphone after AI speaks
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
    if (window.SpeakEdRecorder.isSpeaking()) return;
    listening = false;
    micEl.textContent = "🎤 Tap to speak";
    micEl.classList.remove("active");
    setStatus("⏳ Processing");
    const captured = window.SpeakEdRecorder.stop();
    let transcript = captured.transcript;
    if (!transcript) {
      transcript = window.prompt("Speech recognition is not available in this browser. Type what you said:") || "";
    }
    liveEl.textContent = transcript;
    const response = await fetch(`/exam/${attemptId}/turn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transcript, metrics: captured.metrics }),
    });
    const state = await response.json();
    if (state.practice_note && noteEl) noteEl.textContent = state.practice_note;
    if (state.redirect) {
      window.location.href = state.redirect;
      return;
    }
    if (state.stage && state.stage !== room.dataset.stage) {
      window.location.reload();
      return;
    }
    if (state.prompt) {
      questionEl.textContent = state.prompt.display;
      await speak(state.prompt.spoken || state.prompt.display);
      // Auto-start microphone for next question
      if (autoStartMic) {
        setTimeout(() => startListen(), 500);
      }
    }
    setStatus("🎤 Ready");
  }

  async function startListen() {
    if (window.SpeakEdRecorder.isSpeaking() || listening) return;
    listening = true;
    micEl.textContent = "🛑 Stop recording";
    micEl.classList.add("active");
    setStatus("🎙️ Listening...");
    await window.SpeakEdRecorder.start((text) => {
      liveEl.textContent = text;
    });
  }

  // Toggle microphone instead of hold
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

  // Set up speaking callback to update UI
  window.SpeakEdRecorder.setSpeakingCallback((isSpeaking) => {
    if (isSpeaking) {
      micEl.disabled = true;
      micEl.style.opacity = "0.5";
    } else {
      micEl.disabled = false;
      micEl.style.opacity = "1";
    }
  });

  // Load voices for speech synthesis
  if (window.speechSynthesis) {
    window.speechSynthesis.onvoiceschanged = () => {
      const voices = window.speechSynthesis.getVoices();
      console.log("Available voices:", voices.length);
    };
  }

  // Start the exam with auto-mic
  loadState(true);
})();

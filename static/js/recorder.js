window.SpeakEdRecorder = {
  recognition: null,
  synthesis: window.speechSynthesis,
  active: false,
  speaking: false,
  transcript: "",
  startedAt: 0,
  pauseCount: 0,
  fillerCount: 0,
  onSpeakingCallback: null,

  available() {
    return "webkitSpeechRecognition" in window || "SpeechRecognition" in window;
  },

  speechAvailable() {
    return "speechSynthesis" in window;
  },

  create() {
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new Ctor();
    rec.lang = "en-GB";
    rec.continuous = true;
    rec.interimResults = true;
    return rec;
  },

  start(onUpdate) {
    this.transcript = "";
    this.startedAt = Date.now();
    this.pauseCount = 0;
    this.fillerCount = 0;
    if (!this.available()) {
      this.active = true;
      onUpdate("", true);
      return Promise.resolve();
    }
    this.recognition = this.create();
    this.recognition.onresult = (event) => {
      let text = "";
      for (let i = 0; i < event.results.length; i += 1) {
        text += event.results[i][0].transcript;
      }
      this.transcript = text.trim();
      this.fillerCount = (this.transcript.match(/\b(um|uh|er|erm|like)\b/gi) || []).length;
      onUpdate(this.transcript, true);
    };
    this.recognition.onerror = () => onUpdate(this.transcript, true);
    this.recognition.start();
    this.active = true;
    return Promise.resolve();
  },

  stop() {
    this.active = false;
    try {
      this.recognition && this.recognition.stop();
    } catch (err) {
      /* ignore */
    }
    const duration = Date.now() - this.startedAt;
    return {
      transcript: this.transcript,
      metrics: {
        duration_ms: duration,
        pause_count: this.pauseCount,
        filler_count: this.fillerCount,
        word_count: this.transcript.split(/\s+/).filter(Boolean).length,
      },
    };
  },

  speak(text, onEnd) {
    if (!this.speechAvailable()) {
      console.warn("Speech synthesis not available");
      if (onEnd) onEnd();
      return;
    }

    // Stop any current speech
    this.synthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-GB";
    utterance.rate = 0.9;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;

    // Try to get a good voice
    const voices = this.synthesis.getVoices();
    const preferredVoice = voices.find(voice => 
      voice.name.includes("Google UK English Male") || 
      voice.name.includes("Daniel") ||
      voice.name.includes("UK English")
    );
    if (preferredVoice) {
      utterance.voice = preferredVoice;
    }

    utterance.onstart = () => {
      this.speaking = true;
      if (this.onSpeakingCallback) {
        this.onSpeakingCallback(true);
      }
    };

    utterance.onend = () => {
      this.speaking = false;
      if (this.onSpeakingCallback) {
        this.onSpeakingCallback(false);
      }
      if (onEnd) onEnd();
    };

    utterance.onerror = () => {
      this.speaking = false;
      if (this.onSpeakingCallback) {
        this.onSpeakingCallback(false);
      }
      if (onEnd) onEnd();
    };

    this.synthesis.speak(utterance);
  },

  stopSpeaking() {
    if (this.speechAvailable()) {
      this.synthesis.cancel();
      this.speaking = false;
      if (this.onSpeakingCallback) {
        this.onSpeakingCallback(false);
      }
    }
  },

  setSpeakingCallback(callback) {
    this.onSpeakingCallback = callback;
  },

  isSpeaking() {
    return this.speaking;
  }
};

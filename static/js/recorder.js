window.SpeakEdRecorder = {
  recognition: null,
  synthesis: window.speechSynthesis,
  mediaRecorder: null,
  mediaStream: null,
  chunks: [],
  mimeType: "",
  active: false,
  speaking: false,
  submitting: false,
  transcript: "",
  startedAt: 0,
  pauseCount: 0,
  fillerCount: 0,
  lastPauseAt: 0,
  onSpeakingCallback: null,
  _recognitionFatal: false,
  _onError: null,

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
    rec.maxAlternatives = 1;
    return rec;
  },

  _errorMessage(code) {
    if (code === "not-allowed" || code === "service-not-allowed") {
      return "Microphone permission was denied. Allow the microphone and try again.";
    }
    if (code === "audio-capture") {
      return "The microphone could not be opened. Close other apps using it and try again.";
    }
    if (code === "network") {
      return "Live captions could not connect. Keep speaking, then tap Stop — your recording will still be sent.";
    }
    return "";
  },

  _bindRecognition(onUpdate) {
    if (!this.available()) {
      onUpdate("", true);
      return;
    }
    this.recognition = this.create();
    this.recognition.onresult = (event) => {
      let text = "";
      for (let i = 0; i < event.results.length; i += 1) {
        text += event.results[i][0].transcript;
      }
      this.transcript = text.trim();
      this.fillerCount = (this.transcript.match(/\b(um|uh|er|erm|like)\b/gi) || []).length;
      const now = Date.now();
      if (now - this.lastPauseAt > 900) this.pauseCount += 1;
      this.lastPauseAt = now;
      onUpdate(this.transcript, true);
    };
    this.recognition.onerror = (event) => {
      const code = (event && event.error) || "";
      if (code === "no-speech" || code === "aborted") return;
      if (code === "not-allowed" || code === "service-not-allowed") {
        this._recognitionFatal = true;
      }
      const message = this._errorMessage(code);
      if (message && this._onError) this._onError(message);
      onUpdate(this.transcript, true);
    };
    this.recognition.onend = () => {
      if (!this.active || this._recognitionFatal || !this.recognition) return;
      try {
        this.recognition.start();
      } catch (err) {
        /* already running */
      }
    };
  },

  start(onUpdate, onError) {
    this.transcript = "";
    this.startedAt = Date.now();
    this.pauseCount = 0;
    this.fillerCount = 0;
    this.lastPauseAt = Date.now();
    this.chunks = [];
    this.mimeType = "";
    this.active = true;
    this._recognitionFatal = false;
    this._onError = typeof onError === "function" ? onError : null;

    const startRecognition = () => {
      this._bindRecognition(onUpdate);
      if (!this.recognition) return;
      try {
        this.recognition.start();
      } catch (err) {
        onUpdate(this.transcript, true);
      }
    };

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      startRecognition();
      if (!this.available()) {
        return Promise.reject(new Error("unsupported"));
      }
      return Promise.resolve();
    }

    return navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
      this.mediaStream = stream;
      const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg", "audio/mp4"];
      this.mimeType = types.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
      if (window.MediaRecorder) {
        this.mediaRecorder = this.mimeType
          ? new MediaRecorder(stream, { mimeType: this.mimeType })
          : new MediaRecorder(stream);
        this.mimeType = this.mediaRecorder.mimeType || this.mimeType || "audio/webm";
        this.mediaRecorder.ondataavailable = (event) => {
          if (event.data && event.data.size > 0) this.chunks.push(event.data);
        };
        this.mediaRecorder.start(100);
      }
      startRecognition();
    });
  },

  stop() {
    this.active = false;
    try {
      this.recognition && this.recognition.stop();
    } catch (err) {
      /* ignore */
    }
    this.recognition = null;
    const duration = Date.now() - this.startedAt;
    const transcript = this.transcript;
    const metrics = {
      duration_ms: duration,
      pause_count: this.pauseCount,
      filler_count: this.fillerCount,
      word_count: transcript.split(/\s+/).filter(Boolean).length,
    };

    const finalize = (blob) => {
      if (this.mediaStream) {
        this.mediaStream.getTracks().forEach((track) => track.stop());
        this.mediaStream = null;
      }
      this.mediaRecorder = null;
      return {
        transcript,
        blob: blob && blob.size > 0 ? blob : null,
        mimeType: this.mimeType || (blob && blob.type) || "",
        metrics,
      };
    };

    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      const recorder = this.mediaRecorder;
      return new Promise((resolve) => {
        recorder.onstop = () => {
          const type = this.mimeType || "audio/webm";
          resolve(finalize(new Blob(this.chunks, { type })));
        };
        try {
          recorder.stop();
        } catch (err) {
          resolve(finalize(null));
        }
      });
    }
    return Promise.resolve(finalize(null));
  },

  speak(text, onEnd) {
    if (!this.speechAvailable()) {
      if (onEnd) onEnd();
      return;
    }
    this.synthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-GB";
    utterance.rate = 0.9;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    const voices = this.synthesis.getVoices();
    const preferredVoice = voices.find((voice) =>
      voice.name.includes("Google UK English Male") ||
      voice.name.includes("Daniel") ||
      voice.name.includes("UK English")
    );
    if (preferredVoice) utterance.voice = preferredVoice;
    utterance.onstart = () => {
      this.speaking = true;
      if (this.onSpeakingCallback) this.onSpeakingCallback(true);
    };
    utterance.onend = () => {
      this.speaking = false;
      if (this.onSpeakingCallback) this.onSpeakingCallback(false);
      if (onEnd) onEnd();
    };
    utterance.onerror = () => {
      this.speaking = false;
      if (this.onSpeakingCallback) this.onSpeakingCallback(false);
      if (onEnd) onEnd();
    };
    this.synthesis.speak(utterance);
  },

  stopSpeaking() {
    if (this.speechAvailable()) {
      this.synthesis.cancel();
      this.speaking = false;
      if (this.onSpeakingCallback) this.onSpeakingCallback(false);
    }
  },

  setSpeakingCallback(callback) {
    this.onSpeakingCallback = callback;
  },

  isSpeaking() {
    return this.speaking;
  }
};

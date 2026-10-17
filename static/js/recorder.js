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
  _onUpdate: null,
  _committed: "",
  _stopping: false,
  _restartTimer: null,
  _speechEnded: null,

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

  _publish() {
    this.fillerCount = (this.transcript.match(/\b(um|uh|er|erm|like)\b/gi) || []).length;
    if (this._onUpdate) this._onUpdate(this.transcript, true);
  },

  _bindRecognition(rec) {
    rec.onresult = (event) => {
      let live = "";
      for (let i = 0; i < event.results.length; i += 1) {
        live += event.results[i][0].transcript;
      }
      this.transcript = `${this._committed} ${live}`.replace(/\s+/g, " ").trim();
      const now = Date.now();
      if (this.lastPauseAt && now - this.lastPauseAt > 1200) this.pauseCount += 1;
      this.lastPauseAt = now;
      this._publish();
    };
    rec.onerror = (event) => {
      const code = (event && event.error) || "";
      if (code === "no-speech" || code === "aborted" || code === "audio-capture") {
        return;
      }
      if (code === "not-allowed") {
        this.active = false;
        this._publish();
      }
    };
    rec.onend = () => {
      this._committed = this.transcript;
      if (this._speechEnded) {
        const done = this._speechEnded;
        this._speechEnded = null;
        done();
      }
      if (!this.active || this._stopping) return;
      this._restartTimer = setTimeout(() => this._restartRecognition(), 80);
    };
  },

  _restartRecognition() {
    if (!this.active || this._stopping || !this.available()) return;
    try {
      this.recognition = this.create();
      this._bindRecognition(this.recognition);
      this.recognition.start();
    } catch (err) {
      this._restartTimer = setTimeout(() => this._restartRecognition(), 250);
    }
  },

  start(onUpdate) {
    this.transcript = "";
    this._committed = "";
    this._onUpdate = onUpdate;
    this.startedAt = Date.now();
    this.pauseCount = 0;
    this.fillerCount = 0;
    this.lastPauseAt = Date.now();
    this.chunks = [];
    this.mimeType = "";
    this.active = true;
    this._stopping = false;
    if (this._restartTimer) {
      clearTimeout(this._restartTimer);
      this._restartTimer = null;
    }

    const startRecognition = () => {
      if (!this.available()) {
        onUpdate("", true);
        return Promise.resolve();
      }
      this._restartRecognition();
      return Promise.resolve();
    };

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      return startRecognition();
    }

    return navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
      this.mediaStream = stream;
      const types = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg", "audio/mp4"];
      this.mimeType = types.find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
      if (window.MediaRecorder) {
        try {
          this.mediaRecorder = this.mimeType
            ? new MediaRecorder(stream, { mimeType: this.mimeType })
            : new MediaRecorder(stream);
          this.mimeType = this.mediaRecorder.mimeType || this.mimeType || "audio/webm";
          this.mediaRecorder.ondataavailable = (event) => {
            if (event.data && event.data.size > 0) this.chunks.push(event.data);
          };
          this.mediaRecorder.start(250);
        } catch (err) {
          this.mediaRecorder = null;
        }
      }
      return startRecognition();
    }).catch((err) => startRecognition().then(() => {
      if (!this.available()) throw err;
    }));
  },

  stop() {
    this.active = false;
    this._stopping = true;
    if (this._restartTimer) {
      clearTimeout(this._restartTimer);
      this._restartTimer = null;
    }

    const waitForSpeech = new Promise((resolve) => {
      if (!this.recognition) {
        resolve();
        return;
      }
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        resolve();
      };
      this._speechEnded = finish;
      setTimeout(finish, 500);
      try {
        this.recognition.stop();
      } catch (err) {
        finish();
      }
    });

    const duration = Date.now() - this.startedAt;
    const metricsFrom = (transcript) => ({
      duration_ms: duration,
      pause_count: this.pauseCount,
      filler_count: this.fillerCount,
      word_count: transcript.split(/\s+/).filter(Boolean).length,
    });

    const finalize = (blob) => {
      if (this.mediaStream) {
        this.mediaStream.getTracks().forEach((track) => track.stop());
        this.mediaStream = null;
      }
      this.mediaRecorder = null;
      this.recognition = null;
      const transcript = (this.transcript || this._committed || "").replace(/\s+/g, " ").trim();
      this.transcript = transcript;
      return {
        transcript,
        blob: blob && blob.size > 0 ? blob : null,
        mimeType: this.mimeType || (blob && blob.type) || "",
        metrics: metricsFrom(transcript),
      };
    };

    const stopMedia = () => new Promise((resolve) => {
      if (!this.mediaRecorder || this.mediaRecorder.state === "inactive") {
        resolve(finalize(this.chunks.length ? new Blob(this.chunks, { type: this.mimeType || "audio/webm" }) : null));
        return;
      }
      const recorder = this.mediaRecorder;
      const timer = setTimeout(() => resolve(finalize(null)), 1500);
      recorder.onstop = () => {
        clearTimeout(timer);
        const type = this.mimeType || "audio/webm";
        resolve(finalize(new Blob(this.chunks, { type })));
      };
      try {
        if (recorder.state === "recording") recorder.requestData();
        recorder.stop();
      } catch (err) {
        clearTimeout(timer);
        resolve(finalize(null));
      }
    });

    return waitForSpeech.then(stopMedia);
  },

  speak(text, onEnd) {
    if (!this.speechAvailable() || !text) {
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

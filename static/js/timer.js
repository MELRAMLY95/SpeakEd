window.SpeakEdTimer = {
  remaining: 0,
  id: null,
  start(seconds, onTick, onDone) {
    this.stop();
    this.remaining = seconds;
    onTick(this.remaining);
    this.id = setInterval(() => {
      this.remaining -= 1;
      onTick(this.remaining);
      if (this.remaining <= 0) {
        this.stop();
        onDone();
      }
    }, 1000);
  },
  stop() {
    if (this.id) clearInterval(this.id);
    this.id = null;
  },
  format(total) {
    const m = Math.floor(Math.max(total, 0) / 60);
    const s = Math.max(total, 0) % 60;
    return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  },
};

const canvas = document.getElementById("scoreChart");

if (canvas) {
  const labels = JSON.parse(canvas.dataset.labels || "[]");
  const scores = JSON.parse(canvas.dataset.scores || "[]");
  const MAX_SCORE = 50;

  const token = (name, fallback) => {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  };

  function draw() {
    const ctx = canvas.getContext("2d");
    // The canvas has a fixed attribute size but is stretched by CSS, so redraw
    // at the real pixel size to keep lines and text crisp on any display.
    const cssWidth = canvas.clientWidth || 640;
    const cssHeight = Math.round(cssWidth * 0.42);
    const dpr = window.devicePixelRatio || 1;

    canvas.width = cssWidth * dpr;
    canvas.height = cssHeight * dpr;
    canvas.style.height = `${cssHeight}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const ink = token("--ink", "#14141b");
    const muted = token("--muted", "#6b6c7b");
    const border = token("--border", "#e5e5ed");
    const brand = token("--brand", "#5b54e8");
    const surface = token("--surface", "#ffffff");

    const padLeft = 44;
    const padRight = 18;
    const padTop = 18;
    const padBottom = 34;
    const plotW = cssWidth - padLeft - padRight;
    const plotH = cssHeight - padTop - padBottom;

    ctx.clearRect(0, 0, cssWidth, cssHeight);
    ctx.fillStyle = surface;
    ctx.fillRect(0, 0, cssWidth, cssHeight);
    ctx.font = "11px Inter, system-ui, sans-serif";
    ctx.textBaseline = "middle";

    // Horizontal grid with value labels.
    ctx.strokeStyle = border;
    ctx.fillStyle = muted;
    ctx.lineWidth = 1;
    for (let i = 0; i <= 5; i += 1) {
      const value = (MAX_SCORE / 5) * i;
      const y = Math.round(padTop + plotH - (value / MAX_SCORE) * plotH) + 0.5;
      ctx.beginPath();
      ctx.moveTo(padLeft, y);
      ctx.lineTo(cssWidth - padRight, y);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.fillText(String(value), padLeft - 10, y);
    }

    if (!scores.length) {
      ctx.fillStyle = muted;
      ctx.textAlign = "center";
      ctx.font = "13px Inter, system-ui, sans-serif";
      ctx.fillText("Complete full exams to see your score trend.", cssWidth / 2, cssHeight / 2);
      return;
    }

    const xFor = (i) => padLeft + (i * plotW) / Math.max(scores.length - 1, 1);
    const yFor = (score) => padTop + plotH - (Math.min(score, MAX_SCORE) / MAX_SCORE) * plotH;

    // Soft area under the trend line.
    const fill = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
    fill.addColorStop(0, hexToRgba(brand, 0.28));
    fill.addColorStop(1, hexToRgba(brand, 0));
    ctx.beginPath();
    ctx.moveTo(xFor(0), padTop + plotH);
    scores.forEach((score, i) => ctx.lineTo(xFor(i), yFor(score)));
    ctx.lineTo(xFor(scores.length - 1), padTop + plotH);
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill();

    ctx.beginPath();
    scores.forEach((score, i) => {
      const x = xFor(i);
      const y = yFor(score);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = brand;
    ctx.lineWidth = 2.5;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();

    scores.forEach((score, i) => {
      const x = xFor(i);
      const y = yFor(score);
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = surface;
      ctx.fill();
      ctx.lineWidth = 2.5;
      ctx.strokeStyle = brand;
      ctx.stroke();
    });

    // Date labels, thinned out so they never collide on narrow screens.
    const every = Math.ceil(labels.length / Math.max(Math.floor(plotW / 60), 1));
    ctx.fillStyle = muted;
    ctx.textAlign = "center";
    labels.forEach((label, i) => {
      if (i % every !== 0 && i !== labels.length - 1) return;
      ctx.fillText(String(label).slice(5), xFor(i), cssHeight - padBottom / 2);
    });

    // Latest value called out above the final point.
    const lastIndex = scores.length - 1;
    ctx.fillStyle = ink;
    ctx.font = "600 12px Inter, system-ui, sans-serif";
    ctx.textAlign = lastIndex === 0 ? "left" : "right";
    ctx.fillText(String(scores[lastIndex]), xFor(lastIndex), yFor(scores[lastIndex]) - 14);
  }

  function hexToRgba(color, alpha) {
    const hex = color.replace("#", "");
    if (hex.length !== 6 && hex.length !== 3) return color;
    const full =
      hex.length === 3
        ? hex
            .split("")
            .map((c) => c + c)
            .join("")
        : hex;
    const r = parseInt(full.slice(0, 2), 16);
    const g = parseInt(full.slice(2, 4), 16);
    const b = parseInt(full.slice(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  draw();

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(draw, 150);
  });

  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
}

const canvas = document.getElementById("scoreChart");
if (canvas) {
  const labels = JSON.parse(canvas.dataset.labels || "[]");
  const scores = JSON.parse(canvas.dataset.scores || "[]");
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.fillStyle = "#fffdf8";
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "#e4ddd2";
  ctx.beginPath();
  ctx.moveTo(40, 20);
  ctx.lineTo(40, h - 30);
  ctx.lineTo(w - 16, h - 30);
  ctx.stroke();
  if (scores.length) {
    const max = 50;
    ctx.strokeStyle = "#1d6d62";
    ctx.lineWidth = 2;
    ctx.beginPath();
    scores.forEach((score, i) => {
      const x = 40 + (i * (w - 70)) / Math.max(scores.length - 1, 1);
      const y = h - 30 - (score / max) * (h - 60);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.fillStyle = "#5b6778";
    labels.forEach((label, i) => {
      const x = 40 + (i * (w - 70)) / Math.max(labels.length - 1, 1);
      ctx.fillText(label.slice(5), x - 16, h - 12);
    });
  } else {
    ctx.fillStyle = "#5b6778";
    ctx.fillText("Complete full exams to see your score trend.", 60, h / 2);
  }
}

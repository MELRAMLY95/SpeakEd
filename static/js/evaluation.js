document.querySelectorAll("form.stack").forEach((form) => {
  form.addEventListener("submit", () => {
    const btn = form.querySelector("button");
    if (btn) btn.disabled = true;
  });
});

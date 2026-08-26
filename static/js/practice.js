document.querySelectorAll(".practice-grid a").forEach((link) => {
  link.addEventListener("keydown", (event) => {
    if (event.key === "Enter") link.click();
  });
});

document.querySelectorAll("[data-refresh-images]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Loading…";
    try {
      const response = await fetch("/practice/refresh-images", {
        method: "POST",
        headers: window.SpeakEdCsrf
          ? window.SpeakEdCsrf.headers({ "Content-Type": "application/json" })
          : { "Content-Type": "application/json" },
      });
      const data = await response.json();
      if (data.success) {
        window.location.reload();
        return;
      }
      throw new Error("Refresh was not successful");
    } catch (error) {
      btn.disabled = false;
      btn.textContent = original;
    }
  });
});


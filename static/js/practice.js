document.querySelectorAll(".practice-grid a").forEach((link) => {
  link.addEventListener("keydown", (event) => {
    if (event.key === "Enter") link.click();
  });
});

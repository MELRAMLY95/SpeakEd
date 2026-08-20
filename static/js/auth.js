document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || !form.matches("[data-signup]")) return;
  const password = form.password.value;
  const confirm = form.confirm.value;
  if (password !== confirm) {
    event.preventDefault();
    // Use toast notification instead of alert
    if (window.showToast) {
      showToast("Passwords do not match.", "error");
    } else {
      alert("Passwords do not match.");
    }
  }
});

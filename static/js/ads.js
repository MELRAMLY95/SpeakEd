(function () {
  var slots = document.querySelectorAll(".ad-slot[data-ad-live='1']");
  if (!slots.length) return;

  function hideSlots() {
    slots.forEach(function (slot) {
      slot.hidden = true;
    });
  }

  try {
    window.adsbygoogle = window.adsbygoogle || [];
    window.adsbygoogle.push({});
  } catch (error) {
    hideSlots();
    return;
  }

  window.addEventListener(
    "error",
    function (event) {
      var target = event && event.target;
      var src = (target && target.src) || "";
      if (src.indexOf("googlesyndication.com") !== -1 || src.indexOf("doubleclick.net") !== -1) {
        hideSlots();
      }
    },
    true
  );
})();

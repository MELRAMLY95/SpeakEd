(function () {
  var slots = document.querySelectorAll(".ad-slot[data-ad-live='1']");
  if (!slots.length) return;

  window.adsbygoogle = window.adsbygoogle || [];
  document.querySelectorAll("ins.adsbygoogle[data-ad-slot]").forEach(function () {
    try {
      window.adsbygoogle.push({});
    } catch (error) {
      // Leave the labelled slot visible if a creative fails to fill.
    }
  });
})();

// Keep the scroll position when adding to the cart or toggling a favorite from
// the catalog (and similar list pages). Those actions POST and redirect back to
// the same URL, which would otherwise reload the page scrolled to the top.
(function () {
  "use strict";
  var KEY = "amsScrollRestore";

  try {
    history.scrollRestoration = "manual";
  } catch (e) {}

  function here() {
    return location.pathname + location.search;
  }

  // Remember where we were, right before such a form submits.
  document.addEventListener(
    "submit",
    function (e) {
      var f = e.target;
      if (
        f &&
        f.matches &&
        f.matches('form[action*="/cart/add/"], form[action*="/favorites/toggle/"]')
      ) {
        try {
          sessionStorage.setItem(
            KEY,
            JSON.stringify({ p: here(), y: window.scrollY })
          );
        } catch (err) {}
      }
    },
    true
  );

  // Restore it once, only for the same URL we saved it on.
  try {
    var saved = JSON.parse(sessionStorage.getItem(KEY) || "null");
    if (saved && saved.p === here()) {
      sessionStorage.removeItem(KEY);
      // Jump instantly (no smooth animation from the top).
      var jump = function () {
        window.scrollTo({ top: saved.y, left: 0, behavior: "instant" });
      };
      jump();
      // Re-apply after full load in case late images shifted the layout.
      window.addEventListener("load", jump);
    }
  } catch (err) {}
})();

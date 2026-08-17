// «О компании» scroll-reveal. The .rv elements are only hidden once this runs
// (it adds .reveal-ready), so with JS disabled everything is fully visible.
(function () {
  "use strict";
  var page = document.querySelector(".about-page");
  if (!page) return;
  page.classList.add("reveal-ready");

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) {
        e.target.classList.add("in");
        io.unobserve(e.target);
      }
    });
  }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });

  page.querySelectorAll(".rv").forEach(function (el, i) {
    el.style.transitionDelay = (Math.min(i % 4, 3) * 70) + "ms";
    io.observe(el);
  });
})();

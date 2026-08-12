// Autocomplete dropdown for the navbar catalog search. Fetches /search/suggest/
// as the user types and shows matching products as «Brand (bold) — name».
(function () {
  "use strict";

  var input = document.querySelector('form[role="search"] input[name="q"]');
  if (!input) return; // search box only exists on catalog pages
  var form = input.closest("form");
  form.style.position = "relative";
  input.setAttribute("autocomplete", "off");

  var menu = document.createElement("div");
  menu.className = "search-suggest";
  menu.setAttribute("role", "listbox");
  form.appendChild(menu);

  var items = [];
  var active = -1;
  var timer = null;
  var controller = null;

  function hide() {
    menu.classList.remove("show");
    menu.innerHTML = "";
    items = [];
    active = -1;
  }

  function setActive(i) {
    if (!items.length) return;
    if (active > -1) items[active].classList.remove("active");
    active = (i + items.length) % items.length;
    items[active].classList.add("active");
    items[active].scrollIntoView({ block: "nearest" });
  }

  function render(results) {
    hide();
    if (!results.length) return;
    results.forEach(function (r) {
      var a = document.createElement("a");
      a.className = "search-suggest-item";
      a.href = r.url;
      a.setAttribute("role", "option");
      var b = document.createElement("strong");
      b.textContent = r.brand; // textContent — never innerHTML (XSS-safe)
      a.appendChild(b);
      a.appendChild(document.createTextNode(" " + r.name));
      menu.appendChild(a);
      items.push(a);
    });
    menu.classList.add("show");
  }

  function suggest(q) {
    if (controller) controller.abort();
    controller = new AbortController();
    fetch("/search/suggest/?q=" + encodeURIComponent(q), {
      signal: controller.signal,
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then(function (r) { return r.ok ? r.json() : { results: [] }; })
      .then(function (d) {
        if (input.value.trim() === q) render(d.results || []);
      })
      .catch(function () {}); // ignore aborts / network errors
  }

  input.addEventListener("input", function () {
    var q = input.value.trim();
    clearTimeout(timer);
    if (q.length < 2) { hide(); return; }
    timer = setTimeout(function () { suggest(q); }, 180);
  });

  input.addEventListener("keydown", function (e) {
    if (!menu.classList.contains("show")) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
    else if (e.key === "Enter" && active > -1) {
      e.preventDefault();
      window.location.href = items[active].href;
    } else if (e.key === "Escape") { hide(); }
  });

  document.addEventListener("click", function (e) {
    if (!form.contains(e.target)) hide();
  });
})();

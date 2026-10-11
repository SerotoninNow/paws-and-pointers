// Small behaviours for the blog. Kept in a file (not inline) so the
// Content-Security-Policy can forbid inline scripts.
(function () {
  // Forms with data-confirm ask before submitting.
  document.addEventListener("submit", function (e) {
    var message = e.target.getAttribute("data-confirm");
    if (message && !confirm(message)) e.preventDefault();
  });

  // Selects with data-autosubmit submit their form when changed.
  document.addEventListener("change", function (e) {
    if (e.target.hasAttribute("data-autosubmit")) e.target.form.submit();
  });

  // Close the tag menu on Escape or a click outside it.
  var menu = document.getElementById("tag-menu");
  if (menu) {
    document.addEventListener("click", function (e) {
      if (!menu.contains(e.target)) menu.open = false;
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") menu.open = false;
    });
  }
})();

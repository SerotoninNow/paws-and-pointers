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

  // Animated profile pictures play only while the pointer is over them.
  // mouseover/mouseout bubble, so one listener covers every picture.
  function play(e) {
    var img = e.target;
    if (!img.dataset || !img.dataset.animated || img.dataset.still) return;
    img.dataset.still = img.src;
    img.src = img.dataset.animated;
  }
  function rest(e) {
    var img = e.target;
    if (!img.dataset || !img.dataset.still) return;
    img.src = img.dataset.still;
    delete img.dataset.still;
  }
  document.addEventListener("mouseover", play);
  document.addEventListener("mouseout", rest);

  // Profile settings: once a picture is chosen, show the cropping choice and
  // preview the picture with it.
  var input = document.getElementById("avatar-input");
  var crop = document.getElementById("avatar-crop");
  var preview = document.getElementById("avatar-preview");
  if (input && crop && preview) {
    var positions = { center: "50% 50%", top: "50% 0", bottom: "50% 100%", left: "0 50%", right: "100% 50%" };
    var applyCrop = function () {
      preview.style.objectFit = crop.value === "fit" ? "contain" : "cover";
      preview.style.objectPosition = positions[crop.value] || "50% 50%";
    };
    var showChosen = function () {
      if (preview.src) URL.revokeObjectURL(preview.src);
      var file = input.files[0];
      preview.hidden = !file;
      document.getElementById("avatar-crop-field").hidden = !file;
      document.getElementById("avatar-current").hidden = !!file;
      if (file) preview.src = URL.createObjectURL(file);
      else preview.removeAttribute("src");
      applyCrop();
    };
    input.addEventListener("change", showChosen);
    crop.addEventListener("change", applyCrop);
    showChosen();  // some browsers keep the chosen file across a reload
  }

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

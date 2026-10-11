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

  // Post editor: the post is edited as a run of blocks, text and images in
  // turn, so a pasted image sits in the text where it will appear. The blocks
  // are written back, as Markdown, into the hidden textarea that is submitted.
  var body = document.getElementById("post-body");
  var blocksBox = document.getElementById("post-blocks");
  if (body && blocksBox) {
    var token = body.form.elements["csrf_token"].value;
    var status = document.getElementById("upload-status");
    var previewBox = document.getElementById("post-preview");
    // A line holding only an image, e.g. ![a cat](/media/4){ width=400 }
    var IMAGE_LINE = /^!\[([^\]]*)\]\(([^)\s]+)\)(?:\{\s*width=(\d+)\s*\})?\s*$/;
    var segs = [];
    var last = null;  // { seg, pos }: where the text cursor last was
    var timer = null;
    var resizing = null;

    var post = function (url, data) {
      data.append("csrf_token", token);
      return fetch(url, { method: "POST", body: data, credentials: "same-origin" });
    };
    var hasText = function (text) { return /\S/.test(text); };
    var trimBlank = function (text) {
      return text.replace(/^\s*\n/, "").replace(/\n\s*$/, "");
    };

    // Markdown -> blocks. Image lines inside ``` code fences stay as text.
    var parse = function (markdown) {
      var out = [];
      var lines = [];
      var fenced = false;
      var flush = function () {
        out.push({ type: "text", text: lines.join("\n") });
        lines = [];
      };
      markdown.replace(/\r\n?/g, "\n").split("\n").forEach(function (line) {
        if (/^\s*(```|~~~)/.test(line)) fenced = !fenced;
        var m = fenced ? null : IMAGE_LINE.exec(line);
        if (!m) { lines.push(line); return; }
        flush();
        out.push({ type: "image", alt: m[1], src: m[2], width: m[3] ? Number(m[3]) : null });
      });
      flush();
      return out;
    };

    // Blocks -> Markdown. Images still uploading are left out.
    var serialize = function () {
      var parts = [];
      segs.forEach(function (seg) {
        if (seg.type === "text") {
          if (hasText(seg.text)) parts.push(trimBlank(seg.text));
        } else if (seg.src) {
          parts.push(
            "![" + seg.alt.replace(/[\[\]\n]/g, " ") + "](" + seg.src + ")" +
            (seg.width ? "{ width=" + seg.width + " }" : "")
          );
        }
      });
      return parts.join("\n\n");
    };

    var refresh = function () {
      var data = new FormData();
      data.append("body_md", body.value);
      post(body.dataset.previewUrl, data)
        .then(function (r) { if (!r.ok) throw new Error(); return r.text(); })
        .then(function (html) { previewBox.innerHTML = html; })
        .catch(function () { status.textContent = "Couldn't update the preview."; });
    };
    var sync = function () {
      body.value = serialize();
      clearTimeout(timer);
      timer = setTimeout(refresh, 500);
    };

    // Keep the blocks as text, image, text, ... starting and ending with
    // text, so there is always somewhere to type around an image.
    var tidy = function () {
      var out = [];
      segs.forEach(function (seg) {
        var prev = out[out.length - 1];
        if (seg.type === "image") {
          if (!prev || prev.type === "image") out.push({ type: "text", text: "" });
          out.push(seg);
        } else {
          seg.text = hasText(seg.text) ? trimBlank(seg.text) : "";
          if (prev && prev.type === "text") {
            prev.text = prev.text && seg.text ? prev.text + "\n\n" + seg.text : prev.text || seg.text;
          } else {
            out.push(seg);
          }
        }
      });
      if (!out.length || out[out.length - 1].type === "image") out.push({ type: "text", text: "" });
      segs = out;
    };

    var grow = function (area) {
      area.style.height = "auto";
      area.style.height = area.scrollHeight + "px";
    };

    var textBlock = function (seg) {
      var area = document.createElement("textarea");
      area.className = "block-text";
      area.rows = 1;
      area.value = seg.text;
      area.placeholder = segs.length === 1
        ? "Write your post here. Paste an image to put it in the text."
        : "Text";
      area.setAttribute("aria-label", "Post text");
      var remember = function () { last = { seg: seg, pos: area.selectionStart }; };
      area.addEventListener("input", function () { seg.text = area.value; grow(area); remember(); sync(); });
      area.addEventListener("blur", remember);
      area.addEventListener("keyup", remember);
      area.addEventListener("click", remember);
      area.addEventListener("paste", function (e) {
        var files = e.clipboardData && e.clipboardData.files;
        if (addImages(files, seg, area.selectionStart)) e.preventDefault();
      });
      seg.el = area;
      return area;
    };

    var field = function (labelText, input) {
      var label = document.createElement("label");
      label.appendChild(document.createTextNode(labelText));
      label.appendChild(input);
      return label;
    };

    var imageBlock = function (seg) {
      var block = document.createElement("div");
      block.className = "block-image";
      seg.el = block;
      if (!seg.src) {
        block.classList.add("pending");
        block.textContent = "Uploading image...";
        return block;
      }
      // The browser puts a resize grip on this box's bottom-right corner.
      var box = document.createElement("span");
      box.className = "resizable";
      if (seg.width) box.style.width = seg.width + "px";
      var img = document.createElement("img");
      img.src = seg.src;
      img.alt = seg.alt;
      box.appendChild(img);

      var alt = document.createElement("input");
      alt.type = "text";
      alt.value = seg.alt;
      alt.placeholder = "What the image shows";
      alt.addEventListener("input", function () { seg.alt = alt.value; img.alt = alt.value; sync(); });

      var width = document.createElement("input");
      width.type = "number";
      width.min = 48;
      width.max = 1600;
      width.value = seg.width || "";
      width.placeholder = "full";
      width.addEventListener("change", function () {
        seg.width = Math.min(1600, Math.max(48, Math.round(Number(width.value)))) || null;
        width.value = seg.width || "";
        box.style.width = seg.width ? seg.width + "px" : "";
        sync();
      });

      var remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn danger small";
      remove.textContent = "Remove";
      remove.addEventListener("click", function () {
        segs.splice(segs.indexOf(seg), 1);
        render();
        sync();
      });

      box.addEventListener("mousedown", function () {
        resizing = { box: box, seg: seg, input: width, start: Math.round(box.getBoundingClientRect().width) };
      });

      var tools = document.createElement("div");
      tools.className = "block-image-tools";
      tools.appendChild(field("Description", alt));
      tools.appendChild(field("Width (px)", width));
      tools.appendChild(remove);
      block.appendChild(box);
      block.appendChild(tools);
      return block;
    };

    var render = function () {
      tidy();
      blocksBox.textContent = "";
      segs.forEach(function (seg) {
        blocksBox.appendChild(seg.type === "text" ? textBlock(seg) : imageBlock(seg));
      });
      blocksBox.classList.toggle("single", segs.length === 1);
      segs.forEach(function (seg) { if (seg.type === "text") grow(seg.el); });
    };

    var upload = function (file, seg) {
      status.textContent = "Uploading...";
      var data = new FormData();
      data.append("image", file);
      post(body.dataset.uploadUrl, data)
        .then(function (r) {
          return r.json().then(function (j) {
            if (!r.ok) throw new Error(j.error);
            return j;
          });
        })
        .then(function (j) {
          seg.src = j.url;
          seg.width = j.width;
          status.textContent = "";
          // Swap just this block, so typing elsewhere isn't interrupted.
          var old = seg.el;
          if (old.parentNode) old.parentNode.replaceChild(imageBlock(seg), old);
          sync();
        })
        .catch(function (err) {
          var at = segs.indexOf(seg);
          if (at >= 0) segs.splice(at, 1);
          render();
          sync();
          status.textContent = (err && err.message) || "The upload failed. Try again.";
        });
    };

    // Put images into the text at `pos` of the text block `seg`, splitting
    // it in two. With no block to split, they go at the end.
    var addImages = function (files, seg, pos) {
      var images = Array.prototype.filter.call(files || [], function (f) {
        return f.type.indexOf("image/") === 0;
      });
      if (!images.length) return false;
      var fresh = images.map(function () {
        return { type: "image", alt: "", src: null, width: null };
      });
      var after = { type: "text", text: "" };
      var at = seg ? segs.indexOf(seg) : -1;
      if (at < 0) {
        segs = segs.concat(fresh, [after]);
      } else {
        after.text = seg.text.slice(pos);
        seg.text = seg.text.slice(0, pos);
        segs.splice.apply(segs, [at + 1, 0].concat(fresh, [after]));
      }
      render();
      if (after.el) {
        after.el.focus();
        after.el.setSelectionRange(0, 0);
        last = { seg: after, pos: 0 };
      }
      images.forEach(function (file, i) { upload(file, fresh[i]); });
      sync();
      return true;
    };
    var addAtCursor = function (files) {
      return addImages(files, last && last.seg, last ? last.pos : 0);
    };

    blocksBox.addEventListener("dragover", function (e) {
      e.preventDefault();
      blocksBox.classList.add("dropping");
    });
    blocksBox.addEventListener("dragleave", function () { blocksBox.classList.remove("dropping"); });
    blocksBox.addEventListener("drop", function (e) {
      blocksBox.classList.remove("dropping");
      if (addAtCursor(e.dataTransfer && e.dataTransfer.files)) e.preventDefault();
    });
    // A click on the box's empty space goes to the last text block.
    blocksBox.addEventListener("click", function (e) {
      if (e.target === blocksBox) segs[segs.length - 1].el.focus();
    });
    var picker = document.getElementById("post-image-input");
    picker.addEventListener("change", function () {
      addAtCursor(picker.files);
      picker.value = "";
    });

    // When a resize ends, record the box's new width.
    document.addEventListener("mouseup", function () {
      if (!resizing) return;
      var r = resizing;
      resizing = null;
      var width = Math.round(r.box.getBoundingClientRect().width);
      if (width === r.start) return;  // a plain click, not a resize
      r.seg.width = width;
      r.input.value = width;
      sync();
    });

    body.form.addEventListener("submit", function () { body.value = serialize(); });

    // Swap the plain textarea (what you get without JavaScript) for the blocks.
    segs = parse(body.value);
    body.hidden = true;
    body.required = false;
    blocksBox.hidden = false;
    render();
    refresh();
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

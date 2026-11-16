(function () {
  'use strict';

  function csrf() {
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  // Ask before destructive submits: <form data-confirm="Delete this?">
  document.addEventListener('submit', function (e) {
    var form = e.target;
    var message = form.getAttribute('data-confirm') || (e.submitter && e.submitter.getAttribute('data-confirm'));
    if (message && !window.confirm(message)) { e.preventDefault(); return; }
    if (form.hasAttribute('data-busy')) {
      form.classList.add('is-busy');
      form.querySelectorAll('button[type=submit], button:not([type])').forEach(function (b) { b.disabled = true; });
    }
  });

  // Auto-submit small GET forms (servings scaler, filters).
  document.querySelectorAll('[data-autosubmit]').forEach(function (el) {
    el.addEventListener('change', function () { el.form.submit(); });
  });

  // Copy-to-clipboard buttons: <button data-copy="#input-id">
  document.querySelectorAll('[data-copy]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = document.querySelector(btn.getAttribute('data-copy'));
      if (!input) return;
      var done = function () { var t = btn.textContent; btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = t; }, 1500); };
      if (navigator.clipboard) navigator.clipboard.writeText(input.value).then(done, function () { input.select(); });
      else { input.select(); document.execCommand('copy'); done(); }
    });
  });

  // Tabs: <div class="tabs" role="tablist"><button role="tab" aria-controls="panel-id">
  document.querySelectorAll('[role=tablist]').forEach(function (list) {
    var tabs = Array.prototype.slice.call(list.querySelectorAll('[role=tab]'));
    function select(tab) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
        document.getElementById(t.getAttribute('aria-controls')).hidden = !on;
      });
    }
    tabs.forEach(function (tab, i) {
      tab.addEventListener('click', function () { select(tab); });
      tab.addEventListener('keydown', function (e) {
        var next = e.key === 'ArrowRight' ? tabs[(i + 1) % tabs.length] : e.key === 'ArrowLeft' ? tabs[(i - 1 + tabs.length) % tabs.length] : null;
        if (next) { e.preventDefault(); select(next); next.focus(); }
      });
    });
  });

  // Repeating rows (ingredients, steps): a <template data-row-template="name">, a container
  // [data-rows="name"], an add button [data-add-row="name"], and remove buttons [data-remove-row].
  function renumber(container) {
    container.querySelectorAll('[data-step-number]').forEach(function (el, i) { el.textContent = (i + 1) + '.'; });
  }
  document.querySelectorAll('[data-add-row]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var name = btn.getAttribute('data-add-row');
      var template = document.querySelector('template[data-row-template="' + name + '"]');
      var container = document.querySelector('[data-rows="' + name + '"]');
      var row = template.content.firstElementChild.cloneNode(true);
      container.appendChild(row);
      renumber(container);
      var first = row.querySelector('input, textarea');
      if (first) first.focus();
    });
  });
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-remove-row]');
    if (!btn) return;
    var row = btn.closest('[data-row]');
    var container = row.parentNode;
    row.remove();
    renumber(container);
  });
  // Enter in the last ingredient name adds a new row instead of submitting the form.
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter' || !e.target.matches('[data-rows] input')) return;
    e.preventDefault();
    var container = e.target.closest('[data-rows]');
    var btn = document.querySelector('[data-add-row="' + container.getAttribute('data-rows') + '"]');
    var rows = container.querySelectorAll('[data-row]');
    if (btn && e.target.closest('[data-row]') === rows[rows.length - 1]) btn.click();
  });


  // Tag badges: <input data-tag-input="datalist-id"> holding "a, b, c" becomes removable badges plus
  // a box for new tags (Enter or comma adds one; Backspace in an empty box removes the last). The
  // original input stays in the form, hidden, and is kept in sync, so the server still gets "a, b, c".
  document.querySelectorAll('input[data-tag-input]').forEach(function (source) {
    var tags = [];
    source.value.split(',').forEach(function (t) { t = t.trim().toLowerCase(); if (t && tags.indexOf(t) < 0) tags.push(t); });

    var box = document.createElement('div');
    box.className = 'tag-box';
    var list = document.createElement('span');
    list.setAttribute('role', 'list');
    list.style.display = 'contents';
    var entry = document.createElement('input');
    entry.type = 'text';
    entry.id = source.id;
    entry.autocomplete = 'off';
    entry.placeholder = 'Add a tag';
    var datalist = source.getAttribute('data-tag-input');
    if (datalist) entry.setAttribute('list', datalist);
    if (source.getAttribute('aria-describedby')) entry.setAttribute('aria-describedby', source.getAttribute('aria-describedby'));
    var live = document.createElement('span');
    live.className = 'sr-only';
    live.setAttribute('aria-live', 'polite');

    source.id = source.id + '-value';
    source.type = 'hidden';
    source.parentNode.insertBefore(box, source);
    box.appendChild(list);
    box.appendChild(entry);
    box.appendChild(live);
    box.addEventListener('click', function (e) { if (e.target === box) entry.focus(); });

    function sync() { source.value = tags.join(', '); }
    function render() {
      list.textContent = '';
      tags.forEach(function (tag, i) {
        var chip = document.createElement('span');
        chip.className = 'tag';
        chip.setAttribute('role', 'listitem');
        chip.appendChild(document.createTextNode(tag));
        var remove = document.createElement('button');
        remove.type = 'button';
        remove.textContent = '×';
        remove.setAttribute('aria-label', 'Remove tag ' + tag);
        remove.addEventListener('click', function () {
          tags.splice(i, 1); sync(); render(); live.textContent = 'Removed ' + tag;
          entry.focus();
        });
        chip.appendChild(remove);
        list.appendChild(chip);
      });
    }
    function add(text) {
      var added = [];
      text.split(',').forEach(function (t) {
        t = t.trim().toLowerCase();
        if (t && tags.indexOf(t) < 0) { tags.push(t); added.push(t); }
      });
      if (added.length) { sync(); render(); live.textContent = 'Added ' + added.join(', '); }
    }
    entry.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        add(entry.value);
        entry.value = '';
      } else if (e.key === 'Backspace' && !entry.value && tags.length) {
        var gone = tags.pop(); sync(); render(); live.textContent = 'Removed ' + gone;
      }
    });
    // Picking a suggestion, pasting "a, b", or leaving the box with text in it all add the tag.
    function isSuggestion(value) {
      var options = datalist ? document.querySelectorAll('#' + datalist + ' option') : [];
      return Array.prototype.some.call(options, function (o) { return o.value === value; });
    }
    entry.addEventListener('input', function (e) {
      // A datalist pick arrives as an input event with no typed character (not an InputEvent in some
      // browsers, inputType "insertReplacementText" in others).
      var picked = !(e instanceof InputEvent) || e.inputType === 'insertReplacementText';
      if (entry.value.indexOf(',') >= 0 || (picked && isSuggestion(entry.value))) {
        add(entry.value); entry.value = '';
      }
    });
    entry.addEventListener('blur', function () { if (entry.value.trim()) { add(entry.value); entry.value = ''; } });
    entry.form && entry.form.addEventListener('submit', function () { if (entry.value.trim()) { add(entry.value); entry.value = ''; } });
    render();
  });

  // Shopping list checkboxes save as they're ticked.
  function updateProgress() {
    var boxes = document.querySelectorAll('.shop-item input[type=checkbox]');
    var done = Array.prototype.filter.call(boxes, function (b) { return b.checked; }).length;
    var bar = document.querySelector('[data-progress]');
    var label = document.querySelector('[data-progress-label]');
    if (bar) bar.style.width = (boxes.length ? (100 * done / boxes.length) : 0) + '%';
    if (label) label.textContent = (boxes.length - done) + ' of ' + boxes.length + ' left';
  }
  document.querySelectorAll('.shop-item input[type=checkbox]').forEach(function (box) {
    box.addEventListener('change', function () {
      var item = box.closest('.shop-item');
      item.classList.toggle('done', box.checked);
      updateProgress();
      var body = new FormData();
      body.append('checked', box.checked ? '1' : '0');
      fetch(box.getAttribute('data-url'), {
        method: 'POST', body: body, credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrf(), 'X-Requested-With': 'fetch' },
      }).then(function (r) { if (!r.ok) throw new Error(r.status); }).catch(function () {
        box.checked = !box.checked;
        item.classList.toggle('done', box.checked);
        updateProgress();
        window.alert('Couldn\'t save that. Check your connection and try again.');
      });
    });
  });
})();

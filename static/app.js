// Theme pre-paint script (index.html <head>) already applied any saved
// override before this file loads, so no flash-of-wrong-theme handling
// is needed here.

function currentEffectiveTheme() {
  var explicit = document.documentElement.getAttribute('data-theme');
  if (explicit) return explicit;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function updateThemeToggleIcon() {
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;
  btn.textContent = currentEffectiveTheme() === 'dark' ? '☀' : '☾';
}

function setMode(mode) {
  var groupLabel = document.getElementById('mode-label-group');
  var individualLabel = document.getElementById('mode-label-individual');
  var isIndividual = mode === 'individual';
  if (groupLabel) groupLabel.classList.toggle('active', !isIndividual);
  if (individualLabel) individualLabel.classList.toggle('active', isIndividual);

  var selfRow = document.getElementById('include_self_row');
  var selfNote = document.getElementById('include_self_forced_note');
  if (selfRow) selfRow.style.display = isIndividual ? 'none' : 'flex';
  if (selfNote) selfNote.style.display = isIndividual ? 'block' : 'none';

  var numLabel = document.getElementById('num_suggestions_label');
  if (numLabel) numLabel.childNodes[0].textContent = isIndividual ? 'Suggestions per person ' : 'How many suggestions? ';

  var perDayLegend = document.getElementById('per_day_legend');
  if (perDayLegend) perDayLegend.childNodes[0].textContent = 'Suggestions per day' + (isIndividual ? ' (per person) ' : ' ');
}

// Simple "meeting length" field mirrors into the advanced min/max pair.
function syncSimpleDuration(val) {
  var minEl = document.getElementById('min_duration_minutes');
  var maxEl = document.getElementById('max_duration_minutes');
  if (minEl) minEl.value = val;
  if (maxEl) maxEl.value = val;
}

// If the user edits the advanced range directly, reflect the shortest
// value back onto the simple field so the two stay roughly in sync.
function syncFromAdvancedDuration() {
  var simple = document.getElementById('simple_duration');
  var minEl = document.getElementById('min_duration_minutes');
  if (simple && minEl) simple.value = minEl.value;
}

// A named IANA zone (not a raw UTC offset) so the server can apply correct
// DST rules across a multi-day range instead of one fixed offset for every day.
var tzField = document.getElementById('tz_name');
if (tzField) {
  try {
    tzField.value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch (e) {
    tzField.value = 'UTC';
  }
}

var themeToggle = document.getElementById('theme-toggle');
if (themeToggle) {
  themeToggle.addEventListener('click', function () {
    var next = currentEffectiveTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    updateThemeToggleIcon();
  });
  updateThemeToggleIcon();
}

var groupRadio = document.querySelector('input[name="schedule_mode"][value="group"]');
var individualRadio = document.querySelector('input[name="schedule_mode"][value="individual"]');
if (groupRadio) groupRadio.addEventListener('change', function () { setMode('group'); });
if (individualRadio) individualRadio.addEventListener('change', function () { setMode('individual'); });

var simpleDurationField = document.getElementById('simple_duration');
if (simpleDurationField) {
  simpleDurationField.addEventListener('input', function () { syncSimpleDuration(this.value); });
}

var minDurationField = document.getElementById('min_duration_minutes');
var maxDurationField = document.getElementById('max_duration_minutes');
if (minDurationField) minDurationField.addEventListener('input', syncFromAdvancedDuration);
if (maxDurationField) maxDurationField.addEventListener('input', syncFromAdvancedDuration);

var perDayNoPref = document.getElementById('per_day_no_pref');
if (perDayNoPref) {
  perDayNoPref.addEventListener('change', function () {
    var wrap = document.getElementById('per_day_count_wrap');
    if (wrap) wrap.style.display = this.checked ? 'none' : 'block';
  });
}

// The info-icon tooltips are centered under their icon with pure CSS
// (left: 50%; transform: translateX(-50%)), which has no awareness of the
// viewport edge — a tooltip near the left/right/top of the page can render
// partly or fully off-screen. This clamps it back into view on hover/focus.
function positionTooltip(icon) {
  var tip = icon.querySelector('.tooltip-text');
  if (!tip) return;
  var margin = 10;

  // Reset to the CSS default before measuring, so repeat hovers don't
  // compound a previous adjustment.
  tip.style.transform = 'translateX(-50%)';
  tip.style.bottom = '135%';
  tip.style.top = 'auto';

  var rect = tip.getBoundingClientRect();
  var shiftX = 0;
  if (rect.left < margin) {
    shiftX = margin - rect.left;
  } else if (rect.right > window.innerWidth - margin) {
    shiftX = (window.innerWidth - margin) - rect.right;
  }
  if (shiftX !== 0) {
    tip.style.transform = 'translateX(calc(-50% + ' + shiftX + 'px))';
  }

  // Not enough room above the icon (e.g. near the top of the page) — flip
  // it to open downward instead.
  if (rect.top < margin) {
    tip.style.bottom = 'auto';
    tip.style.top = '135%';
  }
}
document.querySelectorAll('.info-icon').forEach(function (icon) {
  icon.addEventListener('mouseenter', function () { positionTooltip(icon); });
  icon.addEventListener('focus', function () { positionTooltip(icon); });
});

// Shows a brief skeleton placeholder while the form's POST round-trip to
// Google is in flight (only visually meaningful under style-editorial.css,
// which is the one that actually styles .skeleton-line — under the
// original stylesheet this element has no look of its own).
var checkForm = document.getElementById('check-form');
var skeletonLoader = document.getElementById('skeleton-loader');
if (checkForm && skeletonLoader) {
  checkForm.addEventListener('submit', function () {
    skeletonLoader.style.display = 'block';
  });
}

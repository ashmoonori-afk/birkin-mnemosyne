/* birkin-mnemosyne — progressive motion.
   Baseline HTML/CSS shows every element in its final state. This script only
   adds motion when IntersectionObserver exists and the visitor has not asked
   for reduced motion, and it settles everything if that preference changes. */
(function () {
  'use strict';

  var root = document.documentElement;
  var reduceQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  var canObserve = 'IntersectionObserver' in window;

  var observers = [];
  var rafId = 0;
  var countStarted = false;
  var active = false;

  var countEl = document.querySelector('[data-count-to]');
  var barEl = document.querySelector('[data-count-bar]');
  var countFinalText = countEl ? countEl.textContent : '';
  var countFrom = countEl ? Number(countEl.getAttribute('data-count-from')) : 0;
  var countTo = countEl ? Number(countEl.getAttribute('data-count-to')) : 0;
  var formatter = window.Intl && Intl.NumberFormat ? new Intl.NumberFormat('en-US') : null;

  function format(value) {
    return formatter ? formatter.format(value) : String(value);
  }

  function prefersReduced() {
    return !!(reduceQuery && reduceQuery.matches);
  }

  /* (d) Measurement: 45,128 -> 1,297, always settling on the source text. */
  function settleCount() {
    if (rafId) window.cancelAnimationFrame(rafId);
    rafId = 0;
    if (countEl) countEl.textContent = countFinalText;
    if (barEl) barEl.style.transform = '';
  }

  function runCount() {
    if (!countEl || countStarted || !countFrom) return;
    countStarted = true;
    var duration = 1600;
    var start = 0;
    countEl.textContent = format(countFrom);
    if (barEl) barEl.style.transform = 'scaleX(1)';

    function step(now) {
      if (!start) start = now;
      var t = Math.min(1, (now - start) / duration);
      if (t >= 1) {
        settleCount();
        return;
      }
      var eased = 1 - Math.pow(1 - t, 3);
      var value = Math.round(countFrom + (countTo - countFrom) * eased);
      countEl.textContent = format(value);
      if (barEl) barEl.style.transform = 'scaleX(' + (value / countFrom).toFixed(4) + ')';
      rafId = window.requestAnimationFrame(step);
    }
    rafId = window.requestAnimationFrame(step);
  }

  /* (c) Reveals: hide only what the observer reports below the viewport. */
  function watchReveals() {
    var items = document.querySelectorAll('[data-reveal]');
    var io = new IntersectionObserver(function (entries) {
      var batch = 0;
      entries.forEach(function (entry) {
        var el = entry.target;
        if (entry.isIntersecting) {
          if (el.classList.contains('is-pending')) {
            el.style.transitionDelay = Math.min(batch, 3) * 80 + 'ms';
            batch += 1;
            el.classList.add('is-revealing');
            el.classList.remove('is-pending');
          }
          io.unobserve(el);
        } else if (!el.classList.contains('is-revealing') &&
                   entry.boundingClientRect.top > (window.innerHeight || root.clientHeight)) {
          el.classList.add('is-pending');
        }
      });
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0 });
    Array.prototype.forEach.call(items, function (el) { io.observe(el); });
    observers.push(io);
  }

  /* (a)(b) Looping figures run only while on screen. */
  function watchLoops() {
    var loops = document.querySelectorAll('[data-loop]');
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        entry.target.classList.toggle('is-playing', entry.isIntersecting);
      });
    }, { threshold: 0.2 });
    Array.prototype.forEach.call(loops, function (el) { io.observe(el); });
    observers.push(io);
  }

  function watchCount() {
    if (!countEl || countStarted) return;
    var target = countEl.closest('.numbers') || countEl;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          io.disconnect();
          runCount();
        }
      });
    }, { threshold: 0.6 });
    io.observe(target);
    observers.push(io);
  }

  function enable() {
    if (active || !canObserve || prefersReduced()) return;
    active = true;
    root.classList.add('motion-ok');
    watchLoops();
    watchReveals();
    watchCount();
  }

  function disable() {
    observers.forEach(function (io) { io.disconnect(); });
    observers = [];
    active = false;
    root.classList.remove('motion-ok');
    Array.prototype.forEach.call(document.querySelectorAll('[data-reveal]'), function (el) {
      el.classList.remove('is-pending', 'is-revealing');
      el.style.transitionDelay = '';
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-loop]'), function (el) {
      el.classList.remove('is-playing');
    });
    settleCount();
  }

  function onPreferenceChange() {
    if (prefersReduced()) disable();
    else enable();
  }

  if (reduceQuery) {
    if (reduceQuery.addEventListener) reduceQuery.addEventListener('change', onPreferenceChange);
    else if (reduceQuery.addListener) reduceQuery.addListener(onPreferenceChange);
  }

  enable();
})();

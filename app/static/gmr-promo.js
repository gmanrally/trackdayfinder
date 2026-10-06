// Swap the GMR card's still for its turntable.
//
// The animation is ~234KB and the still is a few, so loading it on every page
// view to advertise a part most visitors will not look at is not a trade worth
// making. It is fetched once, on a signal that the viewer might actually care.
//
// What counts as that signal depends on the device. With a mouse it is hover:
// a deliberate act, and cheap to wait for. On a touch screen there is no
// hover, and mouseenter simply never fires — which is why the card sat still
// on every phone. There the signal is the card being on screen, which on a
// phone it now is, because the strip moved above the list.
//
// That makes the fetch near-certain on mobile, so the cheap-data cases are
// checked first and skipped outright: a viewer who has asked for less motion
// or less data gets the still, which is the whole advert anyway — the part,
// lit the same way, just not turning.
(function () {
  var cards = document.querySelectorAll('.gmr-shot[data-anim]');
  if (!cards.length) return;

  function unwanted() {
    try {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return true;
      var c = navigator.connection;
      if (c) {
        if (c.saveData) return true;
        if (/(^|-)2g$/.test(c.effectiveType || '')) return true;
      }
    } catch (e) { /* no matchMedia or no connection info: carry on */ }
    return false;
  }

  // Two turns at six seconds each, then back to the still. A loop that never
  // stops is fine under a cursor that chose it; parked at the top of a phone
  // screen it is just something moving while you are trying to read.
  var REST_AFTER_MS = 12000;

  cards.forEach(function (img) {
    var card = img.closest('.gmr-card') || img;
    var still = img.src;
    var anim = img.dataset.anim;
    var loaded = false, playing = false, restTimer = null;

    function rest() {
      playing = false;
      img.src = still;
    }

    function play() {
      if (playing || unwanted()) return;
      playing = true;
      clearTimeout(restTimer);
      if (loaded) {                       // already fetched: just show it again
        img.src = anim;
        restTimer = setTimeout(rest, REST_AFTER_MS);
        return;
      }
      var pre = new Image();
      pre.onload = function () {
        loaded = true;
        img.src = anim;
        restTimer = setTimeout(rest, REST_AFTER_MS);
      };
      pre.onerror = function () { playing = false; };   // keep the still
      pre.src = anim;
    }

    var hoverable = false;
    try {
      hoverable = window.matchMedia('(hover: hover)').matches;
    } catch (e) { hoverable = true; }     // assume a cursor if we cannot tell

    if (hoverable) {
      card.addEventListener('mouseenter', play);
      card.addEventListener('focus', play, true);
    } else if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) play();
          else { clearTimeout(restTimer); rest(); }   // off screen: stop paying for it
        });
      }, { threshold: 0.5 });
      io.observe(card);
    } else {
      play();                             // old touch browser: just show it
    }
  });
})();

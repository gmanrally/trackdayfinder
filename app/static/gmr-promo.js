// Swap the GMR card's still for its turntable, with nothing asked of the
// viewer.
//
// This started out hover-to-play, to avoid spending ~234KB advertising a part
// most visitors would not look at. Two things settled it the other way. On a
// touch screen there is no hover at all, so mouseenter never fired and the
// card was simply a still image on every phone. And once the strip moved above
// the list on small screens, the card is on the opening screen anyway — so a
// turntable that waits to be asked is a turntable nobody sees.
//
// So it plays on its own, on every device, and keeps turning. The fetch is
// still tied to the card being on screen, which costs nothing where it is
// visible immediately and saves the download on any page where it is not.
//
// Two signals still hold it back, both sent deliberately by the viewer's own
// browser: a reduced-motion preference, and Save-Data or a 2g connection.
// Those get the still, which is the same part under the same lighting — it
// loses the rotation, not the advert.
(function () {
  var shots = document.querySelectorAll('.gmr-shot[data-anim]');
  if (!shots.length) return;

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

  shots.forEach(function (img) {
    var card = img.closest('.gmr-card') || img;
    var still = img.src;
    var anim = img.dataset.anim;
    var started = false;

    function play() {
      if (started || unwanted()) return;
      started = true;
      // Decode first, then swap, so the card never blinks through a
      // half-loaded frame or an empty box on a slow connection.
      var pre = new Image();
      pre.onload = function () { img.src = anim; };
      pre.onerror = function () { started = false; };   // keep the still
      pre.src = anim;
    }

    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (entries) {
        if (!entries.some(function (e) { return e.isIntersecting; })) return;
        play();
        io.disconnect();          // fetched once; it loops on its own from here
      }, { threshold: 0 });
      io.observe(card);
    } else {
      play();
    }
  });
})();

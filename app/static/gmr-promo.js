// Swap the GMR card's still for its turntable on hover.
//
// The animation is ~300KB and the still is a few; loading the animation on
// every page view to advertise a part most visitors will not look at is not a
// trade worth making. Fetched on first hover, then left in place.
(function () {
  document.querySelectorAll('.gmr-shot[data-anim]').forEach(function (img) {
    var card = img.closest('.gmr-card') || img;
    var done = false;
    function play() {
      if (done) return;
      done = true;
      var still = img.src;
      var a = new Image();
      a.onload = function () { img.src = img.dataset.anim; };
      a.onerror = function () { img.src = still; };   // keep the still if it fails
      a.src = img.dataset.anim;
    }
    card.addEventListener('mouseenter', play, {once: true});
    card.addEventListener('focus', play, {once: true});
  });
})();

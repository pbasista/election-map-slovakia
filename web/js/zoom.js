/* Continuous zoom for the wheel, the trackpad, the zoom buttons and
 * double-click.
 *
 * Leaflet zooms the wheel in steps: it gathers wheel events for 40 ms,
 * animates to the next level and redraws every canvas, so a long scroll is a
 * staircase of redraws. Here every input moves a goal zoom instead, and each
 * animation frame takes the view part of the way there, keeping the point
 * under the cursor (or the middle of the map) in place. That is what
 * Leaflet's own pinch zoom does: `_move` fires `zoom`, and the canvases
 * follow by CSS transform. Each input fires `zoomgoal` ({center, zoom}: the
 * view it heads for), so what that view shows can start loading. Once the
 * goal is reached and the input has paused, `_moveEnd` fires `zoomend` and
 * `moveend`.
 *
 * `_move`, `_moveStart`, `_moveEnd`, `_limitCenter`, `_limitZoom`, `_stop`
 * and `_onZoomTransitionEnd` are Leaflet internals (those its TouchZoom
 * handler uses); the vendored Leaflet is pinned at 1.9.4.
 */

const L = globalThis.L;

// Zoom levels per pixel of wheel travel; a mouse wheel notch is about 100 px.
const WHEEL_RATE = 1 / 150;
// A trackpad pinch arrives as ctrl + wheel, in small steps.
const PINCH_RATE = 1 / 50;
// The most one wheel event moves the goal: a page-sized delta is a step,
// not a jump to the zoom limit.
const MAX_STEP = 1;
// Time constant of the approach to the goal, ms: about 0.3 s to arrive.
const EASE = 70;
// How long the input must pause before a reached goal ends the zoom, ms; a
// wheel turned slowly sends a notch about every 100 ms.
const SETTLE = 150;
// How far a pinch's closing "animation" may go, in zoom levels and pixels,
// and still be skipped (dragAfterPinch): about one touchmove's worth.
const NEGLIGIBLE_ZOOM = 0.05;
const NEGLIGIBLE_SHIFT = 4;

/* Takes over wheel and double-click zoom of *map*; `zoomBy(delta, point?)`
 * zooms by *delta* levels around container *point* (default: the middle),
 * `stop()` ends a running zoom where it is, `running()` tells if one is. */
export function smoothZoom(map) {
  const container = map.getContainer();
  let frame = 0;
  let goal = 0;
  let anchorPoint = null;
  let anchorLatLng = null;
  let lastInput = 0;
  let lastFrame = 0;

  function step(now) {
    const zoom = map.getZoom();
    let next = zoom + (goal - zoom) * (1 - Math.exp(-(now - lastFrame) / EASE));
    lastFrame = now;
    if (Math.abs(goal - next) < 0.002) next = goal;
    if (next !== zoom) map._move(centerAt(next), next);
    if (next === goal && now - lastInput >= SETTLE) {
      frame = 0;
      map._moveEnd(true);
    } else {
      frame = requestAnimationFrame(step);
    }
  }

  function zoomBy(delta, point = map.getSize().divideBy(2)) {
    const now = performance.now();
    if (!frame) {
      map._stop();
      goal = map.getZoom();
      lastFrame = now;
      map._moveStart(true, false);
      frame = requestAnimationFrame(step);
    }
    goal = map._limitZoom(goal + delta);
    anchorPoint = point;
    anchorLatLng = map.containerPointToLatLng(point);
    lastInput = now;
    map.fire('zoomgoal', { center: centerAt(goal), zoom: goal });
  }

  // The centre of the view at *zoom* that keeps the anchor in place.
  function centerAt(zoom) {
    const offset = anchorPoint.subtract(map.getSize().divideBy(2));
    const center = map.unproject(map.project(anchorLatLng, zoom).subtract(offset), zoom);
    return map._limitCenter(center, zoom, map.options.maxBounds);
  }

  function stop() {
    if (!frame) return;
    cancelAnimationFrame(frame);
    frame = 0;
    map._moveEnd(true);
  }

  map.scrollWheelZoom.disable();
  map.doubleClickZoom.disable();
  container.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault();
      const rate = e.ctrlKey ? PINCH_RATE : WHEEL_RATE;
      const delta = Math.max(-MAX_STEP, Math.min(MAX_STEP, L.DomEvent.getWheelDelta(e) * rate));
      if (delta) zoomBy(delta, map.mouseEventToContainerPoint(e));
    },
    { passive: false },
  );
  map.on('dblclick', (e) => zoomBy(e.originalEvent.shiftKey ? -1 : 1, e.containerPoint));
  // A drag or a pinch takes the view over from a running zoom.
  map.on('dragstart', stop);
  container.addEventListener('touchstart', stop, { passive: true });

  return { zoomBy, stop, running: () => frame !== 0 };
}

/* Lets a drag start right after a pinch.
 *
 * When a pinch ends, Leaflet's TouchZoom "animates" to where the pinch left
 * the view, marking the map pane `leaflet-zoom-anim`, and its Draggable
 * ignores every touch that starts while the pane has that class. With
 * continuous zoom (zoomSnap 0) the view is already there, or a frame short
 * of it, so the class stays for Leaflet's 250 ms fallback timer or the
 * equally long CSS transition: a pan begun sooner did nothing at all. An
 * animation that goes (almost) nowhere is ended as soon as it starts, at
 * its goal (once `_animateZoom` has returned, hence the microtask); one
 * that does move, back within the zoom limits, runs. */
export function dragAfterPinch(map) {
  map.on('zoomanim', ({ center, zoom }) => {
    const shift = map.project(center, zoom).distanceTo(map.project(map.getCenter(), zoom));
    if (Math.abs(zoom - map.getZoom()) > NEGLIGIBLE_ZOOM || shift > NEGLIGIBLE_SHIFT) return;
    queueMicrotask(() => map._onZoomTransitionEnd());
  });
}

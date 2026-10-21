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
 * `_move`, `_moveStart`, `_moveEnd`, `_limitCenter`, `_limitZoom` and `_stop`
 * are Leaflet internals (those its TouchZoom handler uses); the vendored
 * Leaflet is pinned at 1.9.4.
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

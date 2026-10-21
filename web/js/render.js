/* The worker the map's renderer (draw.js) runs in: what it fetches, decodes
 * and draws keeps the page's main thread free for panning and zooming. It
 * draws on an OffscreenCanvas and posts each drawing as an ImageBitmap,
 * which moves to the page without a copy.
 *
 * Messages from the page (map.js): first {method: 'init', args: [options]}
 * (see `createRenderer`), then {method, args, id?}, a call of the
 * renderer's method; with an id, the result comes back as {id, value} or
 * {id, error}. Drawings go to the page as {frame: bitmap, view, seq}, and
 * {failed: message} if the renderer cannot start.
 */

import { createRenderer } from './draw.js';

let renderer = null;

addEventListener('message', async ({ data: { method, args, id } }) => {
  if (method === 'init') {
    renderer = createRenderer({
      ...args[0],
      surface: (w, h) => new OffscreenCanvas(w, h),
      present(canvas, view, seq) {
        const frame = canvas.transferToImageBitmap();
        postMessage({ frame, view, seq }, [frame]);
      },
    });
    // The page is told when it fails to start: it has no map then.
    renderer.catch((e) => postMessage({ failed: String(e) }));
    return;
  }
  try {
    const value = await (await renderer)[method](...args);
    if (id) postMessage({ id, value });
  } catch (e) {
    if (id) postMessage({ id, error: String(e) });
    else console.error(e);
  }
});

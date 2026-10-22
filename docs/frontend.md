# The frontend

`web/` holds the frontend. `app.css`, `js/` (ES modules, no build step) and
`vendor/` (Leaflet 1.9.4, its `dist/leaflet.js` less the source-map comment
since the map is not shipped; Preact + htm) are copied as is to `/assets/`;
`index.html` (app shell) and `picker.html` (root page) are templates, and
`i18n/<lang>.json` holds the hand-written UI strings, Slovak and English
(the build adds the other languages' and the occupations' translations;
the card and the tooltip of a translated occupation give the Slovak
original; party names stay as the official lists write them).
`app.description` is the search engines' description of a page, and
`app.features`, what the site offers in a paragraph, is on the root page in
each fallback language and in an app shell's `<noscript>`, for search
engines that do not run the page's scripts. The whole page is the map; the site name
with the search, round buttons for language, boundaries, light/dark theme,
zoom and help (the disclaimer, and from there the About dialog) float on
it. Clicking a place or a search result opens a pane with the ballots there
(a bottom sheet on phones); it closes with its button, Esc or, on phones, a
swipe down. A contest's header shows whether it is open: tinted when open;
muted, with a grey bar at its side for the candidates it hides, when closed;
its tooltip says what a press does. On a candidate card each
of the candidate's contests starts closed, showing just the candidate; its
header opens it to the others, whom the filter applies to (never to the
candidate, who stays first), and its pin shows the municipality, city
district, constituency or, in Bratislava and Košice, the city or its
council constituency on the map while the card stays open. The theme follows the device unless chosen in the theme menu
(kept in localStorage); `js/theme.js` applies it before the first paint.
The map uses Leaflet for the view, without any tile layer, and one canvas
of its own, drawn in a worker (`js/render.js` running `js/draw.js`) so that
fetching, decoding and drawing never hold up the page's main thread: it
only moves and scales the canvas with the gesture and swaps in each
finished drawing. The background is our own geometry, loaded per okres and
level of detail as the view changes and kept as typed arrays in a cache
bounded by size (`js/topo.js`), with labels and, from zoom 16, house
numbers, all in the theme's colours. The countries around Slovakia are drawn
below it, duller, with dashed borders and their names where most of each
shows; they cannot be clicked, and the lowest zoom keeps every view within
them. Areas are only filled; every border is
stroked once from the topology, in the style of the highest boundary it is
part of. Zoom is continuous (`js/zoom.js`): wheel, trackpad, pinch, buttons
and double-click scale the canvas every frame. While a pan or zoom goes on,
the view is drawn again at a lower resolution whenever the last drawing no
longer covers it, and sharp once the gesture settles; what has not loaded
yet is added as it comes. The selected place, candidate and the About
dialog are kept in the URL hash, so links can be shared. The About dialog
(`js/about.js`) is a short page with the project's purpose, the source code
and the license, and links to its sections (`#v=about-method`,
`-sources`, `-research`, `-disclaimers`). The site makes no requests to
other servers; `web/_headers` (the base of `dist/_headers`) sets a
Content-Security-Policy that lets the browser enforce this, and short cache
lifetimes with revalidation, since file names carry no content hash.

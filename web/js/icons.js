/* The interface's icons: our own line drawings on a 24 px grid, stroked in
 * the text colour (app.css `.ico`). Always beside a text or an aria-label,
 * so hidden from screen readers. */

import { html } from '../vendor/preact-htm.module.js';

const icon = (shapes) => html`
  <svg class="ico" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${shapes}</svg>
`;

export const Logo = () => html`
  <svg class="logo" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d="M12 2a7.5 7.5 0 0 0-7.5 7.5C4.5 15.4 12 22 12 22s7.5-6.6 7.5-12.5A7.5 7.5 0 0 0 12 2z" />
    <path class="logo-mark" d="m8.8 9.6 2.3 2.3 4.3-4.4" />
  </svg>
`;

export const SearchIcon = () =>
  icon(html`<circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.5 4.5" />`);

/* A place on the map: shows a contest's area there (the candidate card). */
export const MapPinIcon = () =>
  icon(html`<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.3" />`);

export const GlobeIcon = () =>
  icon(html`
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18M12 3c2.4 2.5 3.6 5.5 3.6 9s-1.2 6.5-3.6 9M12 3C9.6 5.5 8.4 8.5 8.4 12s1.2 6.5 3.6 9" />
  `);

export const LayersIcon = () =>
  icon(html`
    <path d="M12 3 3 7.8l9 4.8 9-4.8z" />
    <path d="m3 12 9 4.8 9-4.8M3 16.2 12 21l9-4.8" />
  `);

/* The map's layers, for their menus, in shapes rather than
 * words so that they read in every language: a municipality cut into its
 * council constituencies, a larger region around municipalities (a regional
 * constituency), a city; the polling districts, a municipality's outline
 * cut by thin lines into many small parts; and the base map's layers, a
 * river and a road that crosses it, and buildings as a map draws them, in
 * plan. */
export const LAYER_ICON = {
  oz: () =>
    icon(html`
      <path
        class="fill"
        d="M4 8.5 4.3 11.7 10.9 11 10.5 3.8zM19.5 6 12.7 4 13 10.7 19.7 9.3zM20 15.5 19.8 11.6 13.1 12.9 13.5 20.2zM5 18 11.3 20 11 13.2 4.6 13.8z"
      />
    `),
  zsk: () =>
    icon(html`
      <path d="M3 8.1 10.9 2.5 20.4 5.3 21 15.9 13.1 21.5 4.2 18.7z" />
      <path class="fill" d="M8 10.3 8.5 15.1 11.3 16 10.9 8.3zM16 13.8 15.8 9.1 12.7 8.2 13.1 15.9z" />
    `),
  city: () =>
    icon(html`
      <path class="fill" d="M2 21v-8.5L7.5 7l5.5 5.5V21H8.75v-4.5h-2.5V21zM14.5 21V10l3.25-7.5L21 10v11z" />
    `),
  okrsky: () =>
    icon(html`
      <path d="M3.5 6.5 11 3l9.5 3.5v11L13 21l-9.5-3.5z" />
      <path class="thin" d="M11 3v8.5M3.5 12 11 11.5l9.5.5M13 21l-2-9.5M7.5 4.8l.4 6.9M16 4.7l-.4 7.2" />
    `),
  base: () =>
    icon(html`
      <path d="M3 16c3-3 6 2 9-1s6-6 9-3" />
      <path class="thin" d="M8 3.5 16 20.5" />
    `),
  buildings: () =>
    icon(html`
      <path d="M3.5 6.5 9 4.5l2 5.5-5.5 2zM12.5 12.5l6.5-2.3 2.4 6.8-6.5 2.3zM4 15.5l4-1.4 1.4 4-4 1.4zM14 3.5l4-1.2 1.2 3.8-4 1.2z" />
    `),
};

/* The base map's button: its river and road with a building beside them. */
export const BaseMapIcon = () =>
  icon(html`
    <path d="M3 17c3-3 6 2 9-1s6-6 9-3" />
    <path class="thin" d="M8 3.5 16 20.5" />
    <path d="M14.5 4.5h5v5h-5z" />
  `);

/* A ballot going into the box: the turnout on the map. */
export const TurnoutIcon = () =>
  icon(html`
    <path d="M3 12.5h18M4.5 12.5V20h15v-7.5M8 12.5V4h8v8.5" />
    <path class="thin" d="m10 8.3 1.5 1.5 2.6-3" />
  `);

export const SunIcon = () =>
  icon(html`
    <circle cx="12" cy="12" r="4" />
    <path
      d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"
    />
  `);

export const MoonIcon = () => icon(html`<path d="M20 14.6A8.2 8.2 0 1 1 9.4 4 6.6 6.6 0 0 0 20 14.6z" />`);

/* The device's theme: a disc half light, half dark. */
export const SystemIcon = () =>
  icon(html`
    <circle cx="12" cy="12" r="8.5" />
    <path class="fill" d="M12 3.5a8.5 8.5 0 0 1 0 17z" />
  `);

export const PlusIcon = () => icon(html`<path d="M12 5v14M5 12h14" />`);

export const MinusIcon = () => icon(html`<path d="M5 12h14" />`);

export const HelpIcon = () =>
  icon(html`
    <path d="M8.8 9a3.3 3.3 0 1 1 4.9 2.9c-1 .6-1.7 1.3-1.7 2.6v.5" />
    <circle class="fill" cx="12" cy="18.6" r="1.1" />
  `);

export const CloseIcon = () => icon(html`<path d="m6 6 12 12M18 6 6 18" />`);

export const BackIcon = () => icon(html`<path d="m14.5 18-6-6 6-6" />`);

export const ArrowIcon = () => icon(html`<path d="M5 12h14m-5.5-5.5L19 12l-5.5 5.5" />`);

export const CheckIcon = () => icon(html`<path d="m5 12.5 4.5 4.5L19 7.5" />`);

/* Points down: what it opens unfolds below (app.css turns it up when
 * open). */
export const ExpandIcon = () => icon(html`<path d="m6 9.5 6 6 6-6" />`);

/* The buttons put away on a phone with the sheet open (app.js). */
export const MoreIcon = () =>
  icon(html`
    <circle class="fill" cx="12" cy="5.5" r="1.4" />
    <circle class="fill" cx="12" cy="12" r="1.4" />
    <circle class="fill" cx="12" cy="18.5" r="1.4" />
  `);

/* The map's credits, folded on a phone (map.js). */
export const InfoIcon = () =>
  icon(html`
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5.5" />
    <circle class="fill" cx="12" cy="7.6" r="1.1" />
  `);

/* A heart: Favourites, the candidates circled. Not a star, which browsers
 * use for bookmarking the page, nor a circled number, which reads as a
 * number or a step. */
export const HeartIcon = () =>
  icon(html`<path d="M12 19.5s-7.5-4.6-7.5-10.1A4.1 4.1 0 0 1 12 7a4.1 4.1 0 0 1 7.5 2.4c0 5.5-7.5 10.1-7.5 10.1z" />`);

/* The loop a voter's pen draws around a candidate's number on the ballot:
 * stretched over the number whatever its width (app.css `.ink`), its end
 * running past its start as a hand-drawn one does. */
export const InkCircle = () => html`
  <svg class="ink" viewBox="0 0 40 28" preserveAspectRatio="none" aria-hidden="true" focusable="false">
    <path d="M27 3.6C19.5 1.6 7.8 2.9 4.2 9.6 1 15.6 6.4 24.6 18.6 25 30.4 25.4 38 19.6 37.2 12 36.5 5.6 28.6 2.6 20.4 3.4" />
  </svg>
`;

/* The cross a pen draws over a candidate's number: crossed out by the
 * visitor, stretched over the number like InkCircle. */
export const InkCross = () => html`
  <svg class="ink-cross" viewBox="0 0 40 28" preserveAspectRatio="none" aria-hidden="true" focusable="false">
    <path d="M7 4.5C15 9.5 24 16.5 33.5 24.5M32 3.5C23.5 9 14.5 16.5 6.5 24.6" />
  </svg>
`;

/* A hand-drawn cross, unlike the straight one that closes or removes: the
 * candidates crossed out, in the filter. */
export const CrossOutIcon = () => icon(html`<path d="M5 6c4.5 3.6 9 7.6 14 12.5M18.5 5.5c-4.4 3.9-8.7 8-13 13" />`);

/* Two chain links: copies a link. */
export const LinkIcon = () =>
  icon(html`
    <path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1.2 1.2" />
    <path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1.2-1.2" />
  `);

/* A QR code in outline: its three corner squares and a few modules. */
export const QrIcon = () =>
  icon(html`
    <rect x="3.5" y="3.5" width="7" height="7" rx="1" />
    <rect x="13.5" y="3.5" width="7" height="7" rx="1" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="1" />
    <path d="M14 14h2.5v2.5M20.5 14v.01M14 20.5h.01M17.5 20.5h3v-3" />
  `);

/* A chair seen from the side: the candidate holds the office now. */
export const ChairIcon = () => icon(html`<path d="M7 3v18M7 12.5h11V21M7 16.5h11" />`);

/* A door with an arrow out of it: the candidate withdrew from the election
 * (yet stayed on the ballot). */
export const WithdrawnIcon = () =>
  icon(html`<path d="M10.5 4H5.5v16h5" /><path d="M10 12h10m-3.5-3.5L20 12l-3.5 3.5" />`);

/* The winner map: a folded map whose panels are in colours of their own,
 * each area by who leads there. */
export const WinnerMapIcon = () =>
  icon(html`
    <path d="M3 6.5 9 4l6 2.5L21 4v13.5L15 20l-6-2.5L3 20z" />
    <path class="fill" d="M9 4v13.5L3 20V6.5z" />
    <path class="fill faint" d="M21 4v13.5L15 20V6.5z" />
  `);

/* Elected: a decoration, an eight-pointed star hanging from a ribbon's two
 * straps; a star, not a sports medal's disc, with deep points that still
 * read at the badge's size (more points blur into a disc there), and solid,
 * a hole in it reading as an eye. Not a five-pointed star, which reads as
 * a favourite, nor a check mark, which reads as done. */
export const MedalIcon = () =>
  icon(html`
    <path class="fill" d="M5 1.2h4.6l3 6.8H8.2zM19 1.2h-4.6l-3 6.8h4.4z" />
    <path
      class="fill"
      d="M12 8.6 13.5 12.3 17.2 10.7 15.6 14.4 19.3 15.9 15.6 17.4 17.2 21.1 13.5 19.5 12 23.2 10.5 19.5 6.8 21.1 8.4 17.4 4.7 15.9 8.4 14.4 6.8 10.7 10.5 12.3z"
    />
  `);

/* The decoration in outline, not won yet: a winner this site calls before
 * it is official. */
export const MedalOutlineIcon = () =>
  icon(html`
    <path d="M5.8 2h3.2l2.6 5.8H8.4zM18.2 2H15l-2.6 5.8h3.2z" />
    <path d="M12 9.4 13.4 12.6 16.6 11.3 15.3 14.5 18.5 15.9 15.3 17.3 16.6 20.5 13.4 19.2 12 22.4 10.6 19.2 7.4 20.5 8.7 17.3 5.5 15.9 8.7 14.5 7.4 11.3 10.6 12.6z" />
  `);

/* The filter's two modes: an open eye, only these are shown; struck
 * through, these are hidden. */
export const EyeIcon = () =>
  icon(html`<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="3" />`);

export const EyeOffIcon = () =>
  icon(html`
    <path d="M9.9 5.8A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.6 3.4M14.1 14.2A3 3 0 0 1 9.8 9.9" />
    <path d="M6.6 7.1C3.9 8.9 2.5 12 2.5 12S6 18.5 12 18.5c1.8 0 3.3-.5 4.6-1.2M3 3l18 18" />
  `);

/* A funnel struck through: the filter is cleared. Not a cross, which
 * closes the pane. */
export const FilterOffIcon = () => icon(html`<path d="M4 5h16l-6 7.2V18l-4 2v-7.8z" /><path d="m3 3 18 18" />`);

export const WarningIcon = () =>
  icon(html`
    <path d="M10.3 4.1 2.6 17.6A2 2 0 0 0 4.3 20.6h15.4a2 2 0 0 0 1.7-3L13.7 4.1a2 2 0 0 0-3.4 0z" />
    <path d="M12 9.5v4.5" />
    <circle class="fill" cx="12" cy="17.1" r="1.1" />
  `);

/* A question mark in a circle: what is claimed, not established (allegations
 * and disputes), beside the warning sign of serious controversies. Large and
 * plain, as it is drawn at 12 px in a mark. */
export const DisputeIcon = () =>
  icon(html`
    <circle cx="12" cy="12" r="9.2" />
    <path d="M9.6 9.6a2.5 2.5 0 1 1 3.6 2.2c-.7.4-1.2.9-1.2 1.8" />
    <circle class="fill" cx="12" cy="16.8" r="1.2" />
  `);

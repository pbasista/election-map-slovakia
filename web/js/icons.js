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

/* The constituency overlays, for the boundaries menu, in shapes rather than
 * words so that they read in every language: a municipality cut into its
 * council constituencies, a larger region around municipalities (a regional
 * constituency), a city. */
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
};

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

/* A chair seen from the side: the candidate holds the office now. */
export const ChairIcon = () => icon(html`<path d="M7 3v18M7 12.5h11V21M7 16.5h11" />`);

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

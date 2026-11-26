/**
 * Icons from the one sprite beside this file.
 */

// Beside this file, unless the page names its address: an app that caches these files
// under hashed URLs puts the sprite's in <meta name="chat-ui-icons">, since a module
// cannot work out a hash.
const SPRITE = document.querySelector('meta[name="chat-ui-icons"]')?.content
  || new URL('icons.svg', import.meta.url).href;
const SVG = 'http://www.w3.org/2000/svg';

/** An icon by its name in the sprite, decorative: whatever holds it carries the label. */
export function icon(name) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  const use = document.createElementNS(SVG, 'use');
  use.setAttribute('href', `${SPRITE}#${name}`);
  svg.append(use);
  return svg;
}

/** A button that is only an icon, with the words it stands for as its name and tooltip. */
export function iconButton(name, label, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'icon-button';
  button.title = label;
  button.setAttribute('aria-label', label);
  button.append(icon(name));
  button.addEventListener('click', onClick);
  return button;
}

/** A button that copies `text()`, and says for a moment that it has. */
export function copyButton(label, text) {
  const button = iconButton('copy', label, async () => {
    await navigator.clipboard.writeText(text());
    button.replaceChildren(icon('check'));
    setTimeout(() => button.replaceChildren(icon('copy')), 1500);
  });
  return button;
}

'use strict';

/*
 * Pictures of devices: character grids from sprites.json drawn as rectangles.
 *
 * A grid is the one place a picture is described — the page never hand-draws a device.
 */

class Pixels {
  /** Rectangles of one grid: neighbours of one colour in a row merge into a single strip. */
  static rects(rows, colourOf) {
    const found = [];
    rows.forEach((row, y) => {
      let mark = null;
      let start = 0;
      const line = `${row}.`;
      for (let x = 0; x < line.length; x += 1) {
        if (line[x] === mark) continue;
        if (mark !== null && mark !== '.') {
          found.push({ x: start, y, width: x - start, height: 1, fill: colourOf(mark) });
        }
        mark = line[x];
        start = x;
      }
    });
    return found;
  }

  static size(rows) {
    return { width: Math.max(...rows.map((row) => row.length)), height: rows.length };
  }
}

class Sprites {
  constructor(data) {
    this.palette = data.palette;
    this.icons = data.icons;
    this.fallback = data.default;
  }

  static async load(url = 'sprites.json') {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(say('sprites.unreadable', { status: response.status }));
    return new Sprites(await response.json());
  }

  get kinds() {
    return Object.keys(this.icons);
  }

  has(kind) {
    return Object.prototype.hasOwnProperty.call(this.icons, kind);
  }

  /** The grid of a kind. An unknown kind draws the default house: a device is never left unseen. */
  rows(kind) {
    return this.icons[this.has(kind) ? kind : this.fallback];
  }

  size(kind) {
    return Pixels.size(this.rows(kind));
  }

  icon(kind) {
    return Pixels.rects(this.rows(kind), (mark) => this.colour(mark));
  }

  colour(mark) {
    const colour = this.palette[mark];
    if (!colour) throw new Error(say('sprites.no-colour', { mark }));
    return colour;
  }
}

class Sprite {
  static NS = 'http://www.w3.org/2000/svg';

  /** A group of rectangles: one grid pixel becomes `scale` screen pixels. */
  static node(rects, { x = 0, y = 0, scale = 1 } = {}) {
    const group = document.createElementNS(Sprite.NS, 'g');
    group.setAttribute('shape-rendering', 'crispEdges');
    for (const rect of rects) {
      const node = document.createElementNS(Sprite.NS, 'rect');
      node.setAttribute('x', x + rect.x * scale);
      node.setAttribute('y', y + rect.y * scale);
      node.setAttribute('width', rect.width * scale);
      node.setAttribute('height', rect.height * scale);
      node.setAttribute('fill', rect.fill);
      group.append(node);
    }
    return group;
  }
}

if (typeof module === 'object' && module.exports) module.exports = { Pixels, Sprites, Sprite };

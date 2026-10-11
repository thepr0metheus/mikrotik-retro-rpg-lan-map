'use strict';

/*
 * The map page: castles, one road each, and the houses that are home right now.
 *
 * The page draws and decides nothing. Widths, ports and findings come from /api/map; the only
 * thing it ever sends back is where a thing was dragged (one fact, one place).
 *
 * Nor does it hold any words of its own: every line a reader sees comes from the dictionary
 * in lang.js, by key. What arrives from the server is already said in the chosen language,
 * bar a handful of codes the page has to draw differently — a road's width, a finding's kind,
 * a device's kind. Those it says out of the same dictionary.
 */

const NS = 'http://www.w3.org/2000/svg';

class Svg {
  static el(tag, attrs, ...children) {
    const node = document.createElementNS(NS, tag);
    for (const [name, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      node.setAttribute(name, value === true ? '' : String(value));
    }
    node.append(...children.filter((child) => child !== null && child !== undefined));
    return node;
  }

  static words(x, y, text, attrs) {
    const node = Svg.el('text', {
      x, y, 'text-anchor': 'middle', 'dominant-baseline': 'central',
      'font-family': 'ui-monospace, monospace', ...attrs,
    });
    node.textContent = text;
    return node;
  }

  /** Where a pointer event landed, in the coordinates the map is drawn in. */
  static point(svg, event) {
    const box = svg.getBoundingClientRect();
    const view = svg.viewBox.baseVal;
    const width = view.width || Look.FIELD.width;
    const height = view.height || Look.FIELD.height;
    return {
      x: view.x + (event.clientX - box.left) * (width / box.width),
      y: view.y + (event.clientY - box.top) * (height / box.height),
    };
  }
}

class Look {
  //: The island's size. It can be dragged by the edge, so it changes — but it lives in one place.
  static FIELD = { width: 1200, height: 860 };
  static ISLAND = { least: { width: 700, height: 500 }, most: { width: 3600, height: 2600 } };
  static TOWN = { width: 150, height: 120 };
  static SHORE = 24;
  //: The fence around a subnet: the width of the band it stands on, the thickness of the rail,
  //: how wide a post is and how far apart the posts stand.
  static FENCE = 14;
  static RAIL = 4;
  static POST_WIDE = 8;
  static POST = 26;
  //: A house is a row: picture on the left, caption on the right. Many houses, several columns.
  static ROW = { width: 186, height: 32 };
  static COLUMN_ROWS = 8;
  static HOUSE = 2;
  static SEA = '#2f6fbf';
  static SAND = '#e3cf8f';
  static GRASS = '#5fae45';
  static YARD = '#cdbb8b';
  static STONE = '#8b9099';
  static DARK = '#3b2a1a';
  static ROAD = '#c0a875';
  static ROAD_EDGE = '#8a7248';
  static MOSS = '#4c9434';
  static FOG = '#9aa0a6';
  static GOLD = '#ffd34d';
  static INK = '#3b2a14';
  static BOARD = '#f3e6bf';
  static WOOD = '#9a6a3a';
  static PIN = '#b5443a';
  //: From the widest road to the narrowest. A castle takes the width of its best road.
  static RANK = ['all', 'most', 'ports', 'puzzle'];

  //: How access is shown: by the width of the road, by a barrier at the gate, or by a flag.
  static SHOWS = ['width', 'barriers', 'flags'];
  //: Castle colours: the same ones the server offers, so the choice comes from one set.
  static PALETTE = ['#1d9e75', '#7f77dd', '#f0a020', '#3f6fb5', '#d4537e', '#639922'];
  static PLAIN = 16;

  static lane(width, show) {
    const style = Look.plain(width);
    if (!style || show === 'width') return style;
    return { ...style, size: Look.PLAIN, dash: width === 'puzzle' ? '5 6' : '' };
  }

  static plain(width) {
    if (width === 'all' || width === 'most') return { size: 22, dash: '', colour: Look.ROAD };
    if (width === 'ports') return { size: 11, dash: '', colour: Look.ROAD };
    if (width === 'puzzle') return { size: 11, dash: '5 6', colour: Look.FOG };
    return null;
  }

  /** The colour of an access sign: open, ports only, could not be read. */
  static tone(width) {
    if (width === 'all' || width === 'most') return '#43a047';
    if (width === 'ports') return '#f0a020';
    return Look.FOG;
  }

  static widest(ways) {
    let best = null;
    for (const way of ways) {
      const rank = Look.RANK.indexOf(way.road.width);
      if (rank >= 0 && (best === null || rank < best)) best = rank;
    }
    return best === null ? null : Look.RANK[best];
  }
}

class Places {
  /** Where things stand. What nobody moved is laid out to plan: castles in the corners. */
  constructor(saved, keys) {
    this.places = { ...saved };
    this.keys = keys;
    //: The points that things standing beside something are kept by: see beside().
    this.anchors = {};
  }

  static SPOTS = [[-1, -1], [1, -1], [-1, 1], [1, 1], [-1, 0], [1, 0]];
  static STEP = { x: 330, y: 240 };
  //: Where a thing that stands beside something goes while nobody has moved it: its offset
  //: from that point. The notice board stands just off the router square's lower right corner;
  //: the signpost on the beach left of the pier, clear of the road that comes down to it, and
  //: the book and the robot right of that road, their feet in line with the signpost's. The
  //: guardhouse's point is already the spot it stands on: see gateCorner().
  static BESIDE = { notices: { x: 6, y: 6 }, signpost: { x: -112, y: -120 }, docker: { x: -86, y: 6 },
                    story: { x: 36, y: -106 }, guide: { x: 108, y: -128 }, gate: { x: 0, y: 0 } };

  /**
   * Keeps a thing beside a point that moves: its place is saved as an offset from the point,
   * so it goes wherever the point goes. The notice board stands by the corner of the router's
   * square, which moves with the router and grows with his gates.
   */
  beside(name, point) {
    this.anchors[name] = point;
  }

  of(name) {
    const saved = this.places[name];
    const point = this.anchors[name];
    if (point) {
      const offset = saved ? { x: saved[0], y: saved[1] } : Places.BESIDE[name];
      return { x: point.x + offset.x, y: point.y + offset.y };
    }
    return saved ? { x: saved[0], y: saved[1] } : this.byDefault(name);
  }

  byDefault(name) {
    const middle = { x: Look.FIELD.width / 2, y: Look.FIELD.height / 2 - 60 };
    if (name === 'router') return middle;
    if (name === 'internet') return { x: middle.x, y: Look.FIELD.height - 46 };
    const order = this.keys.indexOf(name);
    if (order < 0) return middle;
    const spot = Places.SPOTS[order % Places.SPOTS.length];
    return { x: middle.x + spot[0] * Places.STEP.x, y: middle.y + spot[1] * Places.STEP.y };
  }

  put(name, x, y) {
    const point = this.anchors[name] || { x: 0, y: 0 };
    this.places[name] = [Math.round((x - point.x) * 10) / 10, Math.round((y - point.y) * 10) / 10];
  }

  payload() {
    return { places: this.places, looks: this.looks || {},
             field: [Look.FIELD.width, Look.FIELD.height] };
  }
}

class Castle {
  /** A castle: in the yard stand those online now. The rest are counted on the sign. */
  constructor(segment, devices, place, look) {
    this.segment = segment;
    this.known = devices.length;
    //: Every dweller, the dark ones too: not in the yard, but the scroll needs them.
    this.all = devices;
    this.look = look || {};
    this.devices = Castle.sorted(devices.filter((device) => device.online && !device.hidden),
                                 this.look.sort);
    this.place = place;
    const count = Math.max(this.devices.length, 1);
    this.columns = this.look.columns || Math.max(1, Math.ceil(count / Look.COLUMN_ROWS));
    this.rows = Math.max(1, Math.ceil(count / this.columns));
  }

  /** The order of houses in a yard: as they came, by name, by address or by kind. */
  static sorted(devices, sort) {
    const seat = (device) => (device.seats.find((one) => one.online) || device.seats[0] || {}).ip || '';
    const number = (ip) => ip.split('.').reduce((sum, part) => sum * 256 + Number(part), 0);
    const copy = [...devices];
    if (sort === 'name') return copy.sort((one, other) => Castle.label(one).localeCompare(Castle.label(other)));
    if (sort === 'address') return copy.sort((one, other) => number(seat(one)) - number(seat(other)));
    if (sort === 'kind') {
      const kind = (device) => say(`kind.${device.kind || 'house'}`);
      return copy.sort((one, other) => kind(one).localeCompare(kind(other)));
    }
    return copy;
  }

  get size() {
    if (this.look.folded) return { width: 210, height: 64 };
    return {
      width: this.columns * Look.ROW.width + Look.FENCE * 2 + 16,
      height: this.rows * Look.ROW.height + Look.FENCE * 2 + 16,
    };
  }

  get box() {
    const size = this.size;
    return { x: this.place.x - size.width / 2, y: this.place.y - size.height / 2, ...size };
  }

  draw(page) {
    const box = this.box;
    // A castle's wall is its colour: castles stay apart even when the sign cannot be read.
    const wall = Castle.shade(this.segment.colour, 0.72);
    const group = Svg.el('g', { class: 'castle' });
    group.append(
      Svg.el('rect', { x: box.x, y: box.y, width: box.width, height: box.height, fill: wall }),
      Svg.el('rect', {
        x: box.x + Look.FENCE, y: box.y + Look.FENCE,
        width: box.width - Look.FENCE * 2, height: box.height - Look.FENCE * 2, fill: Look.YARD,
      }),
      this.fence(box),
    );
    if (this.segment.temporary) {
      group.append(Svg.el('rect', {
        x: box.x, y: box.y, width: box.width, height: box.height, fill: 'none',
        stroke: Look.BOARD, 'stroke-width': 3, 'stroke-dasharray': '8 6',
      }));
    }
    // The yard beyond the gate: a fence of loose stones, since it is not ours.
    if (this.segment.outside) {
      group.append(Svg.el('rect', {
        x: box.x, y: box.y, width: box.width, height: box.height, fill: 'none',
        stroke: Look.STONE, 'stroke-width': 4, 'stroke-dasharray': '3 6',
      }));
    }
    // A castle is moved by its name alone: the yard itself is clicked, and a click inside it
    // must not turn into a move.
    const name = page.board(this.place.x, box.y - 34, this.heading(), this.segment.colour);
    name.setAttribute('data-move', this.segment.key);
    name.classList.add('held');
    group.append(name);
    group.addEventListener('pointerenter', () => page.hint.show(this.tell()));
    group.addEventListener('pointerleave', () => page.hint.hide());
    group.addEventListener('click', () => page.showSegment(this.segment.key));
    group.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      event.stopPropagation();
      page.menu.show(page.spot(event), this.segment.title, page.castleMenu(this));
    });
    return group;
  }

  /** The words on the castle's board: its name, its network, who is home. */
  heading() {
    return `${this.segment.title} · ${Castle.shortNet(this.segment.network)}`
      + ` · ${say('castle.count', { here: this.devices.length, all: this.known })}`;
  }

  /** The yard and its fence: what the fog covers. The board with the name stays above the fog. */
  area() {
    const box = this.box;
    return { x: box.x - 6, y: box.y - 6, width: box.width + 12, height: box.height + 12 };
  }

  /** Where the house of the n-th device stands in the yard: houses and the fog's windows share it. */
  spot(order) {
    const column = Math.floor(order / this.rows);
    const row = order % this.rows;
    return { x: this.box.x + Look.FENCE + 8 + column * Look.ROW.width,
             y: this.box.y + Look.FENCE + 8 + row * Look.ROW.height };
  }

  /** A device's row in the yard, for a window in the fog; null when the yard shows no houses. */
  rowOf(key) {
    const order = this.look.folded ? -1 : this.devices.findIndex((device) => device.key === key);
    if (order < 0) return null;
    const at = this.spot(order);
    return { x: at.x - 5, y: at.y - 4, width: Look.ROW.width - 6, height: Look.ROW.height };
  }

  /** Battlements along the top wall: a castle should look like a castle. */
  /**
   * A fence around the yard: a rail all the way round, and posts standing on it.
   *
   * The band underneath keeps the subnet's colour, because that is what tells one subnet from
   * another across the whole map when no caption can be read. The rail and the posts are what
   * make it a fence — the band used to wear merlons along its top, which said "castle" and
   * nothing else. Posts are wider than the rail and darker than both: at the size a whole map
   * is looked at, a fence is only a fence if its posts can be counted.
   */
  fence(box) {
    const group = Svg.el('g');
    const left = box.x + Look.FENCE / 2;
    const right = box.x + box.width - Look.FENCE / 2;
    const top = box.y + Look.FENCE / 2;
    const foot = box.y + box.height - Look.FENCE / 2;
    group.append(Svg.el('rect', {
      x: left, y: top, width: right - left, height: foot - top, fill: 'none',
      stroke: Castle.darker(this.segment.colour, 0.55), 'stroke-width': Look.RAIL,
    }));
    const dark = Castle.darker(this.segment.colour, 0.3);
    const put = (x, y) => group.append(Svg.el('rect', {
      x: x - Look.POST_WIDE / 2, y: y - Look.POST_WIDE / 2,
      width: Look.POST_WIDE, height: Look.POST_WIDE, fill: dark }));
    // The corners stand on both runs and are put down once, by the one that goes across.
    for (const x of Castle.evenly(left, right)) {
      put(x, top);
      put(x, foot);
    }
    for (const y of Castle.evenly(top, foot).slice(1, -1)) {
      put(left, y);
      put(right, y);
    }
    return group;
  }

  /** Points from one end to the other at even steps, both ends among them. */
  static evenly(from, to) {
    const many = Math.max(1, Math.round((to - from) / Look.POST));
    return Array.from({ length: many + 1 }, (_, step) => from + ((to - from) * step) / many);
  }

  /**
   * The colour taken down towards the dark. Not the same as taking it towards stone: stone
   * lightens a dark colour, and a fence has to be seen against the band it stands on.
   */
  static darker(colour, part) {
    const number = parseInt(String(colour).replace('#', ''), 16);
    if (Number.isNaN(number)) return Look.DARK;
    const down = (shift) => Math.round(((number >> shift) & 255) * part);
    return `rgb(${down(16)}, ${down(8)}, ${down(0)})`;
  }

  /** The subnet's colour taken towards stone: a band must not shout louder than the devices. */
  static shade(colour, part) {
    const number = parseInt(String(colour).replace('#', ''), 16);
    if (Number.isNaN(number)) return Look.STONE;
    const mix = (shift, stone) => Math.round((((number >> shift) & 255) * part) + stone * (1 - part));
    return `rgb(${mix(16, 139)}, ${mix(8, 144)}, ${mix(0, 153)})`;
  }

  /** The network in a heading: a /24 reads as "192.168.20.x", the rest stands as it is. */
  static shortNet(network) {
    const [base, bits] = String(network).split('/');
    return bits === '24' ? base.replace(/\.\d+$/, '.x') : network;
  }

  houses(page) {
    const box = this.box;
    const group = Svg.el('g');
    if (this.look.folded) return group;
    this.devices.forEach((device, order) => {
      const { x, y } = this.spot(order);
      const house = Svg.el('g', { class: 'house', 'data-device': device.key });
      // A device that also stands in another subnet has the shadow of the same house behind
      // it, in that subnet's colour. It is not in two places by halves: it is wholly in both,
      // and one of the two is where its owner will go looking for it.
      for (const [step, key] of device.homes.filter((one) => one !== this.segment.key)
        .slice(0, 2).entries()) {
        const shift = (step + 1) * 5;
        house.append(Svg.el('rect', {
          x: x - 2 + shift, y: y - 2 - shift, width: 28, height: 28, rx: 3, fill: Look.YARD,
          stroke: page.colourOf(key), 'stroke-width': 2,
        }));
      }
      house.append(
        page.sprites.node(device.kind, x, y, Look.HOUSE),
        Svg.el('text', {
          x: x + 30, y: y + 14, 'text-anchor': 'start', 'dominant-baseline': 'central',
          'font-family': 'ui-monospace, monospace', 'font-size': 13, fill: Look.INK,
        }),
      );
      house.lastChild.textContent = Castle.label(device);
      // Only those online stand in a yard, so there is nothing to mark and no need. A pinned
      // house, though, stays on the map when dark: it alone asks for a frame.
      if (!device.online) {
        house.append(Svg.el('rect', {
          x: x - 2, y: y - 2, width: 28, height: 28, fill: 'none', rx: 3,
          stroke: Look.FOG, 'stroke-width': 2, 'stroke-dasharray': '3 3',
        }));
      }
      house.addEventListener('pointerenter', () => {
        page.hint.show(page.aboutDevice(device));
        page.together(device.key, true);
      });
      house.addEventListener('pointerleave', () => {
        page.hint.hide();
        page.together(device.key, false);
      });
      house.addEventListener('click', (event) => {
        event.stopPropagation();
        page.showDevice(device);
      });
      if (page.found.has(device.key)) {
        house.append(Svg.el('rect', {
          x: x - 3, y: y - 3, width: 30, height: 30, fill: 'none',
          stroke: Look.GOLD, 'stroke-width': 3, rx: 4,
        }));
      }
      group.append(house);
    });
    return group;
  }

  /** A house's caption: its name, or failing that its number inside its own network. */
  static label(device) {
    if (device.name) return device.name.length > 17 ? `${device.name.slice(0, 16)}…` : device.name;
    const seat = device.seats.find((one) => one.online) || device.seats[0];
    return seat ? `·${seat.ip.split('.').pop()}` : say('device.nameless');
  }

  tell() {
    const vlan = this.segment.vlan ? `VLAN ${this.segment.vlan}, ` : '';
    return `${this.segment.title}: ${vlan}${this.segment.network}. `
      + say('castle.online', { here: this.devices.length, all: this.known });
  }
}

class Roadwork {
  /** One road from a castle to the customs house. What it lets through is on the sign. */
  static draw(corridor, page) {
    const width = Look.widest(corridor.ways);
    const style = Look.lane(width, page.access);
    if (!style) return null;
    const tight = Look.RANK[Math.max(...corridor.ways
      .map((way) => Look.RANK.indexOf(way.road.width)).filter((rank) => rank >= 0))];
    const points = corridor.spine;
    const group = Svg.el('g', { class: 'lane', 'data-road': corridor.key });
    group.append(
      Svg.el('path', {
        d: Roadwork.line(points), fill: 'none', stroke: Look.ROAD_EDGE,
        'stroke-width': style.size + 5, 'stroke-linejoin': 'round',
      }),
      Svg.el('path', {
        d: Roadwork.line(points), fill: 'none', stroke: style.colour,
        'stroke-width': style.size, 'stroke-dasharray': style.dash, 'stroke-linejoin': 'round',
      }),
      Roadwork.gate(points[0], points[1], style.size),
    );
    if (page.access === 'barriers') group.append(Roadwork.barrier(points, style.size, tight));
    if (page.access === 'flags') group.append(Roadwork.mark(points[1], Look.tone(tight)));
    if (corridor.ways.every((way) => way.road.dead)) {
      page.groups.notes.append(Svg.el('path', {
        d: Roadwork.line(points), fill: 'none', stroke: Look.MOSS, 'stroke-width': style.size,
        'stroke-dasharray': '3 12', 'stroke-linejoin': 'round',
      }));
    }
    const plain = corridor.ways.find((way) => way.road.byDefault);
    if (plain) page.groups.notes.append(Roadwork.flag(points[1]));
    // A sign of a narrow road is the subnet's own business: it shows when the subnet is clicked.
    const sign = page.watching === corridor.key ? Roadwork.sign(corridor, page) : '';
    if (sign) {
      const spot = Roadwork.signSpot(points);
      // A sign of several lines grows downwards, so it is lifted by the extra lines.
      spot[1] -= (MapPage.wrap(sign).length - 1) * MapPage.LINE;
      page.groups.notes.append(page.board(spot[0], spot[1], sign, Look.ROAD_EDGE));
    }
    group.addEventListener('pointerenter', () => page.hint.show(page.aboutCastleRoads(corridor)));
    group.addEventListener('pointerleave', () => page.hint.hide());
    group.addEventListener('click', () => page.scroll.roads(corridor, (key) => page.titleOf(key),
                                                            page.gateNotes(corridor.key)));
    group.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      event.stopPropagation();
      page.menu.show(page.spot(event), say('road.of', { title: corridor.title }),
                     page.roadMenu(corridor));
    });
    return group;
  }

  /** The sign by a road: its narrowest point, when that point is one nameable house. */
  static sign(corridor, page) {
    const narrow = corridor.ways.find((way) => way.road.width === 'ports' && way.road.only);
    if (!narrow) return '';
    const other = narrow.way === 'out' ? narrow.road.target : narrow.road.source;
    const ports = Roadwork.ports(narrow.road);
    const where = say(narrow.way === 'out' ? 'road.to' : 'road.from',
                      { title: page.titleOf(other) });
    return `${where}: ${narrow.road.only}${ports ? `, ${ports}` : ''}`;
  }

  /**
   * Every port on the sign, not one left out. The sign grows to two lines, which beats an ellipsis.
   *
   * "Every port" arrives from the server already in words, so that is what it is compared
   * against: the page asks for its own language, and both say it out of the same dictionary.
   */
  static ports(road) {
    const said = [];
    for (const opening of road.openings) {
      const port = opening.ports === say('space.any-port') ? opening.protocol : opening.ports;
      if (!said.includes(port)) said.push(port);
    }
    return said.join(', ');
  }

  /** The sign stands at the castle's own gate, along its road, not in the middle of a field. */
  static signSpot(points) {
    const from = points[0];
    const to = points[1];
    const part = (one, other) => one + (other - one) * 0.62;
    if (from.y === to.y) return [part(from.x, to.x), from.y - 42];
    return [from.x + 104, part(from.y, to.y) - 13];
  }

  static gate(at, towards, size) {
    const flat = at.y === towards.y;
    const long = size + 10;
    return Svg.el('rect', {
      x: at.x - (flat ? 7 : long / 2), y: at.y - (flat ? long / 2 : 7),
      width: flat ? 14 : long, height: flat ? long : 14, fill: Look.DARK,
    });
  }

  /** The barrier at a gate: wide open, half down for "ports only", or grey for "unread". */
  static barrier(points, size, width) {
    const at = points[0];
    const flat = at.y === points[1].y;
    const long = size + 14;
    const thick = 7;
    const group = Svg.el('g');
    group.append(Svg.el('rect', {
      x: at.x - (flat ? thick / 2 : long / 2), y: at.y - (flat ? long / 2 : thick / 2),
      width: flat ? thick : long, height: flat ? long : thick, fill: Look.tone(width),
      stroke: Look.DARK, 'stroke-width': 2,
    }));
    if (width === 'ports') {
      const step = flat ? { x: 0, y: long / 3 } : { x: long / 3, y: 0 };
      for (let part = 0; part < 2; part += 1) {
        group.append(Svg.el('rect', {
          x: at.x - (flat ? thick / 2 : long / 2) + step.x * (part * 2 + 1),
          y: at.y - (flat ? long / 2 : thick / 2) + step.y * (part * 2 + 1),
          width: flat ? thick : long / 3, height: flat ? long / 3 : thick, fill: '#f6edd8',
        }));
      }
    }
    return group;
  }

  /** An access flag: the colour says what the width says, while the road stays the same. */
  static mark(at, colour) {
    const group = Svg.el('g');
    group.append(
      Svg.el('rect', { x: at.x + 12, y: at.y - 32, width: 3, height: 32, fill: Look.DARK }),
      Svg.el('polygon', {
        points: `${at.x + 15},${at.y - 32} ${at.x + 33},${at.y - 25} ${at.x + 15},${at.y - 18}`,
        fill: colour,
      }),
    );
    return group;
  }

  static flag(at) {
    const group = Svg.el('g');
    group.append(
      Svg.el('rect', { x: at.x - 26, y: at.y - 34, width: 3, height: 34, fill: Look.DARK }),
      Svg.el('polygon', {
        points: `${at.x - 23},${at.y - 34} ${at.x - 5},${at.y - 27} ${at.x - 23},${at.y - 20}`,
        fill: '#d32f2f',
      }),
    );
    return group;
  }

  static line(points) {
    return points.map((point, order) => `${order ? 'L' : 'M'} ${point.x} ${point.y}`).join(' ');
  }

  static bridges(marks) {
    const group = Svg.el('g');
    for (const mark of marks) {
      const deck = Bridges.deck(mark);
      group.append(Svg.el('rect', {
        x: deck.x, y: deck.y, width: deck.width, height: deck.height,
        fill: '#c9a063', stroke: Look.ROAD_EDGE, 'stroke-width': 2,
      }));
      const rail = (offset) => (deck.flat
        ? Svg.el('rect', { x: deck.x, y: deck.y + offset, width: deck.width, height: 3, fill: '#7a5230' })
        : Svg.el('rect', { x: deck.x + offset, y: deck.y, width: 3, height: deck.height, fill: '#7a5230' }));
      group.append(rail(2), rail((deck.flat ? deck.height : deck.width) - 5));
    }
    return group;
  }
}

class Sheet {
  /** Pictures of devices. */
  constructor(sprites) {
    this.sprites = sprites;
  }

  node(kind, x, y, scale) {
    return Sprite.node(this.sprites.icon(kind || ''), { x, y, scale });
  }

}

class Hint {
  constructor(node, field) {
    this.node = node;
    this.field = field;
    this.at = { x: 0, y: 0 };
    field.addEventListener('pointermove', (event) => {
      const box = field.getBoundingClientRect();
      this.at = { x: event.clientX - box.left + 14, y: event.clientY - box.top + 14 };
      if (!this.node.hidden) this.place();
    });
  }

  show(words) {
    if (!words) return;
    this.node.textContent = words;
    this.node.hidden = false;
    this.place();
  }

  place() {
    this.node.style.left = `${Math.min(this.at.x, this.field.clientWidth - 350)}px`;
    this.node.style.top = `${this.at.y}px`;
  }

  hide() {
    this.node.hidden = true;
  }
}

class Scroll {
  constructor(node) {
    this.node = node;
  }

  put(title, ...blocks) {
    this.node.replaceChildren(Object.assign(document.createElement('h2'), { textContent: title }), ...blocks);
  }

  //: What a line of access is, at a glance. Pointing at a mark names it in words. A line with
  //: exceptions is the other way round from them: "most" is open but for the ⛔ ones, "only" is
  //: shut but for the ✅ ones — an address, or an address and a port, for all or for one device.
  static MARKS = { home: '✅🏠', 'home-most': '✅🏠', open: '✅', most: '✅', port: '✅', shut: '⛔', only: '⛔' };
  //: What every line of access starts with: the way goes from here to the place on the line.
  static WAY = '➡️';
  //: How the router came to know an address.
  static SEEN = { lease: '📄', arp: '🔗', peer: '🔐', netmap: '🗺️' };

  /** A mark with its meaning under the pointer, for the eye and for a screen reader alike. */
  static mark(symbol, meaning) {
    const node = document.createElement('span');
    node.className = 'mark';
    node.textContent = symbol;
    node.title = meaning;
    node.setAttribute('aria-label', meaning);
    return node;
  }

  /** A list whose lines are made of words and marks. */
  static marked(lines, className) {
    const list = document.createElement('ul');
    if (className) list.className = className;
    for (const parts of lines) {
      const line = document.createElement('li');
      line.append(...parts);
      list.append(line);
    }
    return list;
  }

  /** Where it may go, place by place: the way, then the place's line and the lines under it. */
  static reach(rows) {
    return Scroll.marked(rows.map((row) => [Scroll.mark(Scroll.WAY, say('reach.way')), ' ', ...Scroll.reachLine(row)]),
                         'reach');
  }

  /**
   * One line of access without its way: a mark and the place; then, when something goes the
   * other way, the word "exception" and under it each exception on a line of its own. The rules
   * that shut a line are named under its mark, not on the line.
   */
  static reachLine(row) {
    const meaning = [say(`reach.${row.mark}`), row.rules].filter(Boolean).join('\n');
    const parts = [Scroll.mark(Scroll.MARKS[row.mark], meaning), ` ${row.title}`];
    if (row.note && (row.note.text || row.note.save)) parts.push(Scroll.note(row.note));
    if (row.but && row.but.length) {
      const word = Scroll.quiet(say(row.but.length > 1 ? 'reach.but-many' : 'reach.but-one'));
      parts.push(Scroll.marked([[word, Scroll.marked(row.but.map((one) => Scroll.reachItem(one)), 'under')]], 'under'));
    }
    return parts;
  }

  //: The longest note the server keeps: lan_map/server.py, MapApp.NOTE_MOST.
  static NOTE_MOST = 200;

  /**
   * What a line is for, after the line: "— Vaultwarden". When the map may be changed from here, a
   * pen writes or changes it in place; saved, the note changes at once on every line of the
   * scroll kept under the same key, and Escape leaves it as it was.
   */
  static note(note) {
    const node = document.createElement('span');
    node.className = 'note';
    node.dataset.key = note.key;
    const show = (text) => {
      const parts = text ? [Scroll.quiet(` — ${text}`)] : [];
      if (note.save) {
        const pen = document.createElement('button');
        pen.type = 'button';
        pen.className = 'pen';
        pen.textContent = '✎';
        pen.title = say('reach.note.edit');
        pen.setAttribute('aria-label', say('reach.note.edit'));
        pen.addEventListener('click', () => write(text));
        parts.push(' ', pen);
      }
      node.replaceChildren(...parts);
    };
    const write = (text) => {
      const row = document.createElement('span');
      row.className = 'naming';
      const field = document.createElement('input');
      field.type = 'text';
      field.value = text;
      field.maxLength = Scroll.NOTE_MOST;
      field.placeholder = say('reach.note.placeholder');
      const save = document.createElement('button');
      save.type = 'button';
      save.textContent = say('save');
      const send = async () => {
        field.disabled = true;
        save.disabled = true;
        const kept = await note.save(field.value.trim());
        if (kept === null) {
          field.disabled = false;
          save.disabled = false;
          return;
        }
        const scroll = node.closest('.scroll') || node.parentNode;
        for (const other of (scroll ? scroll.querySelectorAll('.note') : [node])) {
          if (other.dataset.key === note.key && other.show) other.show(kept);
        }
      };
      save.addEventListener('click', send);
      field.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') send();
        if (event.key === 'Escape') show(text);
      });
      row.append(field, save);
      node.replaceChildren(row);
      field.focus();
    };
    node.show = show;
    show(note.text);
    return node;
  }

  /** One exception: a line, or a device's own exceptions under its name, "for iPad 8:". */
  static reachItem(item) {
    if (!item.lines) return Scroll.reachLine(item);
    return [Scroll.quiet(item.label), Scroll.marked(item.lines.map((one) => Scroll.reachLine(one)), 'under')];
  }

  static quiet(text) {
    return Object.assign(document.createElement('span'), { className: 'quiet', textContent: text });
  }

  static list(items) {
    const list = document.createElement('ul');
    for (const item of items) {
      const line = document.createElement('li');
      line.textContent = item;
      list.append(line);
    }
    return list;
  }

  static words(text, className) {
    const line = document.createElement('p');
    line.textContent = text;
    if (className) line.className = className;
    return line;
  }

  /**
   * A device's card in the server's own words, and the way to its page. None (null) is a file
   * that would not read, never "nobody wrote one": the two are told apart.
   */
  static specs(device) {
    const told = device.specs === null ? [Scroll.words(say('device.specs.unread'), 'quiet')]
      : device.specs.length ? [Scroll.list(device.specs)] : [Scroll.words(say('device.specs.none'), 'quiet')];
    const page = new URL(tongue.href('/specs.html'), window.location.href);
    page.searchParams.set('device', device.key);
    const link = Object.assign(document.createElement('a'), {
      className: 'button', href: page.pathname + page.search, textContent: say('device.specs.edit'),
    });
    return [...told, link];
  }

  static about(road, title) {
    const signs = road.signs.length ? `: ${road.signs.join(', ')}` : '';
    const shut = road.shutTo ? say('road.except', { where: road.shutTo }) : '';
    const why = road.byDefault ? ` — ${say('road.by-default')}` : '';
    const moss = road.dead ? ` — ${say('road.never-used')}` : '';
    const name = road.renamed.length ? ` — ${say('road.renamed')}` : '';
    return `${title(road.source)} → ${title(road.target)}: `
      + `${say(`road.width.${road.width}`)}${signs}${shut}${why}${moss}${name}`;
  }

  /** A road's scroll. `notes` are what DSM on the NAS changes for its yard: see gateNotes(). */
  roads(corridor, title, notes = []) {
    const rows = corridor.ways.map((way) => Scroll.about(way.road, title));
    const blocks = [Scroll.words(say('road.of', { title: corridor.title })), Scroll.list(rows), ...Scroll.gate(notes)];
    const rules = corridor.ways.flatMap((way) => way.road.openings.flatMap((opening) => opening.rules.map(
      (rule) => say('rule.line', { index: rule.index, comment: rule.comment, packets: rule.packets }))));
    if (rules.length) {
      blocks.push(Scroll.words(say('road.opened-by'), 'quiet'), Scroll.list([...new Set(rules)]));
    }
    this.put(say('scroll.title'), ...blocks);
  }

  /** The block DSM's notes make, under its own heading; nothing at all when there are none. */
  static gate(notes) {
    return notes.length ? [Scroll.words(say('gate.notes'), 'quiet'), Scroll.list(notes)] : [];
  }

  /**
   * The router's "3h20m", said plainly. "never" does not mean "never switched on" but "we have
   * not seen it at this address": the lease may be minutes old and have met nobody yet.
   */
  static ago(last) {
    if (!last) return '';
    if (last === 'never') return say('ago.never');
    const parts = [...String(last).matchAll(/(\d+)([wdhms])/g)]
      .map(([, number, unit]) => say(`span.unit.${unit}`, { number }));
    return parts.length ? say('ago.seen', { span: parts.slice(0, 2).join(' ') }) : '';
  }

  /** A dweller's line: name, address, and when it was last seen if it is not online. */
  static dweller(device) {
    const seat = device.seats.find((one) => one.online) || device.seats[0] || {};
    const name = device.name || say('device.nameless');
    const hidden = device.hidden ? say('device.hidden') : '';
    if (device.online) return `${name} · ${seat.ip}${hidden}`;
    const ago = Scroll.ago(seat.last);
    return `${name} · ${seat.ip}${ago ? ` — ${ago}` : ''}${hidden}`;
  }

  castle(castle, world, title, notes = [], reach = []) {
    const segment = castle.segment;
    const all = castle.all || castle.devices;
    // Online first: they are asked about more often, and the dark ones can wait their turn.
    const dwellers = [...all].sort((one, other) => Number(other.online) - Number(one.online));
    // The yard beyond the gate is told as what it is: our address there, who is in charge, and
    // that its rules are not ours — so it has no lines of access of its own to show.
    const post = world.outpost || {};
    const facts = segment.outside ? [
      say('castle.network', { network: segment.network }),
      say('castle.on-router', { key: segment.key }),
      say('outpost.ours', { ours: segment.gateway }),
      post.gate ? say('outpost.gate', { gate: post.gate }) : say('outpost.no-gate'),
      say('castle.online', { here: castle.devices.length, all: castle.known }),
    ] : [
      say('castle.network', { network: segment.network })
        + (segment.vlan ? `, VLAN ${segment.vlan}` : ''),
      // This line earns its place only when the castle's name was invented on the map: if it
      // already equals the interface name, repeating it takes room and says nothing.
      ...(segment.title === segment.key ? [] : [say('castle.on-router', { key: segment.key })]),
      say('castle.gateway', { gateway: segment.gateway }),
      say(segment.temporary ? 'castle.temporary' : 'castle.permanent'),
      say('castle.online', { here: castle.devices.length, all: castle.known }),
    ];
    const blocks = [
      Scroll.words(say('castle.of', { title: segment.title })),
      Scroll.list(facts),
      ...(segment.outside ? [Scroll.words(say('outpost.not-ours'), 'quiet')] : []),
      ...(reach.length ? [Scroll.words(say('device.reach'), 'quiet'), Scroll.reach(reach)] : []),
      ...Scroll.gate(notes),
    ];
    // Two separate parts rather than one list with a tail: "who is here" and "who is not" are
    // different questions, and telling them apart by eye should not be the reader's work.
    const here = dwellers.filter((device) => device.online);
    const gone = dwellers.filter((device) => !device.online);
    if (here.length) {
      blocks.push(Scroll.words(say('castle.here', { count: here.length }), 'quiet'),
                  Scroll.list(here.map((device) => Scroll.dweller(device))));
    }
    if (gone.length) {
      blocks.push(Scroll.words(say('castle.gone', { count: gone.length }), 'quiet'),
                  Scroll.list(gone.map((device) => Scroll.dweller(device))));
    }
    this.put(say('scroll.title'), ...blocks);
  }

  /** A line about a door: its number, a short name and a guess about who lives there. */
  static door(row) {
    return `${row.port} — ${say(row.name)}: ${say(row.about)}`;
  }

  /** We knocked from another network: that must be said, or an empty answer would lie. */
  static elsewhere(from, ip) {
    const net = (address) => String(address).split('.').slice(0, 3).join('.');
    return Boolean(from) && net(from) !== net(ip);
  }

  /**
   * Doors reach the scroll after the rest: while we knock, a "knocking" line stands in their
   * place. So this is a part of its own that gets replaced, not the whole scroll again —
   * otherwise a name or a kind being chosen would reset under the reader's hands.
   */
  doors(answer, again) {
    const box = this.node.querySelector('.doors');
    if (!box) return;
    const blocks = [];
    if (answer.error) {
      blocks.push(Scroll.words(answer.error, 'quiet'));
    } else {
      blocks.push(Scroll.words(say(answer.open.length ? 'doors.open' : 'doors.none'), 'quiet'));
      if (answer.open.length) blocks.push(Scroll.list(answer.open.map(Scroll.door)));
      blocks.push(Scroll.words(say('doors.knocked', {
        from: answer.from || say('doors.from-unknown'),
        knocked: answer.knocked, took: answer.took }), 'quiet'));
      if (!answer.open.length && Scroll.elsewhere(answer.from, answer.ip)) {
        blocks.push(Scroll.words(say('doors.from-elsewhere'), 'quiet'));
      }
    }
    if (again) blocks.push(again);
    box.replaceChildren(...blocks);
  }

  device(device, page, reach) {
    // A seat is a line of marks and words: online or an old lease, where, how long ago, and
    // how the router came to know it. The marks say it at a glance; pointing at one names it.
    const seats = device.seats.map((seat) => {
      const ago = Scroll.ago(seat.last);
      return [Scroll.mark(seat.online ? '🟢' : '⚪', say(seat.online ? 'device.online' : 'seat.old-lease')),
              ` ${seat.ip} — ${page ? page.titleOf(seat.segment) : seat.segment}${ago ? ` · ${ago}` : ''} `,
              ...seat.seen.map((one) => Scroll.mark(Scroll.SEEN[one] || '•', say(`seen.${one}`)))];
    });
    const blocks = [Scroll.words(device.name || say('device.nameless')), Scroll.marked(seats)];
    if (reach) blocks.push(Scroll.words(say('device.reach'), 'quiet'), Scroll.reach(reach));
    else if (page && page.beyondOnly(device)) blocks.push(Scroll.words(say('outpost.not-ours'), 'quiet'));
    if (page) {
      const walks = page.walks(device);
      if (walks.length) {
        blocks.push(Scroll.words(say('device.walks-now'), 'quiet'), Scroll.list(walks));
      } else if (device.online) {
        blocks.push(Scroll.words(say('device.walks-nowhere'), 'quiet'));
      }
      if (!page.beyondOnly(device)) {
        const doors = document.createElement('div');
        doors.className = 'doors';
        doors.append(Scroll.words(say('doors.knocking'), 'quiet'));
        blocks.push(Scroll.words(say('doors.title'), 'quiet'), doors);
      }
      blocks.push(page.tools(device));
      blocks.push(Scroll.words(say('device.name'), 'quiet'), page.naming(device));
      blocks.push(Scroll.words(say('device.kind'), 'quiet'), page.kinds(device));
      blocks.push(Scroll.words(say('device.specs'), 'quiet'), ...Scroll.specs(device));
    }
    this.put(say('scroll.title'), ...blocks);
  }
}

class Fog {
  //: The fog's own colour: the night over a network one may not reach.
  static COLOUR = '#1d2430';
  static OPACITY = 0.72;

  /** A dark cover with windows cut out of it: the machines one may reach show through. */
  static dark(area, holes) {
    if (!holes.length) {
      return Svg.el('rect', { ...area, fill: Fog.COLOUR, opacity: Fog.OPACITY, rx: 6 });
    }
    const ring = (box) => `M${box.x} ${box.y}h${box.width}v${box.height}h${-box.width}Z`;
    return Svg.el('path', { d: [area, ...holes].map(ring).join(' '), fill: Fog.COLOUR,
                            opacity: Fog.OPACITY, 'fill-rule': 'evenodd' });
  }

  /** Stripes: the whole network, but only some of its doors. */
  static striped(area) {
    return Svg.el('rect', { ...area, fill: 'url(#fog-stripes)', rx: 6 });
  }

  static stripes() {
    return Svg.el('defs', {},
      Svg.el('pattern', { id: 'fog-stripes', width: 14, height: 14, patternUnits: 'userSpaceOnUse',
                          patternTransform: 'rotate(45)' },
      Svg.el('rect', { x: 0, y: 0, width: 7, height: 14, fill: Fog.COLOUR, opacity: Fog.OPACITY })));
  }
}

class Eyes {
  /** Through a device's eyes: where it may call, and where the fog begins. */
  constructor(world) {
    this.world = world;
  }

  /** The words Sight compares openings against: said by the server, in the page's language. */
  static words() {
    return { anyPort: say('space.any-port'), anyProtocol: say('space.any') };
  }

  seen(device) {
    return new Set(this.where(device).map((step) => step.target));
  }

  /** Where this device may call and on which ports: worked out from the rules' addresses. */
  where(device) {
    const found = [...new Set(device.homes)].map((home) => ({ target: home, width: 'home', ports: [] }));
    for (const { road, openings: mine } of new Sight(this.world, Eyes.words()).deviceRoads(device)) {
      const ports = [...new Set(mine.map((opening) => (opening.ports === say('space.any-port')
        ? opening.protocol : `${opening.protocol} ${opening.ports}`)))];
      const wide = road.width === 'all' || road.width === 'most';
      found.push({ target: road.target, width: road.width, only: road.only,
                   shutTo: road.shutTo, ports: wide ? [] : ports });
    }
    return found;
  }
}


class Menu {
  /**
   * The right-click menu: "do this to that", without taking one's eyes off the map.
   *
   * An item is a button with a deed. An item with a nest opens a second leaf beside it: that
   * way a set of three dozen icons does not cover the map itself.
   */
  constructor(field) {
    this.field = field;
    this.node = null;
    field.addEventListener('pointerdown', (event) => {
      if (this.node && !this.node.contains(event.target)) this.hide();
    });
  }

  show(at, title, items) {
    this.hide();
    const node = document.createElement('div');
    node.className = 'menu';
    const head = document.createElement('p');
    head.className = 'head';
    head.textContent = title;
    node.append(head, ...items.map((item) => this.line(item)));
    node.style.left = `${Math.min(at.x, this.field.clientWidth - 240)}px`;
    node.style.top = `${Math.min(at.y, Math.max(12, this.field.clientHeight - 60))}px`;
    this.field.append(node);
    this.node = node;
  }

  line(item) {
    if (item.split) {
      const rule = document.createElement('hr');
      return rule;
    }
    if (item.field) {
      const row = document.createElement('div');
      row.className = 'naming';
      const input = document.createElement('input');
      input.type = 'text';
      input.value = item.field.value || '';
      input.placeholder = item.label;
      input.maxLength = 48;
      const done = () => { this.hide(); item.field.run(input.value.trim()); };
      input.addEventListener('keydown', (event) => { if (event.key === 'Enter') done(); });
      const save = document.createElement('button');
      save.type = 'button';
      save.textContent = say('menu.ok');
      save.addEventListener('click', done);
      row.append(input, save);
      return row;
    }
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = item.label + (item.nest ? ' ›' : '');
    if (item.on) button.classList.add('on');
    button.addEventListener('click', () => {
      if (item.nest) {
        this.nest(button, item.nest());
        return;
      }
      this.hide();
      item.run();
    });
    return button;
  }

  nest(button, content) {
    const older = this.node.querySelector('.nest');
    if (older) older.remove();
    const box = document.createElement('div');
    box.className = 'nest';
    box.append(content);
    button.after(box);
  }

  hide() {
    if (this.node) this.node.remove();
    this.node = null;
  }
}

class MapPage extends Page {
  constructor() {
    super();
    this.map = document.getElementById('map');
    this.field = document.querySelector('.field');
    this.hint = new Hint(document.getElementById('hint'), this.field);
    this.menu = new Menu(this.field);
    this.found = new Set();
    //: Doors already knocked at: clicking houses back and forth is no reason to knock again.
    this.doors = new Map();
    //: Whose scroll is open: a late answer about somebody else's doors will not reach it.
    this.shown = '';
    this.at = '';
    //: The map always opens on the whole island: zoom is a passing thing, not worth remembering.
    this.zoom = 1;
    this.eye = { x: Look.FIELD.width / 2, y: Look.FIELD.height / 2 };
    this.scroll = new Scroll(document.getElementById('scroll'));
    this.when = document.getElementById('when');
    this.eyes = '';
    //: The subnet whose eyes the map looks through: its fog, its road signs. "" when none.
    this.watching = '';
    this.layers = { roads: true, devices: true, notes: true, carts: true };
    this.carts = [];
    //: The one cart the mouse holds — {key, node, since} — and when it let each one go. This
    //: lives on the page, not in the cart: a redraw builds them afresh, and a hold and a rest
    //: must both survive that.
    this.held = null;
    this.touched = new Map();
    this.access = MapPage.remembered('access', Look.SHOWS[0]);
    this.dragging = null;
    this.drawing = null;
    this.saving = null;
  }

  async start() {
    try {
      this.sprites = new Sheet(await Sprites.load('sprites.json'));
    } catch (err) {
      this.warn(say('sprites.failed', { why: err.message }));
      return;
    }
    document.getElementById('refresh').addEventListener('click', () => this.refresh());
    document.getElementById('seek').addEventListener('input', (event) => this.seek(event.target.value));
    document.getElementById('shelf').addEventListener('change', (event) => {
      this.at = event.target.value;
      this.load();
    });
    document.getElementById('theme').addEventListener('click', () => this.flip());
    document.getElementById('out').addEventListener('click', () => this.scale(1 / 1.2));
    document.getElementById('in').addEventListener('click', () => this.scale(1.2));
    document.getElementById('zoom').addEventListener('click', () => this.whole());
    this.told();
    await this.languages();
    this.map.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      this.menu.show(this.spot(event), say('map.title'), this.fieldMenu());
    });
    document.addEventListener('keydown', (event) => this.keys(event));
    this.theme();
    this.watchPointer();
    await this.freshen(await this.load());
  }

  /**
   * Nothing on a schedule asks the router any more. So when somebody opens the map on a snapshot
   * the server calls old, or on none yet (503), the page asks for a fresh one, as the button does.
   */
  async freshen(failed) {
    if (this.at) return;
    if (failed === 503 || (this.world && this.world.refresh_on_open)) await this.refresh();
  }

  /**
   * In another language the page's own words are redressed first, then the server is asked
   * again: road widths, findings and notes are said by the server, and the two halves must
   * never end up in different languages.
   */
  async retell() {
    this.told();
    await this.load();
  }

  /** The address of the map, in the language of whoever is looking. */
  where(path) {
    const asked = new URLSearchParams({ lang: tongue.code });
    if (this.at) asked.set('at', this.at);
    return `${path}?${asked}`;
  }

  /** The map from the server; the status it refused with, when it did. */
  async load() {
    try {
      this.world = await Api.request('GET', this.where('/api/map'));
    } catch (err) {
      this.warn(err.message);
      return err.status;
    }
    this.warn('');
    this.places = new Places(this.world.layout.places, this.world.segments.map((one) => one.key));
    this.places.looks = { ...this.world.layout.looks };
    const size = this.world.layout.field;
    Look.FIELD = size && size.length === 2
      ? { width: size[0], height: size[1] } : { width: 1200, height: 860 };
    this.eye = { x: Look.FIELD.width / 2, y: Look.FIELD.height / 2 };
    this.when.textContent = say('bar.taken', { clock: this.world.taken.slice(11, 16) })
      + (this.at ? ` · ${say('bar.looking-back')}` : '');
    if (!this.world.move.allowed) {
      this.warn(say('move.not-allowed', { why: this.world.move.reason }));
    }
    this.journal();
    this.banner();
    this.shelf();
    this.watchers();
    this.draw();
    document.body.classList.toggle('back', Boolean(this.at));
  }

  // --- drawing ----------------------------------------------------------------------------------
  draw() {
    cancelAnimationFrame(this.rolling);
    this.carts = [];
    this.map.setAttribute('viewBox', this.viewBox());
    const groups = {
      island: Svg.el('g'), roads: Svg.el('g'), notes: Svg.el('g', { class: 'notes' }),
      castles: Svg.el('g'), devices: Svg.el('g'), carts: Svg.el('g'),
      // The fog is looked through, never clicked: a click on a dark network is a click on that
      // network — its heading, its fence, its houses — and turns the eyes to it.
      fog: Svg.el('g', { 'pointer-events': 'none' }),
    };
    this.groups = groups;
    const town = this.places.of('router');
    // A network that comes and goes is drawn as a tunnel — until somebody is known to be in
    // it. An occupied network one cannot see is the one thing a map must not do, and the
    // dashed border says "temporary" well enough on a yard.
    const empty = (segment) => segment.temporary
      && !this.world.devices.some((device) => this.livesIn(device, segment.key));
    this.castles = this.world.segments.filter((segment) => !empty(segment)).map((segment) => new Castle(
      segment, this.world.devices.filter((device) => this.livesIn(device, segment.key)),
      this.places.of(segment.key), this.look(segment.key)));
    this.castles.forEach((castle) => this.keepInside(castle));
    const corridors = this.corridors(town);
    const square = this.square();
    const pier = this.places.of(this.world.ends.internet);
    this.places.beside('notices', { x: town.x + square.width / 2, y: town.y + square.height / 2 });
    this.places.beside('signpost', pier);
    this.places.beside('docker', this.dockerCorner(town, square));
    this.places.beside('story', pier);
    this.places.beside('guide', pier);
    this.places.beside('gate', this.gateCorner(town, square));
    groups.island.append(...this.island(), this.grip());
    for (const segment of this.world.segments.filter(empty)) {
      groups.island.append(this.tunnel(segment, town));
    }
    groups.island.append(this.pier(town), this.town(town));
    const bridges = Bridges.find(corridors);
    corridors.forEach((corridor, order) => {
      groups.roads.append(Roadwork.bridges(bridges.filter((mark) => mark.over === order)));
      const road = Roadwork.draw(corridor, this);
      if (road) groups.roads.append(road);
    });
    for (const castle of this.castles) {
      groups.castles.append(castle.draw(this));
      groups.devices.append(castle.houses(this));
    }
    groups.castles.append(this.noticeBoard(this.places.of('notices')),
                          this.signpost(this.places.of('signpost')),
                          this.containerStack(this.places.of('docker')),
                          this.storyBook(this.places.of('story')),
                          this.guidePost(this.places.of('guide')),
                          this.gatehouse(this.places.of('gate')));
    if (this.layers.carts) groups.carts.append(...this.harness(corridors));
    if (this.eyes || this.watching) groups.fog.append(...this.fog(), ...this.pinned());
    if (!this.layers.roads) groups.roads.classList.add('gone');
    if (!this.layers.devices) groups.devices.classList.add('gone');
    if (!this.layers.notes) groups.notes.classList.add('gone');
    // Findings above the castles: a flag and a sign must be seen, not hide behind a wall.
    this.map.replaceChildren(groups.island, groups.roads, groups.castles, groups.devices,
                             groups.carts, groups.notes, groups.fog);
    this.signs = [...groups.notes.querySelectorAll('.sign')];
    if (this.carts.length) this.rolling = requestAnimationFrame(() => this.roll());
  }

  /**
   * A castle nobody moved must not spill past the shore: it grows with the number of houses.
   * What was moved by hand is left alone: there a human knew what they wanted.
   */
  keepInside(castle) {
    if (this.places.places[castle.segment.key]) return;
    const box = castle.box;
    const top = Look.SHORE + 50 + box.height / 2;
    const bottom = Look.FIELD.height - Look.SHORE - 80 - box.height / 2;
    const left = Look.SHORE + 24 + box.width / 2;
    const right = Look.FIELD.width - Look.SHORE - 24 - box.width / 2;
    castle.place = {
      x: Math.max(Math.min(left, right), Math.min(castle.place.x, Math.max(left, right))),
      y: Math.max(Math.min(top, bottom), Math.min(castle.place.y, Math.max(top, bottom))),
    };
  }

  /**
   * A house stands in the yard of every subnet it lives in — in all of them at once, not in
   * one with strings tied to the rest. Which is the truth about a netmapped phone: it holds
   * an address in the tunnel and wears another one everywhere else, and both are it.
   */
  livesIn(device, key) {
    return device.homes.includes(key)
      || (!device.homes.length && device.seats.some((seat) => seat.segment === key));
  }

  island() {
    const field = Look.FIELD;
    const shore = Look.SHORE;
    return [
      Svg.el('rect', { x: 0, y: 0, width: field.width, height: field.height, fill: Look.SEA }),
      Svg.el('rect', {
        x: shore, y: shore, width: field.width - shore * 2, height: field.height - shore * 2 - 60,
        fill: Look.SAND, rx: 18,
      }),
      Svg.el('rect', {
        x: shore + 14, y: shore + 14, width: field.width - (shore + 14) * 2,
        height: field.height - (shore + 14) * 2 - 60, fill: Look.GRASS, rx: 14,
      }),
    ];
  }

  /**
   * The corner of the island it is dragged by. A bigger island means more room for castles,
   * and the layout does not shift for it: things stay where they stood.
   */
  grip() {
    const field = Look.FIELD;
    const x = field.width - Look.SHORE - 34;
    const y = field.height - Look.SHORE - 94;
    const group = Svg.el('g', { class: 'grip', 'data-grip': 'island' });
    group.append(
      Svg.el('rect', { x, y, width: 34, height: 34, fill: Look.SAND, stroke: Look.ROAD_EDGE, 'stroke-width': 2 }),
      Svg.el('rect', { x: x + 7, y: y + 20, width: 20, height: 3, fill: Look.ROAD_EDGE }),
      Svg.el('rect', { x: x + 14, y: y + 13, width: 13, height: 3, fill: Look.ROAD_EDGE }),
      Svg.el('rect', { x: x + 21, y: y + 6, width: 6, height: 3, fill: Look.ROAD_EDGE }),
    );
    group.addEventListener('pointerenter', () => this.hint.show(say('island.drag')));
    group.addEventListener('pointerleave', () => this.hint.hide());
    return group;
  }

  corridors(town) {
    const found = new Map();
    for (const castle of this.castles) {
      const corridor = new Corridor(castle, town);
      corridor.key = castle.segment.key;
      corridor.title = castle.segment.title;
      found.set(castle.segment.key, corridor);
    }
    const pier = new Corridor(this.pierNode(), town);
    pier.key = this.world.ends.internet;
    pier.title = say('pier.title');
    found.set(pier.key, pier);
    for (const road of this.world.roads) {
      if (road.target === this.world.ends.router || road.width === 'shut') continue;
      const from = found.get(road.source);
      const to = found.get(road.target);
      if (from) from.add(road, 'out');
      if (to) to.add(road, 'in');
    }
    const corridors = [...found.values()].filter((corridor) => corridor.ways.length);
    this.townSize = Corridor.gates(corridors);
    return corridors;
  }

  pierNode() {
    const place = this.places.of(this.world.ends.internet);
    return { place, box: { x: place.x - 60, y: place.y - 26, width: 120, height: 52 } };
  }

  town(at) {
    const size = this.square();
    const group = Svg.el('g', { class: 'held', 'data-move': 'router' });
    group.append(
      Svg.el('rect', { x: at.x - size.width / 2, y: at.y - size.height / 2,
                       width: size.width, height: size.height, fill: '#b9b1a4' }),
      Svg.el('rect', { x: at.x - size.width / 2 + 8, y: at.y - size.height / 2 + 8,
                       width: size.width - 16, height: size.height - 16, fill: '#cfc6b6' }),
      Svg.el('rect', { x: at.x - 26, y: at.y - size.height / 2 - 16, width: 52, height: 22, fill: '#b9b1a4' }),
      Svg.el('rect', { x: at.x - 16, y: at.y - 26, width: 32, height: 26, fill: Look.DARK }),
      this.lantern({ x: at.x, y: at.y - 13 }),
      Svg.words(at.x, at.y + 26, say('town.router'), { fill: Look.INK, 'font-size': 16 }),
    );
    group.addEventListener('pointerenter', () => this.hint.show(say('town.about')));
    group.addEventListener('pointerleave', () => this.hint.hide());
    group.addEventListener('click', () => this.tellAboutRouter());
    group.addEventListener('contextmenu', (event) => {
      event.preventDefault();
      event.stopPropagation();
      this.menu.show(this.spot(event), say('town.title'), this.townMenu());
    });
    return group;
  }

  /** The router's square: as wide and tall as his gates need, never smaller than the plan. */
  square() {
    return this.townSize || Look.TOWN;
  }

  /**
   * A way from the island into a page of its own: the notice board, the signpost, the stack of
   * containers, the book and the robot. It is a link, so it opens the way links do, and a right
   * click brings the link's own menu — open in a new tab, copy the address — rather than the
   * field's. A text (`text`) opens in the page's language and in a tab of its own: a text has no
   * way back to the map.
   *
   * Each stands beside what it belongs to, follows it, and can be dragged aside (`move` names
   * its place). Once the mouse moves the pointer is captured, and a drag never turns into a
   * click on the link.
   */
  wayIn({ href, text, move, about }, ...parts) {
    const link = Svg.el('a', { href: text ? tongue.href(href) : href, target: text && '_blank',
                               rel: text && 'noopener', class: 'way-in', 'data-move': move }, ...parts);
    link.addEventListener('pointerenter', () => this.hint.show(about));
    link.addEventListener('pointerleave', () => this.hint.hide());
    link.addEventListener('contextmenu', (event) => event.stopPropagation());
    return link;
  }

  //: The notice board by the router: the board itself, and how far its posts reach down.
  static NOTICES = { width: 72, height: 60, post: 16 };

  /**
   * The notice board by the router. The names he answers for himself are pinned to it, and it
   * leads to their page.
   *
   * It stands on the grass off the lower right corner of his square, and goes where the square
   * goes. Inside the square it ended up under the carts that wait at the gates: covered, with
   * its clicks taken by them. Roads leave the square from its sides, not from its corners — but
   * a road may still bend past, so the board can be dragged aside, and it stays where it was
   * put, beside the square.
   */
  noticeBoard(at) {
    const { width, height, post } = MapPage.NOTICES;
    const left = at.x;
    const top = at.y;
    return this.wayIn({ href: '/names.html', move: 'notices', about: say('town.board.about') },
      Svg.el('rect', { x: left + 12, y: top + height, width: 5, height: post, fill: Look.DARK }),
      Svg.el('rect', { x: left + width - 17, y: top + height, width: 5, height: post, fill: Look.DARK }),
      Svg.el('rect', { x: left, y: top, width, height, fill: Look.DARK }),
      Svg.el('rect', { x: left + 3, y: top + 3, width: width - 6, height: height - 6, fill: Look.WOOD }),
      Svg.words(left + width / 2, top + 15, say('town.board'),
                { fill: Look.GOLD, 'font-size': 18, 'font-weight': 'bold' }),
      // Three notes pinned up, three lines of writing on each: at any size, that is a notice.
      ...[7, 27.5, 48].flatMap((x) => [
        Svg.el('rect', { x: left + x, y: top + 28, width: 17, height: 24, fill: Look.BOARD }),
        Svg.el('rect', { x: left + x + 7, y: top + 26, width: 3, height: 3, fill: Look.PIN }),
        ...[6, 11, 16].map((y, line) => Svg.el('rect', {
          x: left + x + 2, y: top + 28 + y, width: 13 - line * 2, height: 2, fill: Look.STONE })),
      ]));
  }

  /** The yard of the house the map itself lives in, found by the map's own address; or null. */
  homeCastle() {
    const here = this.world.here;
    const home = here ? this.world.devices.find((device) => device.seats.some((one) => one.ip === here)) : null;
    const seat = home ? home.seats.find((one) => one.ip === here) : null;
    return seat ? this.castles.find((one) => one.segment.key === seat.segment) || null : null;
  }

  /**
   * Where the stack of containers stands: by the lower left corner of the yard of the house
   * the map itself lives in, since that is the host the containers are counted on. A map that
   * cannot tell its own house puts the stack by the router's square instead of nowhere.
   */
  dockerCorner(town, square) {
    const castle = this.homeCastle();
    if (castle) {
      const box = castle.box;
      return { x: box.x, y: box.y + box.height };
    }
    return { x: town.x - square.width / 2, y: town.y + square.height / 2 };
  }

  /**
   * Where the guardhouse stands: beside the same yard, a little above its top, for DSM's gate is
   * the gate of the house the map lives in. The road's sign takes the space along the road below
   * the yard, and the stack of containers its lower left; the signs of a neighbour's road often
   * stand level with the yard, so the guardhouse rises above them, but not past the grass. The
   * right side is the guardhouse's; the left, when the yard leaves no room before the shore. A
   * map that cannot tell its house puts the guardhouse by the router's square.
   */
  gateCorner(town, square) {
    const { width, height, rise } = MapPage.GATE;
    const castle = this.homeCastle();
    if (!castle) {
      return { x: town.x - square.width / 2 - 6 - width, y: town.y - square.height / 2 - 6 - height };
    }
    const box = castle.box;
    const right = box.x + box.width + 6;
    const room = right + width <= Look.FIELD.width - Look.SHORE - 14;
    return { x: room ? right : box.x - 6 - width, y: Math.max(box.y - rise, Look.SHORE + 24) };
  }

  //: The stack of containers: its size, and the colours of its three crates, rust and blues.
  static STACK = { width: 80, height: 60 };
  static CRATES = ['#3f6fb5', '#b5443a', '#f0a020'];

  /**
   * A stack of shipping containers by the yard of the house the map lives in: Docker's own
   * picture of what runs there. The sign on top counts the running containers. A red flag
   * goes up when one of them is unhealthy, when the snapshot is stale, or when there is none.
   *
   * It leads to /containers.md, the very text agents read.
   */
  containerStack(at) {
    const docker = this.world.docker || {};
    const link = this.wayIn({ href: '/containers.md', text: true, move: 'docker', about: this.aboutDocker(docker) });
    const crate = (x, y, colour) => [
      Svg.el('rect', { x, y, width: 34, height: 18, fill: colour, stroke: Look.DARK, 'stroke-width': 1.5 }),
      // corrugated walls, and the doors at one end
      ...[6, 12, 18, 24].map((dx) => Svg.el('rect', { x: x + dx, y: y + 3, width: 1.5, height: 12,
                                                      fill: Look.DARK, opacity: 0.35 })),
      Svg.el('rect', { x: x + 29, y: y + 2, width: 3, height: 14, fill: Look.DARK, opacity: 0.5 }),
    ];
    link.append(
      ...crate(at.x + 4, at.y + 40, MapPage.CRATES[0]),
      ...crate(at.x + 42, at.y + 40, MapPage.CRATES[1]),
      ...crate(at.x + 23, at.y + 20, MapPage.CRATES[2]),
      Svg.el('rect', { x: at.x + 4, y: at.y, width: 72, height: 16, fill: Look.DARK }),
      Svg.words(at.x + 40, at.y + 8, say('docker.sign', { running: docker.missing ? '?' : docker.running }),
                { fill: Look.GOLD, 'font-size': 10, 'font-weight': 'bold' }));
    if (docker.missing || docker.stale || docker.unhealthy) {
      link.append(Svg.el('rect', { x: at.x + 64, y: at.y + 18, width: 2, height: 22, fill: Look.DARK }),
                  Svg.el('polygon', { points: `${at.x + 66},${at.y + 18} ${at.x + 78},${at.y + 22} ${at.x + 66},${at.y + 26}`,
                                      fill: Look.PIN }));
    }
    return link;
  }

  /** What the stack says under the pointer: counts, the snapshot's time, and any trouble. */
  aboutDocker(docker) {
    if (docker.missing) return say('docker.none');
    const words = [say('docker.about', { host: docker.host || '?', running: docker.running, idle: docker.idle,
                                         time: Page.clock(docker.taken) })];
    if (docker.stale) words.push(say('docker.stale'));
    if (docker.unhealthy) words.push(say('docker.unhealthy', { count: docker.unhealthy }));
    return words.join(' ');
  }

  //: The guardhouse by the NAS's yard: its size, the board on its right, how many letters of a
  //: name fit a line of the board, and how far above the yard's top it stands.
  static GATE = { width: 100, height: 76, board: 68, letters: 8, rise: 24 };

  /**
   * A guardhouse by the yard of the house the map lives in: DSM's own gate on the NAS. The router
   * decides who reaches the NAS; DSM's reverse proxy there asks again, name by name. The board
   * says what DSM changes: a lock for a name it turns some away from, an arrow for a name it leads
   * on past a road the router keeps shut, and how many names let in whoever the router lets in.
   * A red flag goes up for a way past the router, for a reading missing, stale or unclear, and for
   * a firewall the map cannot vouch for. A click tells the whole list in the scroll.
   *
   * With no reading the board says "?" and nothing else: a gate nobody has looked at is not an
   * open gate. Like the board, the signpost and the crates, it can be dragged aside.
   */
  gatehouse(at) {
    const { width, height, board } = MapPage.GATE;
    const gate = this.world.gate || { missing: 'gate.no-snapshot', doors: [], firewall: {} };
    const left = at.x + width - board;
    const group = Svg.el('g', { class: 'way-in', 'data-move': 'gate' },
      // the tower: stone, three teeth on top, a slit of a window and a dark doorway
      Svg.el('rect', { x: at.x + 2, y: at.y + 16, width: 26, height: height - 16, fill: Look.STONE,
                       stroke: Look.DARK, 'stroke-width': 2 }),
      ...[2, 11, 20].map((dx) => Svg.el('rect', { x: at.x + dx, y: at.y + 9, width: 8, height: 8, fill: Look.STONE,
                                                   stroke: Look.DARK, 'stroke-width': 2 })),
      Svg.el('rect', { x: at.x + 13, y: at.y + 26, width: 4, height: 9, fill: Look.DARK }),
      Svg.el('rect', { x: at.x + 9, y: at.y + height - 20, width: 12, height: 20, fill: Look.DARK }),
      // the barrier, red and white, from the tower to its post
      ...Array.from({ length: Math.ceil((width - 33) / 8) }, (_, step) => Svg.el('rect', {
        x: at.x + 28 + step * 8, y: at.y + height - 15, width: Math.min(8, width - 33 - step * 8), height: 5,
        fill: step % 2 ? Look.BOARD : Look.PIN })),
      Svg.el('rect', { x: at.x + width - 5, y: at.y + height - 20, width: 5, height: 20, fill: Look.DARK }),
      // the board: who DSM turns away, who it leads past the router, how many it lets in
      Svg.el('rect', { x: left, y: at.y, width: board, height: 50, fill: Look.DARK }),
      Svg.el('rect', { x: left + 2, y: at.y + 2, width: board - 4, height: 46, fill: Look.WOOD }),
      Svg.words(left + board / 2, at.y + 9, say('gate.sign'), { fill: Look.GOLD, 'font-size': 10, 'font-weight': 'bold' }),
      ...this.gateLines(gate).flatMap((line, order) => [
        ...MapPage.gateIcon(line.icon, left + 5, at.y + 18 + order * 11),
        Svg.words(left + 16, at.y + 22 + order * 11, line.text,
                  { fill: Look.BOARD, 'font-size': 9, 'text-anchor': 'start', ...MapPage.squeezed(line.text, board - 20) })]));
    if (this.gateTrouble(gate)) {
      group.append(Svg.el('rect', { x: at.x + 14, y: at.y - 8, width: 2, height: 18, fill: Look.DARK }),
                   Svg.el('polygon', { points: `${at.x + 16},${at.y - 8} ${at.x + 28},${at.y - 4} ${at.x + 16},${at.y}`,
                                       fill: Look.PIN }));
    }
    group.addEventListener('pointerenter', () => this.hint.show(this.aboutGate(gate)));
    group.addEventListener('pointerleave', () => this.hint.hide());
    group.addEventListener('click', () => this.tellAboutGate());
    return group;
  }

  /**
   * A board's line that would run past its edge is pressed to fit: the same words are longer in
   * one language than in another, and a language's words are not for the drawing to choose. A monospace letter at
   * nine pixels is a little over five wide.
   */
  static squeezed(text, room) {
    return text.length * 9 * 0.6 > room ? { textLength: room, lengthAdjust: 'spacingAndGlyphs' } : {};
  }

  /** The names on the board in four heaps: turned away, past the router, unclear, plain open. */
  static gateParts(gate) {
    const doors = gate.doors || [];
    const closed = doors.filter((door) => door.refuses.length);
    const past = doors.filter((door) => door.past.length);
    const unclear = doors.filter((door) => door.unclear.length || door.profile === 'unread');
    const open = doors.filter((door) => !closed.includes(door) && !past.includes(door) && !unclear.includes(door));
    return { closed, past, unclear, open };
  }

  /** At most three lines: the heaps that are not empty, a name when there is one, a count when more. */
  gateLines(gate) {
    if (gate.missing) return [{ icon: 'unknown', text: '?' }];
    const { closed, past, unclear, open } = MapPage.gateParts(gate);
    const suffix = MapPage.commonSuffix((gate.doors || []).map((door) => door.name));
    const { letters } = MapPage.GATE;
    const name = (doors) => {
      if (doors.length > 1) return `×${doors.length}`;
      const full = doors[0].name;
      const short = full.endsWith(suffix) && full.length > suffix.length ? full.slice(0, -suffix.length) : full;
      return short.length > letters ? `${short.slice(0, letters - 1)}…` : short;
    };
    return [
      ...(closed.length ? [{ icon: 'lock', text: name(closed) }] : []),
      ...(past.length ? [{ icon: 'arrow', text: name(past) }] : []),
      ...(unclear.length ? [{ icon: 'unknown', text: name(unclear) }] : []),
      { icon: 'open', text: say('gate.sign.open', { count: open.length }) },
    ].slice(0, 3);
  }

  /**
   * The ending every name shares, from a dot: ".lan.example". The board has room for "vault",
   * not for "vault.lan.example"; the hint and the scroll say names in full.
   */
  static commonSuffix(names) {
    if (!names.length) return '';
    const split = names.map((name) => name.split('.').reverse());
    const shared = [];
    for (let part = 0; split.every((labels) => labels.length > part && labels[part] === split[0][part]); part += 1) {
      shared.unshift(split[0][part]);
    }
    return shared.length ? `.${shared.join('.')}` : '';
  }

  /** A board's icon, eight pixels square: a lock, an arrow, a tick, or a question mark. */
  static gateIcon(kind, x, y) {
    const gold = Look.GOLD;
    if (kind === 'lock') {
      return [Svg.el('rect', { x: x + 2, y, width: 4, height: 1, fill: gold }),
              Svg.el('rect', { x: x + 1, y: y + 1, width: 1, height: 3, fill: gold }),
              Svg.el('rect', { x: x + 6, y: y + 1, width: 1, height: 3, fill: gold }),
              Svg.el('rect', { x, y: y + 4, width: 8, height: 5, fill: gold })];
    }
    if (kind === 'arrow') {
      return [Svg.el('rect', { x, y: y + 3, width: 5, height: 2, fill: Look.PIN }),
              Svg.el('polygon', { points: `${x + 4},${y} ${x + 8},${y + 4} ${x + 4},${y + 8}`, fill: Look.PIN })];
    }
    if (kind === 'open') {
      const green = Look.tone('all');
      return [[0, 4], [2, 6], [4, 4], [6, 2]].map(([dx, dy]) => Svg.el('rect', {
        x: x + dx, y: y + dy, width: 2, height: 2, fill: green }));
    }
    return [Svg.words(x + 4, y + 4, '?', { fill: gold, 'font-size': 10, 'font-weight': 'bold' })];
  }

  /** Whether the flag goes up: something on the board is a way past the router, or not known. */
  gateTrouble(gate) {
    if (gate.missing || gate.stale) return true;
    const { past, unclear } = MapPage.gateParts(gate);
    const wall = gate.firewall || {};
    return Boolean(past.length || unclear.length || wall.missing || wall.on);
  }

  /** Networks, each by its title, with the addresses when only part of a network is meant. */
  whoText(parts) {
    return parts.map((part) => (part.whole ? this.titleOf(part.segment)
      : `${this.titleOf(part.segment)} (${part.space})`)).join(', ');
  }

  /** What the guardhouse says under the pointer: what DSM changes, in a few sentences. */
  aboutGate(gate) {
    if (gate.missing) return `${say(gate.missing)} ${say('gate.about.click')}`;
    const { closed, past, unclear, open } = MapPage.gateParts(gate);
    const words = [say('gate.about')];
    for (const door of closed) words.push(say('gate.about.refuses', { name: door.name, who: this.whoText(door.refuses) }));
    for (const door of past) {
      words.push(say('gate.about.past', { name: door.name, to: this.titleOf(door.beyond), who: this.whoText(door.past) }));
    }
    if (unclear.length) words.push(say('gate.about.unclear', { names: unclear.map((door) => door.name).join(', ') }));
    words.push(say('gate.about.open', { count: open.length }), gate.wall);
    if (gate.stale) words.push(say('gate.stale'));
    words.push(say('gate.about.click'));
    return words.join(' ');
  }

  /** The whole list, in the scroll: every name DSM serves and what it does to who arrives. */
  tellAboutGate() {
    const gate = this.world.gate || { missing: 'gate.no-snapshot', doors: [], firewall: {} };
    const blocks = [Scroll.words(say('gate.intro'))];
    if (gate.missing) {
      blocks.push(Scroll.words(say(gate.missing)));
      this.scroll.put(say('gate.head'), ...blocks);
      return;
    }
    const { closed, past, unclear, open } = MapPage.gateParts(gate);
    const onward = gate.doors.filter((door) => !door.local && !door.past.length);
    const profile = (door) => (door.profile === 'unread' ? say('gate.profile.unread')
      : (door.profile || []).map(([action, source]) => `${action} ${source}`).join(', '));
    const beyond = (door) => (door.beyond ? this.titleOf(door.beyond) : say('gate.outside'));
    const heap = (title, doors, line) => (doors.length
      ? [Scroll.words(say(title), 'quiet'), Scroll.list(doors.map(line))] : []);
    blocks.push(
      ...heap('gate.closed', closed, (door) => say('gate.line.refuses',
        { name: door.name, who: this.whoText(door.refuses), profile: profile(door) })),
      ...heap('gate.past', past, (door) => say('gate.line.past',
        { name: door.name, to: door.to, beyond: beyond(door), who: this.whoText(door.past) })),
      ...heap('gate.onward', onward, (door) => say('gate.line.onward', { name: door.name, to: door.to, beyond: beyond(door) })),
      ...heap('gate.unclear', unclear, (door) => say('gate.line.unclear', { name: door.name,
        why: door.profile === 'unread' ? say('gate.profile.unread')
          : say('gate.why.puzzle', { who: door.unclear.map((key) => this.titleOf(key)).join(', ') }) })),
      Scroll.words(say('gate.open', { count: open.length }), 'quiet'),
      Scroll.words(open.map((door) => door.name).join(', ') || '—'),
      Scroll.words(gate.wall, 'quiet'),
      Scroll.words(`${say('gate.taken', { time: Page.clock(gate.taken) })}${gate.stale ? ` ${say('gate.stale')}` : ''}`,
                   'quiet'));
    this.scroll.put(say('gate.head'), ...blocks);
  }

  /**
   * What DSM on the NAS changes for one network, for the scroll of its yard and of its road: the
   * names that turn it away, and the names that lead it past a road the router keeps shut.
   */
  gateNotes(key) {
    const gate = this.world.gate;
    if (!gate || gate.missing) return [];
    const notes = [];
    for (const door of gate.doors) {
      const refused = door.refuses.find((part) => part.segment === key);
      if (refused) {
        notes.push(say('gate.note.refuses', { name: door.name, who: refused.whole ? say('gate.whole') : refused.space }));
      }
      const past = door.past.find((part) => part.segment === key);
      if (past) {
        notes.push(say('gate.note.past', { name: door.name, beyond: this.titleOf(door.beyond), to: door.to,
                                           who: past.whole ? say('gate.whole') : past.space }));
      }
    }
    return notes;
  }

  //: The signpost by the pier: how wide and tall it stands, and how many letters fit a plank.
  static SIGNPOST = { width: 76, height: 78, letters: 9 };

  /**
   * The signpost on the beach by the pier, where every road out of the network ends. Its
   * planks point at the busiest far ends out in the world — YouTube, Google — the way a
   * signpost names the towns down the road, and it leads to the page that lists them all.
   *
   * The names are the server's, reckoned as that page reckons them. A plank with no name
   * stays blank: when the snapshot holds no connections there is nobody to point at, and a
   * guessed name would be worse than none.
   */
  signpost(at) {
    const { width, height, letters } = MapPage.SIGNPOST;
    const names = this.world.signpost || [];
    const link = this.wayIn({ href: '/houses.html', move: 'signpost', about: say('pier.signpost.about') },
      Svg.el('rect', { x: at.x + width / 2 - 2, y: at.y + 4, width: 5, height: height - 4, fill: Look.DARK }),
      Svg.el('rect', { x: at.x + width / 2 - 4, y: at.y, width: 9, height: 5, fill: Look.DARK }));
    [10, 30, 50].forEach((drop, order) => {
      // Right, left, right: a signpost's planks never all point the same way.
      const right = order % 2 === 0;
      const top = at.y + drop;
      const [back, front] = right ? [at.x + 4, at.x + width - 4] : [at.x + width - 4, at.x + 4];
      const tip = right ? front - 10 : front + 10;
      link.append(Svg.el('polygon', {
        points: `${back},${top} ${tip},${top} ${front},${top + 8} ${tip},${top + 16} ${back},${top + 16}`,
        fill: Look.WOOD, stroke: Look.DARK, 'stroke-width': 2,
      }));
      const name = names[order];
      if (name) {
        link.append(Svg.words((back + tip) / 2, top + 8,
                              name.length > letters ? `${name.slice(0, letters - 1)}…` : name,
                              { fill: Look.GOLD, 'font-size': 10, 'font-weight': 'bold' }));
      }
    });
    return link;
  }

  //: The book by the pier: as wide as its lectern, and as tall from the cover to the feet.
  static BOOK = { width: 64, height: 64 };

  /**
   * An open book on a lectern by the pier: the whole network written down — subnets, devices
   * and who may go where — the very text agents read, /network.md. The desk under the book says
   * "As text", the name this way in had while it was a button in the top bar.
   */
  storyBook(at) {
    const { width, height } = MapPage.BOOK;
    const { x, y } = at;
    // A page and four lines of writing on it: at any size, that is a book open to be read.
    const page = (left) => [
      Svg.el('rect', { x: left, y: y + 4, width: 26, height: 20, fill: Look.BOARD }),
      ...[8, 12, 16, 20].map((down, line) => Svg.el('rect', {
        x: left + 3, y: y + down, width: line % 2 ? 16 : 20, height: 2, fill: Look.STONE })),
    ];
    return this.wayIn({ href: '/network.md', text: true, move: 'story', about: say('pier.story.about') },
      // the legs first: the desk stands on them
      Svg.el('rect', { x: x + 12, y: y + 48, width: 5, height: height - 48, fill: Look.DARK }),
      Svg.el('rect', { x: x + width - 17, y: y + 48, width: 5, height: height - 48, fill: Look.DARK }),
      Svg.el('rect', { x: x + 5, y: y + 32, width: width - 10, height: 18, fill: Look.DARK }),
      Svg.words(x + width / 2, y + 41, say('pier.story'), { fill: Look.GOLD, 'font-size': 10, 'font-weight': 'bold' }),
      // the slanted top the book lies on
      Svg.el('polygon', { points: `${x + 1},${y + 26} ${x + width - 1},${y + 26} ${x + width - 5},${y + 33} ${x + 5},${y + 33}`,
                          fill: Look.WOOD, stroke: Look.DARK, 'stroke-width': 2 }),
      // the cover, open flat, both pages, and the spine down the middle
      Svg.el('rect', { x: x + 1, y: y + 1, width: width - 2, height: 26, fill: Look.DARK }),
      Svg.el('rect', { x: x + 3, y: y + 3, width: width - 6, height: 22, fill: Look.PIN }),
      ...page(x + 5), ...page(x + 33),
      Svg.el('rect', { x: x + 31, y: y + 2, width: 2, height: 24, fill: Look.DARK }),
      // a ribbon keeps the place, hanging over the edge of the desk
      Svg.el('rect', { x: x + 47, y: y + 22, width: 3, height: 12, fill: Look.GOLD }));
  }

  //: The robot by the pier: how wide its plank is, where its post ends, how far down the plank
  //: hangs, and how many times over the robot is drawn — four, to stand out from the houses,
  //: which are drawn twice.
  static GUIDE = { width: 86, height: 86, plank: 40, scale: 4 };

  /**
   * A robot on a post by the pier: where a reading agent starts, /llms.txt — what this map
   * offers, in one short text. The plank says "For agents" and points at the book beside it,
   * the first thing that text sends its reader to. The robot is the map's own picture of one,
   * the same grid a robot of a device is drawn from.
   */
  guidePost(at) {
    const { width, height, plank, scale } = MapPage.GUIDE;
    const { x, y } = at;
    const middle = x + width / 2;
    const top = y + plank;
    return this.wayIn({ href: '/llms.txt', text: true, move: 'guide', about: say('pier.guide.about') },
      Svg.el('rect', { x: middle - 2.5, y: top, width: 5, height: height - plank, fill: Look.DARK }),
      // Left, at the book: an arrow, the way a signpost's planks are.
      Svg.el('polygon', {
        points: `${x + width - 2},${top} ${x + 12},${top} ${x + 2},${top + 9} ${x + 12},${top + 18} ${x + width - 2},${top + 18}`,
        fill: Look.WOOD, stroke: Look.DARK, 'stroke-width': 2,
      }),
      Svg.words(x + (width + 10) / 2, top + 9, say('pier.guide'), { fill: Look.GOLD, 'font-size': 10, 'font-weight': 'bold' }),
      // The grid is 12 by 12 and the robot in it ends ten rows down: from there it stands on
      // the plank.
      this.sprites.node('robot', middle - 6 * scale, top - 10 * scale, scale));
  }

  //: How far the lantern may stray from the middle of the archway, each way.
  static GAZE = { x: 10, y: 7 };
  //: How often the lantern blinks, and how long the blink lasts.
  static BLINK = { every: 5200, lasts: 120 };
  //: The lantern's own size.
  static LANTERN = 8;

  /**
   * The lantern in the archway of the customs house.
   *
   * A dark arch with a light in it reads as an eye at this size, and it was read that way long
   * before anybody decided it should be one. So the map lets it be an eye: the lantern follows
   * whatever is moving on the roads, because every road passes the customs house anyway.
   */
  lantern(at) {
    const size = MapPage.LANTERN;
    const node = Svg.el('rect', { x: at.x - size / 2, y: at.y - size / 2,
                                  width: size, height: size, fill: Look.GOLD });
    this.lamp = { node, at };
    return node;
  }

  /**
   * Where the lantern looks: at the nearest cart, and back to the middle when the roads empty.
   *
   * It drifts rather than jumps — an eye that snapped from cart to cart would look like a
   * fault, not like watching.
   */
  watch(now) {
    if (!this.lamp) return;
    const { node, at } = this.lamp;
    let near = null;
    let best = Infinity;
    for (const cart of this.carts) {
      const gap = Math.hypot(cart.spot.x - at.x, cart.spot.y - at.y);
      if (gap < best) {
        best = gap;
        near = cart.spot;
      }
    }
    const look = near && best > 1
      ? { x: ((near.x - at.x) / best) * MapPage.GAZE.x, y: ((near.y - at.y) / best) * MapPage.GAZE.y }
      : { x: 0, y: 0 };
    this.gaze = this.gaze || { x: 0, y: 0 };
    this.gaze.x += (look.x - this.gaze.x) * 0.1;
    this.gaze.y += (look.y - this.gaze.y) * 0.1;
    const size = MapPage.LANTERN;
    const tall = (now % MapPage.BLINK.every) < MapPage.BLINK.lasts ? 2 : size;
    node.setAttribute('x', (at.x - size / 2 + this.gaze.x).toFixed(1));
    node.setAttribute('y', (at.y - tall / 2 + this.gaze.y).toFixed(1));
    node.setAttribute('height', tall);
  }

  pier(town) {
    const at = this.places.of(this.world.ends.internet);
    const group = Svg.el('g', { class: 'held', 'data-move': this.world.ends.internet });
    const planks = Svg.el('g');
    for (let step = 0; step < 5; step += 1) {
      planks.append(Svg.el('rect', { x: at.x - 30 + step * 13, y: at.y - 18, width: 9, height: 40, fill: '#a0732f' }));
    }
    group.append(planks, this.pierWords());
    group.addEventListener('pointerenter', () => this.hint.show(this.aboutSea()));
    group.addEventListener('pointerleave', () => this.hint.hide());
    group.addEventListener('click', () => this.tellAboutSea());
    return group;
  }

  /** "The internet: way out only", beside the pier: the pier and the fog over it say it alike. */
  pierWords() {
    const at = this.places.of(this.world.ends.internet);
    return Svg.words(at.x + 130, at.y, say('pier.way-out'), { fill: '#eaf2ff', 'font-size': 16 });
  }

  /** A network that appears with the VPN is no castle but a tunnel to the customs house. */
  tunnel(segment, town) {
    const at = { x: town.x - 300, y: Look.FIELD.height - 96 };
    const group = Svg.el('g', { class: 'lane' });
    group.append(
      Svg.el('path', {
        d: `M ${town.x} ${town.y} L ${at.x} ${at.y}`, stroke: Look.DARK, 'stroke-width': 4,
        'stroke-dasharray': '10 8', fill: 'none',
      }),
      Svg.el('rect', { x: at.x - 22, y: at.y - 12, width: 44, height: 24, fill: Look.DARK }),
      Svg.words(at.x, at.y + 36, say('tunnel.title', { title: segment.title }),
                { fill: '#eaf2ff', 'font-size': 16 }),
    );
    group.addEventListener('pointerenter', () => this.hint.show(
      say('tunnel.about', { title: segment.title, network: segment.network })));
    group.addEventListener('pointerleave', () => this.hint.hide());
    group.addEventListener('click', () => this.scroll.castle(
      new Castle(segment, this.world.devices.filter((device) => this.livesIn(device, segment.key)), at),
      this.world, (key) => this.titleOf(key), this.gateNotes(segment.key), this.reachOf({ segment: segment.key })));
    return group;
  }

  /** The set of pictures: a house by default, the rest a human picks themselves. */
  kinds(device) {
    const list = document.createElement('div');
    list.className = 'kinds';
    const pick = (kind, title) => {
      const button = document.createElement('button');
      button.type = 'button';
      const size = this.sprites.sprites.size(kind || 'house');
      const svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('viewBox', `0 0 ${size.width} ${size.height}`);
      svg.setAttribute('width', 18);
      svg.setAttribute('height', 18);
      svg.append(this.sprites.node(kind, 0, 0, 1));
      button.append(svg, document.createTextNode(title));
      if ((device.kind || '') === kind) button.classList.add('on');
      button.addEventListener('click', () => this.remember(device, { kind }));
      return button;
    };
    list.append(pick('', say('kind.plain')),
                ...this.sprites.sprites.kinds.map((kind) => pick(kind, say(`kind.${kind}`))));
    return list;
  }

  async remember(device, fields) {
    try {
      await Api.request('PUT', '/api/device', { device: device.key, ...fields });
    } catch (err) {
      this.warn(say('save.failed', { why: err.message }));
      return;
    }
    await this.load();
    const fresh = this.world.devices.find((one) => one.key === device.key);
    if (fresh) this.describe(fresh, this.eyes === fresh.key ? this.reach(fresh) : null);
  }

  /**
   * The fog, through the eyes of a device or of a whole subnet: dark where it cannot go,
   * striped where it reaches a whole network on some ports only, and dark with windows where
   * it reaches only some machines — those machines show through. What decides is web/sight.js.
   */
  fog() {
    const device = this.eyes ? this.world.devices.find((one) => one.key === this.eyes) : null;
    if (this.eyes && !device) return [];
    const sight = new Sight(this.world, Eyes.words());
    const verdicts = device ? sight.ofDevice(device) : sight.ofSegment(this.watching);
    const covers = [Fog.stripes()];
    for (const castle of this.castles) {
      const verdict = verdicts.get(castle.segment.key);
      covers.push(...this.cover(castle.area(), verdict, castle));
      // A dark network still says which it is: its board is drawn again, above its fog.
      if (!verdict || !['home', 'open'].includes(verdict.state)) {
        covers.push(this.board(castle.place.x, castle.box.y - 34, castle.heading(), castle.segment.colour));
      }
    }
    const pier = this.places.of(this.world.ends.internet);
    const sea = verdicts.get(this.world.ends.internet);
    covers.push(...this.cover({ x: pier.x - 70, y: pier.y - 46, width: 300, height: 92 }, sea, null));
    // The way out still says what it is when it is dark: its words are drawn again, above.
    if (!sea || !['home', 'open'].includes(sea.state)) covers.push(this.pierWords());
    return covers;
  }

  /** One network's cover, by what the onlooker may reach of it. A verdict unknown is dark. */
  cover(area, verdict = { state: 'shut' }, castle) {
    // The fog's words stand under the network, never over its houses: below it, or above it
    // when below there is no more island.
    const middle = (words) => {
      const height = MapPage.boardBox(0, 0, words).height;
      const below = area.y + area.height + 4;
      const y = below + height > Look.FIELD.height - Look.SHORE ? area.y - height - 4 : below;
      return this.board(area.x + area.width / 2, y, words, Look.ROAD_EDGE);
    };
    const covers = {
      home: () => [],
      open: () => [],
      shut: () => [Fog.dark(area, [])],
      ports: () => [Fog.striped(area), middle(say('fog.ports', { ports: verdict.ports.join(', ') }))],
      some: () => [Fog.striped(area), middle(say('fog.some', { who: verdict.members.join(', ') }))],
      hosts: () => {
        const holes = [];
        const signs = [];
        const unseen = [];
        for (const host of verdict.hosts) {
          const row = castle && host.device ? castle.rowOf(host.device) : null;
          if (row) {
            holes.push(row);
            if (host.ports.length) {
              signs.push(this.board(row.x + row.width / 2, row.y + row.height, host.ports.join(', '), Look.ROAD_EDGE));
            }
          } else {
            const who = host.name ? `${host.name} (${host.ip})` : host.ip;
            unseen.push(host.ports.length ? `${who}: ${host.ports.join(', ')}` : who);
          }
        }
        if (unseen.length) signs.push(middle(say('fog.hosts', { hosts: unseen.join('; ') })));
        return [Fog.dark(area, holes), ...signs];
      },
    };
    return (covers[verdict.state] || covers.shut)();
  }

  titleOf(key) {
    const segment = this.world.segments.find((one) => one.key === key);
    if (segment) return segment.title;
    if (key === this.world.ends.internet) return say('end.internet');
    return key === this.world.ends.router ? say('end.router') : key;
  }

  /**
   * What is visible on the canvas. Zoom stretches everything together — castles, roads and
   * carts: this is a map, not a page of text, and magnifying half of it would be odd.
   */
  viewBox() {
    const width = Look.FIELD.width / this.zoom;
    const height = Look.FIELD.height / this.zoom;
    const edge = 120;
    const x = Math.max(-edge, Math.min(Look.FIELD.width + edge - width, this.eye.x - width / 2));
    const y = Math.max(-edge, Math.min(Look.FIELD.height + edge - height, this.eye.y - height / 2));
    return `${x.toFixed(1)} ${y.toFixed(1)} ${width.toFixed(1)} ${height.toFixed(1)}`;
  }

  static ZOOMS = { least: 0.6, most: 4 };

  /** Zoom in or out. The point under the cursor stays under the cursor. */
  scale(times, at) {
    const zoom = Math.max(MapPage.ZOOMS.least, Math.min(MapPage.ZOOMS.most, this.zoom * times));
    if (zoom === this.zoom) return;
    if (at && at.clientX !== undefined) {
      const before = Svg.point(this.map, at);
      const box = this.map.getBoundingClientRect();
      const width = Look.FIELD.width / zoom;
      const height = Look.FIELD.height / zoom;
      this.eye = {
        x: before.x - ((at.clientX - box.left) / box.width - 0.5) * width,
        y: before.y - ((at.clientY - box.top) / box.height - 0.5) * height,
      };
    }
    this.zoom = zoom;
    this.told();
    this.draw();
  }

  /** Back to the whole island: zoom at one, the eye in the middle. */
  whole() {
    this.zoom = 1;
    this.eye = { x: Look.FIELD.width / 2, y: Look.FIELD.height / 2 };
    this.told();
    this.draw();
  }

  told() {
    const said = document.getElementById('zoom');
    if (said) said.textContent = `${Math.round(this.zoom * 100)}%`;
  }

  /**
   * A sign by a road steps aside while the pointer is over it, and comes back when it leaves.
   *
   * Signs live in a layer that takes no pointer events at all — a caption must never eat a
   * click meant for the house beneath it — so being "over" one is worked out from coordinates.
   * `:hover` could not do this anyway: hiding a sign would end the hover that hid it, and it
   * would flicker on and off under a still cursor.
   */
  peek(event) {
    if (!this.signs || !this.signs.length) return;
    const at = event ? Svg.point(this.map, event) : null;
    for (const sign of this.signs) {
      const box = sign.dataset;
      const over = Boolean(at) && at.x >= +box.x && at.x <= +box.x + +box.width
        && at.y >= +box.y && at.y <= +box.y + +box.height;
      sign.classList.toggle('away', over);
    }
  }

  /** Where the cursor landed on the field: the menu opens under it, not in a corner. */
  spot(event) {
    const box = this.field.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  }

  /** Everything about a house is done in the scroll: buttons in one row under the description. */
  tools(device) {
    const seat = device.seats.find((one) => one.online) || device.seats[0];
    const row = document.createElement('div');
    row.className = 'tools';
    const put = (label, run, on) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = label;
      if (on) button.classList.add('on');
      button.addEventListener('click', run);
      row.append(button);
    };
    if (this.eyes === device.key) put(say('tool.clear-fog'), () => {
      this.eyes = '';
      this.watching = '';
      this.draw();
      this.describe(device, null);
    });
    else if (!this.beyondOnly(device)) put(say('tool.where-it-may-go'), () => this.showDevice(device));
    put(say(device.pinned ? 'tool.unpin' : 'tool.pin'),
        () => this.remember(device, { pinned: !device.pinned }), device.pinned);
    put(say(device.hidden ? 'tool.unhide' : 'tool.hide'),
        () => this.remember(device, { hidden: !device.hidden }), device.hidden);
    if (seat) put(say('tool.copy-ip', { ip: seat.ip }), () => this.copy(seat.ip));
    put(say('tool.copy-mac'), () => this.copy(device.key));
    return row;
  }

  castleMenu(castle) {
    const key = castle.segment.key;
    const look = this.look(key);
    return [
      { label: say('menu.rename'), field: { value: castle.segment.title,
                                            run: (title) => this.repaint(key, { title }) } },
      { label: say('menu.colour'), nest: () => this.colours(key) },
      { split: true },
      { label: say(look.folded ? 'menu.unfold' : 'menu.fold'),
        run: () => this.relook(key, { folded: !look.folded }) },
      { label: say('menu.sorting'), nest: () => this.sorts(key) },
      { label: say('menu.columns'), nest: () => this.columns(key) },
    ];
  }

  roadMenu(corridor) {
    const shut = this.world.roads.filter((road) => (road.source === corridor.key
      || road.target === corridor.key) && road.shutBy.length);
    const commands = corridor.ways.flatMap((way) => way.road.openings
      .flatMap((opening) => opening.rules.map((rule) => rule.command))).filter(Boolean);
    return [
      { label: say('menu.show-rules'),
        run: () => this.scroll.roads(corridor, (key) => this.titleOf(key), this.gateNotes(corridor.key)) },
      { label: say('menu.what-shuts-it'), run: () => this.tellAboutShut(corridor, shut) },
      { split: true },
      { label: say('menu.copy-command'),
        run: () => this.copy(commands.length ? commands[0] : '') },
    ];
  }

  townMenu() {
    return [
      { label: say('menu.refresh'), run: () => this.refresh() },
      { label: say('menu.who-reaches-router'), run: () => this.tellAboutRouter() },
      { split: true },
      { label: say('menu.who-sees-map'),
        run: () => document.getElementById('watchers').scrollIntoView() },
    ];
  }

  fieldMenu() {
    return [
      { label: say('tool.clear-fog'), on: Boolean(this.eyes || this.watching), run: () => this.blind() },
      { label: say('menu.access-shown-as'), nest: () => this.shows() },
      { label: say('menu.layers'), nest: () => this.layerList() },
      { split: true },
      { label: say('menu.whole-island'), run: () => this.whole() },
      { label: say('menu.lay-out-again'), run: () => this.spread() },
      { label: say('menu.save-picture'), run: () => this.snapshotPng() },
    ];
  }

  /** A set of buttons for a menu nest: colour, sorting, columns, layers, how access is shown. */
  static buttons(items) {
    const box = document.createElement('div');
    box.className = 'kinds';
    for (const item of items) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = item.label;
      if (item.on) button.classList.add('on');
      button.addEventListener('click', item.run);
      box.append(button);
    }
    return box;
  }

  colours(key) {
    const now = (this.world.segments.find((one) => one.key === key) || {}).colour;
    return MapPage.buttons(Look.PALETTE.map((colour) => ({
      label: colour === now ? `● ${say('menu.now')}` : '●', on: colour === now,
      run: () => this.repaint(key, { colour }),
    })));
  }

  sorts(key) {
    const look = this.look(key);
    return MapPage.buttons(['as-is', 'name', 'address', 'kind'].map((sort) => ({
      label: say(`sort.${sort}`), on: (look.sort || 'as-is') === sort,
      run: () => this.relook(key, { sort }),
    })));
  }

  columns(key) {
    const look = this.look(key);
    return MapPage.buttons([0, 1, 2, 3, 4].map((columns) => ({
      label: columns ? String(columns) : say('menu.columns-auto'), on: (look.columns || 0) === columns,
      run: () => this.relook(key, { columns }),
    })));
  }

  shows() {
    return MapPage.buttons(Look.SHOWS.map((name) => ({
      label: say(`shown.${name}`), on: this.access === name,
      run: () => {
        this.access = name;
        MapPage.remember('access', name);
        this.draw();
      },
    })));
  }

  layerList() {
    return MapPage.buttons(['roads', 'devices', 'notes', 'carts'].map((key) => ({
      label: say(`layer.${key}`), on: this.layers[key],
      run: () => {
        this.layers[key] = !this.layers[key];
        this.draw();
      },
    })));
  }

  /**
   * Carts from the live connections: where someone walks now, a cart rolls.
   *
   * A cart's path is the road of the castle that calls plus the road of the one being called;
   * in between it dives into the customs house and comes out the other side, as it should.
   */
  harness(corridors) {
    const traffic = (this.world.traffic && this.world.traffic.rows) || [];
    const byKey = new Map(corridors.map((corridor) => [corridor.key, corridor]));
    const town = this.world.ends.router;
    const drawn = [];
    for (const row of traffic) {
      // The customs house is not a castle and has no corridor of its own. A cart that talks
      // to the router rides its own castle's road and stops where that road ends — at the
      // customs house itself, which is exactly where the conversation goes.
      const from = row.from === town ? null : byKey.get(row.from);
      const to = row.to === town ? null : byKey.get(row.to);
      if ((row.from !== town && !from) || (row.to !== town && !to)) continue;
      if (!from && !to) continue;
      const path = from && to ? [...from.spine, ...[...to.spine].reverse()]
        : (from ? [...from.spine] : [...to.spine].reverse());
      const length = MapPage.walk(path);
      if (!length) continue;
      // As many carts as named riders: each rides for somebody, not for "traffic in general".
      const riders = row.who || [];
      const many = Math.max(1, Math.min(riders.length || 3, row.count > 19 ? 3 : (row.count > 4 ? 2 : 1)));
      for (let number = 0; number < many; number += 1) {
        const rider = riders[number];
        const device = rider && this.world.devices.find(
          (one) => one.seats.some((seat) => seat.ip === rider.ip));
        const cargo = device ? this.sprites.node(device.kind, -2, -26, 2)
          : (rider && this.isRouter(rider.ip) ? this.sprites.node('router', -2, -26, 2) : null);
        // A cart's colour is the colour of the castle it left: whose train is on the road
        // stays visible even when the rider is a stranger and the cart carries no icon.
        const node = MapPage.cart(this.colourOf(row.from), cargo);
        // The same cart between two draws is the same cart: it is known by its road and its
        // rider, so a redraw does not set a resting cart rolling again.
        const key = `${row.from}>${row.to}#${rider ? rider.ip : number}`;
        // A road that ends at the customs house ends for good: whoever calls the router is
        // talking to him, not through him, and there is nothing beyond the gate to draw.
        this.carts.push({ node, key, path, length, speed: 90,
                          at: (length / many) * number, unloads: !to });
        if (this.held && this.held.key === key) {
          // The mouse is still on this cart; only the node beneath it is new.
          this.held.node = node;
          node.classList.add('watched');
        }
        node.addEventListener('pointerenter', () => {
          // One cart at a time. While the mouse holds one, the rest of the road is not
          // listening: the caption still belongs to the first, and two carts stopped on the
          // same spot hide one another.
          if (this.held) return;
          this.hint.show(this.aboutCart(row, rider, device));
          this.held = { key, node, since: performance.now() };
          node.classList.add('watched');
          this.map.classList.add('watching');
        });
        node.addEventListener('pointerleave', () => {
          if (!this.held || this.held.key !== key) return;
          this.hint.hide();
          this.touched.set(key, performance.now());
          this.release();
        });
        drawn.push(node);
      }
    }
    return drawn;
  }

  /**
   * The colour of whoever set out: a cart wears its castle's canopy.
   *
   * From overseas, and from the customs house, it is plain canvas: neither the sea nor the
   * router belongs to a castle, and borrowing a colour would name the wrong owner.
   */
  colourOf(key) {
    const segment = this.world.segments.find((one) => one.key === key);
    return segment ? segment.colour : '#d9c08a';
  }

  /** Is this one of the router's own addresses? He is no dweller, and no stranger either. */
  isRouter(ip) {
    return this.world.segments.some((segment) => segment.gateway === ip);
  }

  /**
   * What to tell about a cart: who rides, from where and to where. A stranger is an address.
   *
   * When the road starts at the customs house the rider is the router, and the road has said
   * so already — naming him again would only read as "the router rides the router".
   */
  aboutCart(row, rider, device) {
    const road = `${this.titleOf(row.from)} → ${this.titleOf(row.to)}`;
    const head = !rider || this.isRouter(rider.ip)
      ? say('cart.road', { road, count: row.count })
      : (device ? say('cart.rider', { who: device.name || rider.ip, road, count: rider.count })
        : say('cart.stranger', { ip: rider.ip, road, count: rider.count }));
    const load = this.cargo(row, rider);
    return load.length ? [head, say('cart.carries'), ...load].join('\n') : head;
  }

  //: How many doors a caption names. Beyond that it is a list, not a hint.
  static CARGO = 4;

  /**
   * What the cart is carrying: the doors its rider knocks at on the far end of this road.
   *
   * This is what makes a cart to the customs house readable at all — without it one sees a
   * cart arrive at the router and has no way of telling whether that is the DNS being asked,
   * the map reading the tables, or somebody logging in.
   *
   * The road each walk belongs to comes from the router's own sorting, so the page matches
   * keys and does not go guessing castles from addresses.
   */
  cargo(row, rider) {
    if (!rider) return [];
    return this.trips(rider.ip).filter((trip) => trip.where === row.to)
      .slice(0, MapPage.CARGO).map((trip) => this.walk(trip));
  }

  //: Cart colours. One dweller always rides in its own, so it is known from afar.
  static CARTS = ['#b5443a', '#3f6fb5', '#1d9e75', '#f0a020', '#7f77dd', '#d4537e', '#639922', '#c06030'];

  static hue(ip) {
    let sum = 0;
    for (const letter of String(ip)) sum = (sum * 31 + letter.charCodeAt(0)) % 9973;
    return MapPage.CARTS[sum % MapPage.CARTS.length];
  }

  /**
   * The cart is wooden; on it a platform in its castle's colour, and on the platform whoever
   * sent it. It used to carry a nameless heap: that showed the castle's colour but never who
   * was riding.
   *
   * A nameless cargo goes on when the rider is a stranger to the map. An empty platform would
   * read as a fault, whereas a crate reads as "somebody rides, and we do not know who" — which
   * is the truth.
   */
  static crate() {
    const box = Svg.el('g');
    box.append(
      Svg.el('rect', { x: 1, y: -24, width: 18, height: 22, fill: '#8b6b3a' }),
      Svg.el('rect', { x: 3, y: -22, width: 14, height: 18, fill: '#a0732f' }),
      Svg.el('rect', { x: 3, y: -14, width: 14, height: 2, fill: '#8b6b3a' }),
      Svg.el('rect', { x: 9, y: -22, width: 2, height: 18, fill: '#8b6b3a' }),
    );
    return box;
  }

  static cart(colour, cargo) {
    const group = Svg.el('g', { class: 'cart' });
    group.append(cargo || MapPage.crate());  // the rider stands on the platform, not inside
    group.append(
      // The platform grows upwards, not down: the wheels stay on the same spot of the road,
      // while the castle's colour becomes visible from afar.
      Svg.el('rect', { x: 0, y: -2, width: 20, height: 9, fill: colour }),
      Svg.el('rect', { x: 1, y: 7, width: 18, height: 5, fill: '#7a5230' }),
      Svg.el('rect', { x: 3, y: 12, width: 5, height: 5, fill: Look.DARK }),
      Svg.el('rect', { x: 12, y: 12, width: 5, height: 5, fill: Look.DARK }),
      Svg.el('rect', { x: 4, y: 13, width: 3, height: 3, fill: '#c9a063' }),
      Svg.el('rect', { x: 13, y: 13, width: 3, height: 3, fill: '#c9a063' }),
    );
    return group;
  }

  static walk(points) {
    let length = 0;
    for (let step = 0; step + 1 < points.length; step += 1) {
      length += Math.hypot(points[step + 1].x - points[step].x, points[step + 1].y - points[step].y);
    }
    return length;
  }

  static along(points, distance) {
    let left = distance;
    for (let step = 0; step + 1 < points.length; step += 1) {
      const dx = points[step + 1].x - points[step].x;
      const dy = points[step + 1].y - points[step].y;
      const part = Math.hypot(dx, dy);
      if (left <= part) {
        const share = part ? left / part : 0;
        return { x: points[step].x + dx * share, y: points[step].y + dy * share };
      }
      left -= part;
    }
    return points[points.length - 1];
  }

  //: How long a cart stands at the customs gate once its road has ended, and how much of that
  //: it spends fading away. Long enough to see it arrive, short enough not to clutter the gate.
  static UNLOADS = 3000;
  static FADES = 600;
  //: How pale it goes the moment it arrives, and over what stretch of road a fresh one gains
  //: its colour as it rolls out of the castle.
  static PALE = 0.45;
  static SETS_OUT = 40;

  //: How long a cart stands still after the mouse lets it go — long enough to finish the line
  //: one was reading, short enough that the road does not fill up with carts standing about.
  static REST = 10000;
  //: And the longest the mouse may hold one at all. Without this a cart could be held for
  //: good: the pointer leaves the map by a way that sends no word — a window changes, the
  //: page is scrolled away — and the cart stands on the road until it is reloaded.
  static HOLD = 300000;

  /** The mouse lets the cart go: the road starts listening again. */
  release() {
    if (!this.held) return;
    this.held.node.classList.remove('watched');
    this.map.classList.remove('watching');
    this.held = null;
  }

  /** And lets go by itself of one it never left. */
  unhand(now) {
    if (this.held && now - this.held.since >= MapPage.HOLD) this.release();
  }

  /**
   * A cart stands still while the mouse is on it, and for ten seconds after it leaves.
   *
   * Otherwise the caption cannot be read: by the first line the cart has rolled out from
   * under the cursor, the hint goes dark, and one is left chasing it down the road.
   */
  resting(cart, now) {
    // One that has begun to fade at the gate is past holding: stopping it there would leave a
    // ghost standing on the road for the whole ten seconds.
    if (cart.waits !== undefined && cart.waits <= MapPage.FADES) return false;
    if (this.held && this.held.key === cart.key) return true;
    const left = this.touched.get(cart.key);
    return left !== undefined && now - left < MapPage.REST;
  }

  /**
   * One cart, one frame.
   *
   * A cart whose road ends at the customs house has nowhere to go on: it arrives, stands pale
   * at the gate while the goods change hands, fades out, and another sets out from the castle.
   * Before, it winked out at the gate and was back at its castle in the same frame, which read
   * as the map losing carts rather than as a journey that ends there.
   */
  nudge(cart, now, step) {
    if (this.resting(cart, now)) return;
    if (cart.waits !== undefined) {
      // The wait runs down only while nobody holds the cart: its caption is still being read.
      cart.waits -= step;
      if (cart.waits <= 0) {
        cart.waits = undefined;
        cart.at = 0;
      }
      return;
    }
    cart.at += (cart.speed * step) / 1000;
    if (cart.at < cart.length) return;
    if (!cart.unloads) {
      cart.at %= cart.length;
    } else {
      cart.at = cart.length;
      cart.waits = MapPage.UNLOADS;
    }
  }

  /**
   * How solid a cart looks: it gains its colour leaving the castle, and at the customs gate it
   * stands pale and then fades away altogether. One that rides through keeps its colour: it is
   * only the end of a road that is worth showing as an end.
   */
  static paleness(cart) {
    if (cart.waits !== undefined) return MapPage.PALE * Math.min(1, cart.waits / MapPage.FADES);
    if (!cart.unloads) return 1;
    return Math.min(1, cart.at / MapPage.SETS_OUT);
  }

  roll() {
    const now = performance.now();
    const step = Math.min(80, now - (this.rolled || now));
    this.rolled = now;
    this.unhand(now);
    for (const cart of this.carts) {
      this.nudge(cart, now, step);
      // Where the cart is now is kept on the cart: the lantern needs it too, and working it
      // out a second time would be the same answer at twice the price.
      cart.spot = MapPage.along(cart.path, cart.at);
      cart.node.setAttribute('transform', `translate(${cart.spot.x - 10} ${cart.spot.y - 8})`);
      const pale = MapPage.paleness(cart);
      if (pale !== cart.pale) {
        cart.pale = pale;
        cart.node.setAttribute('opacity', pale.toFixed(2));
      }
    }
    this.watch(now);
    if (this.carts.length) this.rolling = requestAnimationFrame(() => this.roll());
  }

  /**
   * One device, several yards: point at it in one and it lights up in all of them.
   *
   * That is the whole of "these are the same device" said without a word, and it has to be
   * said — two identical houses in two yards read as two devices otherwise.
   */
  together(key, lit) {
    for (const node of this.map.querySelectorAll(`[data-device="${CSS.escape(key)}"]`)) {
      node.classList.toggle('lit', lit);
    }
  }

  /** Pinned houses are drawn over the fog: they are the ones being watched. */
  pinned() {
    const kept = this.world.devices.filter((device) => device.pinned && !device.hidden);
    if (!kept.length) return [];
    const group = Svg.el('g');
    for (const castle of this.castles) {
      const mine = kept.filter((device) => this.livesIn(device, castle.segment.key));
      if (!mine.length) continue;
      const seen = new Castle(castle.segment, mine, castle.place, { ...castle.look, folded: false });
      seen.devices = mine;
      group.append(seen.houses(this));
    }
    return [group];
  }

  static LINE = 19;
  static MOST = 34;

  /** A long caption is cut between words: two lines beat an ellipsis. */
  static wrap(words) {
    const lines = [];
    let line = '';
    for (const word of String(words).split(' ')) {
      if (line && `${line} ${word}`.length > MapPage.MOST) {
        lines.push(line);
        line = word;
      } else {
        line = line ? `${line} ${word}` : word;
      }
    }
    if (line) lines.push(line);
    return lines;
  }

  /** Where a board with these words stands: the board and whatever must cover it measure alike. */
  static boardBox(x, y, words) {
    const lines = MapPage.wrap(words);
    const width = Math.max(...lines.map((line) => line.length)) * 8.6 + 22;
    const height = lines.length * MapPage.LINE + 8;
    // A sign does not drift off the island's edge: it still has to be read.
    const middle = Math.max(width / 2 + 10, Math.min(Look.FIELD.width - width / 2 - 10, x));
    return { x: middle - width / 2, y, width, height, middle, lines };
  }

  board(x, y, words, colour) {
    const box = MapPage.boardBox(x, y, words);
    // The board remembers its own box. A sign by a road hides when the pointer comes over it,
    // and that is worked out from these numbers rather than from getBBox on every mouse move.
    return Svg.el('g', { class: 'sign', 'data-x': box.x, 'data-y': y,
                         'data-width': box.width, 'data-height': box.height },
      Svg.el('rect', { x: box.x, y, width: box.width, height: box.height, fill: Look.BOARD,
                       stroke: colour, 'stroke-width': 3, rx: 3 }),
      ...box.lines.map((line, order) => Svg.words(box.middle, y + 13 + order * MapPage.LINE, line,
                                                  { fill: Look.INK, 'font-size': 15 })));
  }

  // --- what the map says -------------------------------------------------------------------------
  aboutCastleRoads(corridor) {
    // Each direction on its own line: on one line this cannot be read at all.
    const rows = corridor.ways.map((way) => {
      const road = way.road;
      const where = say(way.way === 'out' ? 'road.to' : 'road.from',
                        { title: this.titleOf(way.way === 'out' ? road.target : road.source) });
      const only = road.only ? ` ${say('road.only', { name: road.only })}` : '';
      const why = road.byDefault ? `, ${say('road.no-rule')}` : '';
      const moss = road.dead ? `, ${say('road.never-used')}` : '';
      return `${where}: ${say(`road.width.${road.width}`)}${only}${why}${moss}`;
    });
    return [say('road.of', { title: corridor.title }), ...rows].join('\n');
  }

  aboutDevice(device) {
    const where = device.seats.map((seat) => `${seat.ip} — ${this.titleOf(seat.segment)}`).join('\n');
    const kind = device.kind ? say(`kind.${device.kind}`) : '';
    return [(device.name || say('device.nameless'))
              + (device.online ? '' : ` — ${say('device.offline')}`), kind, where]
      .filter(Boolean).join('\n');
  }

  /** The pier says what it is and where the rest is told: each network's own lines of access. */
  aboutSea() {
    return [say('pier.head'), say('pier.see-access')].join('\n');
  }

  tellAboutSea() {
    this.scroll.put(say('scroll.title'), Scroll.words(say('pier.head')), Scroll.words(say('pier.see-access'), 'quiet'));
  }

  tellAboutRouter() {
    const roads = this.world.roads.filter((road) => road.target === this.world.ends.router);
    this.scroll.put(say('scroll.title'), Scroll.words(say('town.head')), Scroll.list(roads.map(
      (road) => `${this.titleOf(road.source)}: ${say(`road.width.${road.width}`)}`
        + `${road.signs.length ? ` — ${road.signs.join(', ')}` : ''}`)));
  }

  /**
   * A click on a house is "through its eyes": the fog at once, the list of roads at once.
   * That is what a map leads one to expect: poke a dweller and see where it goes.
   */
  showDevice(device) {
    // A dweller of the yard beyond the gate has no eyes the map could lend: what it may reach is
    // decided by a router that is not ours.
    const beyond = this.beyondOnly(device);
    this.eyes = beyond ? '' : device.key;
    this.watching = '';
    this.draw();
    this.describe(device, beyond ? null : this.reach(device));
  }

  /** Whether a device lives only in the yard beyond the gate. */
  beyondOnly(device) {
    const outside = new Set(this.world.segments.filter((one) => one.outside).map((one) => one.key));
    return device.homes.length > 0 && device.homes.every((home) => outside.has(home));
  }

  /**
   * A click on a subnet's heading or its fence is the same, through the eyes of the whole
   * subnet: what none of its devices may reach goes dark, and its road signs come out.
   */
  showSegment(key) {
    // The yard beyond the gate is looked at, not looked through: its rules are not ours.
    const castle = this.castles.find((one) => one.segment.key === key);
    const beyond = Boolean(castle && castle.segment.outside);
    this.watching = beyond ? '' : key;
    this.eyes = '';
    this.draw();
    if (castle) {
      this.scroll.castle(castle, this.world, (one) => this.titleOf(one), this.gateNotes(key),
                         beyond ? [] : this.reachOf({ segment: key }));
    }
  }

  /** The scroll about a dweller and a knock at once: a click means "show all you know". */
  describe(device, reach) {
    this.shown = device.key;
    this.scroll.device(device, this, reach);
    // Beyond the gate is not our network: the map does not knock at doors there.
    if (!this.beyondOnly(device)) this.knock(device);
  }

  /**
   * Where a dweller walks right now — by the live connections the router holds.
   * A neighbour is called by name, a stranger's address by its address: names are not invented.
   */
  walks(device) {
    return device.seats.flatMap((seat) => this.trips(seat.ip).map((walk) => this.walk(walk)));
  }

  /** Where one address walks right now. Only our own dwellers are counted this way. */
  trips(ip) {
    return ((this.world.traffic && this.world.traffic.trips) || {})[ip] || [];
  }

  /** One walk in words: to whom, at which door, and how many at once. */
  walk(trip) {
    const port = trip.port ? `:${trip.port}` : '';
    // The protocol is named only when it is not tcp: otherwise one address over tcp and
    // over udp looks like a twin line, and it is unclear why there are two.
    const how = trip.protocol && trip.protocol !== 'tcp' ? ` ${trip.protocol}` : '';
    const about = trip.about ? ` — ${say(trip.about)}` : '';
    const many = trip.count > 1 ? say('walk.count', { count: trip.count }) : '';
    return `${this.whose(trip)}${port}${how}${about}${many}`;
  }

  /**
   * Who is at the far end of a walk, best answer first — and nothing is looked up here, all
   * four were in the snapshot already.
   *
   * A dweller is named by the map. Beyond the sea, a house known by name beats the name it
   * was read from — "YouTube" is the answer, `rr2.sn-h5bupjvh-ucnr.googlevideo.com` is only
   * where the answer came from. A bare name beats a house guessed from the address, because
   * the name is a fact and the block is a guess; and the guess, when it is all there is, says
   * plainly that it is one.
   *
   * A remembered name sits between the two. The router gave it to this very address, which
   * the block never did; but he gave it before, and the address may have moved on since. So
   * it outranks the block and still says where it came from.
   */
  whose(trip) {
    const known = this.world.devices.find((one) => one.seats.some((s) => s.ip === trip.to));
    if (known && known.name) return `${known.name} (${trip.to})`;
    if (trip.house && trip.by === 'name') return `${trip.house} (${trip.to})`;
    if (trip.remembered) {
      const who = trip.by === 'memory' ? trip.house : trip.name;
      return say('walk.remembered', { who, ip: trip.to });
    }
    if (trip.name) return `${trip.name} (${trip.to})`;
    if (trip.house) return say('walk.somewhere-in', { who: trip.house, ip: trip.to });
    return trip.to;
  }

  /**
   * Knock at a dweller's doors. The answer stays in the page's memory: one may come back to a
   * house as often as one likes, while a knock is a deed in the network, repeated by button.
   */
  async knock(device, again) {
    const seat = device.seats.find((one) => one.online) || device.seats[0];
    if (!seat) return;
    const repeat = document.createElement('button');
    repeat.type = 'button';
    repeat.textContent = say('doors.knock-again');
    repeat.addEventListener('click', () => this.knock(device, true));
    const kept = this.doors.get(device.key);
    if (kept && !again) {
      this.scroll.doors(kept, repeat);
      return;
    }
    if (again) this.scroll.doors({ open: [], knocked: 0, took: 0, ip: seat.ip, from: '' }, null);
    let answer;
    try {
      answer = await Api.request('POST', '/api/ports', { ip: seat.ip });
      this.doors.set(device.key, answer);
    } catch (err) {
      answer = { error: say('doors.failed', { why: err.message }) };
    }
    if (this.shown === device.key) this.scroll.doors(answer, answer.error ? null : repeat);
  }

  /**
   * Everywhere a device may and may not go: three answers, because one list answers badly.
   *
   * "Where it may go" alone leaves the reader counting subnets on their fingers to work out
   * what is missing, and that is the half people actually came to check. And a road that
   * leads to one named house is not a way into that subnet at all — it is a way to that one
   * house — so it stands apart rather than reading as "this subnet is open".
   *
   * "Only the router" on the road to the router itself is no exception, and no news either.
   */
  reach(device) {
    return this.reachOf({ device });
  }

  /**
   * Where a device, or a whole subnet, may go, line by line: the internet first, then the
   * networks by their numbers. A line is a mark and the place, and its exceptions; the networks
   * are judged as the fog judges them, by web/sight.js.
   *
   * The router has no line of its own: its address in the onlooker's network is one of that
   * network's addresses, so it stands inside that network's line — as an exception, when it is
   * not as open as the rest of the network. A device on no network the map knows keeps the
   * router on a line of its own.
   */
  reachOf({ device = null, segment = '' }) {
    const homes = device ? device.homes : [segment];
    const sight = new Sight(this.world, Eyes.words());
    const verdicts = device ? sight.ofDevice(device) : sight.ofSegment(segment);
    const { internet, router } = this.world.ends;
    const line = (key, at) => this.reachLine(key === router ? null : verdicts.get(key), this.way(sight, key, device, segment),
                                             this.closers(key, device, segment), this.placeOf(key, at), this.addressOf(key, at),
                                             key === router ? 'router' : '');
    const number = (one) => (Sight.range(one.network) || [Infinity])[0];
    const networks = [...this.world.segments].sort((a, b) => number(a) - number(b));
    const lines = networks.map((one) => {
      const own = line(one.key, homes);
      if (!homes.includes(one.key)) return own;
      const gate = line(router, [one.key]);
      if (gate.mark === 'open') return own;
      return { ...own, mark: own.mark === 'home' ? 'home-most' : own.mark, but: [...(own.but || []), gate] };
    });
    const housed = networks.some((one) => homes.includes(one.key));
    return [line(internet, homes), ...(housed ? [] : [line(router, homes)]), ...lines];
  }

  /** The rules that shut the way toward a place, as the mark of its line names them. */
  closers(target, device, segment) {
    const homes = new Set(device ? device.homes : [segment]);
    return this.ruleNames(this.world.roads.filter((road) => homes.has(road.source) && road.target === target)
      .flatMap((road) => road.shutBy || []));
  }

  /**
   * Rules by their names, as the router keeps them: «between networks, everything else — no»
   * says why a network is dark. One name for several rules is said once, with how many there
   * are. Nothing when there are no rules.
   */
  ruleNames(rules) {
    const seen = new Set();
    const names = new Map();
    for (const rule of rules) {
      if (seen.has(rule.id)) continue;
      seen.add(rule.id);
      const name = rule.comment ? `«${rule.comment}»` : say('rule.nameless', { id: rule.id });
      names.set(name, (names.get(name) || 0) + 1);
    }
    if (!seen.size) return '';
    const list = [...names].map(([name, count]) => (count > 1 ? `${name} ×${count}` : name)).join(', ');
    return say(seen.size > 1 ? 'reach.rules' : 'reach.rule', { rules: list });
  }

  /**
   * A place as a line of access names it: a network by its addresses and its name, the router
   * by its addresses in the onlooker's own networks, the internet by its name alone.
   */
  placeOf(key, homes) {
    const segment = this.world.segments.find((one) => one.key === key);
    const name = segment ? segment.title : this.titleOf(key);
    const address = this.addressOf(key, homes);
    return address ? `${address} / ${name}` : name;
  }

  /**
   * A place's addresses as a line of access writes them: a network's ("192.168.10.x"), the
   * router's in the onlooker's own networks. The internet has none: "".
   */
  addressOf(key, homes) {
    const segment = this.world.segments.find((one) => one.key === key);
    if (segment) return Castle.shortNet(segment.network);
    if (key !== this.world.ends.router) return '';
    const gates = homes.map((home) => (this.world.segments.find((one) => one.key === home) || {}).gateway)
      .filter(Boolean);
    return [...new Set(gates)].join(', ');
  }

  /**
   * The road toward a place as the onlooker travels it: its width, the ports of the openings
   * that are the onlooker's, and what a "most" leaves out, piece by piece with the rules that
   * shut each. None when there is no such road.
   */
  way(sight, target, device, segment) {
    let found;
    if (device) {
      found = sight.deviceRoads(device).find(({ road }) => road.target === target);
    } else {
      const road = this.world.roads.find((one) => one.source === segment && one.target === target && one.width !== 'shut');
      const home = this.world.segments.find((one) => one.key === segment);
      const range = home ? Sight.range(home.network) : null;
      const everyone = road ? road.openings.filter((opening) => !range || Sight.covers(opening.from, range[0], range[1])) : [];
      found = everyone.length ? { road, openings: everyone } : null;
    }
    if (!found) return null;
    return { width: found.road.width, shut: found.road.shutParts || [],
             ports: Sight.byPort([...new Set(found.openings.map((opening) => sight.label(opening)))]) };
  }

  /**
   * A place's line of access, and its exceptions: of a place open but for some addresses, those
   * addresses, shut; of a place shut but for some addresses or ports, those, open — each an
   * address, or an address and a port, with the machine's name when the map knows it; of a
   * network open only for some devices of the subnet, those devices. The verdict is the
   * network's, or for the router itself the road's width; `where` is the place's own addresses.
   *
   * A line of an address, or of an address and a port, carries what a human wrote down about
   * it: what sits there and why it is open. `spot` is what such a note is kept under — the
   * router's lines are "router" in every network, whichever of its addresses they show.
   */
  reachLine(verdict, way, closers, title, where, spot = '') {
    const place = spot || where;
    const pieces = way && way.width === 'most'
      ? way.shut.map((piece) => ({ title: piece.where, mark: 'shut', rules: this.ruleNames(piece.by) })) : [];
    const open = () => (pieces.length ? { title, mark: 'most', but: pieces } : { title, mark: 'open' });
    const shut = () => ({ title, mark: 'shut', rules: closers });
    const only = (but) => ({ title, mark: 'only', rules: closers, but });
    const at = (address, port, name) => `${[address, port].filter(Boolean).join(' ')}${name ? ` / ${name}` : ''}`;
    const ports = (labels, address, name, kept = address) => labels.map((label) => ({
      title: at(address, label, name), mark: 'port', note: this.note(kept, label) }));
    // What a reach opens of the network, line by line: the whole of it, ports of it, machines in it.
    const opened = (reach) => ({
      open: () => [{ title: where, mark: 'open', note: this.note(place) }],
      ports: () => ports(reach.ports, where, '', place),
      hosts: () => reach.hosts.flatMap((host) => (host.ports.length ? ports(host.ports, host.ip, host.name)
        : [{ title: at(host.ip, '', host.name), mark: 'open', note: this.note(host.ip) }])),
    }[reach.state] || (() => []))();
    // A few devices of the subnet have their own: each under its name.
    const theirs = (verdict && verdict.others || []).map((one) => ({
      label: `${say('reach.for-whom', { who: one.name })}:`, lines: opened(one.verdict) }));
    if (!verdict) {
      if (!way || way.width === 'shut') return shut();
      return way.width === 'ports' ? only(ports(way.ports, where, '', place)) : open();
    }
    const lines = {
      home: () => ({ title, mark: 'home' }),
      open,
      ports: () => only([...opened(verdict), ...theirs]),
      hosts: () => only([...opened(verdict), ...theirs]),
      some: () => only(theirs),
      shut,
    };
    return (lines[verdict.state] || shut)();
  }

  /**
   * What a human wrote down about a line of access, "Vaultwarden" or "DNS of the router": the key
   * it is kept under — the place, and the protocol and ports when there are any — the words, and
   * a way to change them when the map may be changed from here. None for a line with no place.
   */
  note(spot, label = '') {
    if (!spot) return null;
    const key = [spot, label].filter(Boolean).join(' ');
    return { key, text: (this.world.ports || {})[key] || '',
             save: this.world.move.allowed ? (text) => this.notePort(key, text) : null };
  }

  /**
   * Writes down what a line of access is for; an empty note takes it away. The words as the map
   * kept them, or null when it did not keep them — the reason is said above the page.
   */
  async notePort(key, text) {
    let answer;
    try {
      answer = await Api.request('PUT', '/api/port', { key, note: text });
    } catch (err) {
      this.warn(say('save.failed', { why: err.message }));
      return null;
    }
    this.warn('');
    const ports = { ...(this.world.ports || {}) };
    if (answer.note) ports[answer.key] = answer.note;
    else delete ports[answer.key];
    this.world.ports = ports;
    return answer.note;
  }

  /** One line of "where it may go": the castle, how wide, and what narrows it. */
  step(step) {
    const ports = step.ports.length ? `: ${step.ports.join(', ')}` : '';
    const only = step.only && step.target !== this.world.ends.router
      ? ` ${say('road.only', { name: step.only })}` : '';
    const shut = step.shutTo ? ` ${step.shutTo}` : '';
    return `${say('road.to', { title: this.titleOf(step.target) })}: `
      + `${say(`road.width.${step.width}`)}${shut}${only}${ports}`;
  }

  /** A device's name: the router does not know it, a human does. */
  naming(device) {
    const row = document.createElement('div');
    row.className = 'naming';
    const field = document.createElement('input');
    field.type = 'text';
    field.value = device.name || '';
    field.maxLength = 48;
    field.placeholder = say('device.name.hint');
    const save = document.createElement('button');
    save.type = 'button';
    save.textContent = say('save');
    const send = () => this.remember(device, { name: field.value.trim() });
    save.addEventListener('click', send);
    field.addEventListener('keydown', (event) => { if (event.key === 'Enter') send(); });
    row.append(field, save);
    return row;
  }

  tellAboutEyes() {
    const device = this.world.devices.find((one) => one.key === this.eyes);
    if (!device) {
      this.scroll.put(say('scroll.title'), Scroll.words(say('fog.none'), 'quiet'));
      return;
    }
    const steps = new Eyes(this.world).where(device);
    const seen = new Set(steps.map((step) => step.target));
    // "only the router" on the road to the router itself is no news, so it is left unsaid.
    const rows = steps.filter((step) => step.width !== 'home').map((step) => this.step(step));
    const hidden = [...this.castles.map((castle) => castle.segment.key), this.world.ends.internet]
      .filter((key) => !seen.has(key)).map((key) => this.titleOf(key));
    this.scroll.put(say('scroll.title'),
      Scroll.words(say('fog.eyes', { who: device.name || device.seats[0].ip })),
      Scroll.list([
        say('fog.home', { where: device.homes.map((key) => this.titleOf(key)).join(', ') }),
        ...rows,
        say('fog.hidden', { where: hidden.join(', ') || say('fog.nothing') })]));
  }

  journal() {
    const kinds = new Map();
    for (const finding of this.world.findings) {
      if (!kinds.has(finding.kind)) kinds.set(finding.kind, []);
      kinds.get(finding.kind).push(finding);
    }
    const chips = document.getElementById('findings');
    const changed = this.world.changes && this.world.changes.lines.length
      ? [this.changeChip(this.world.changes)] : [];
    chips.replaceChildren(...changed, ...[...kinds].map(([kind, found]) => {
      const chip = document.createElement('li');
      chip.textContent = `${say(`find.kind.${kind}`)} · ${found.length}`;
      chip.addEventListener('click', () => this.tellAboutFindings(kind, found));
      return chip;
    }));
    const notes = document.getElementById('notes');
    const said = [...this.world.notes];
    if (this.world.traffic && this.world.traffic.missing) said.push(this.world.traffic.missing);
    notes.replaceChildren(...said.map((note) => {
      const line = document.createElement('li');
      line.textContent = note;
      return line;
    }));
  }

  /** What changed since the last snapshot: a chip of its own, because it is the day's news. */
  changeChip(changes) {
    const chip = document.createElement('li');
    chip.textContent = say('changed.chip', { count: changes.lines.length });
    chip.addEventListener('click', () => this.scroll.put(say('scroll.title'),
      Scroll.words(say('changed.head', { clock: changes.before.slice(11, 16) })),
      Scroll.list(changes.lines)));
    return chip;
  }

  /**
   * Findings of one kind in the scroll. For rules a ready line for the router is shown —
   * a human will run it: the map never changes the network.
   */
  tellAboutFindings(kind, found) {
    const blocks = [Scroll.words(say('findings.head', { kind: say(`find.kind.${kind}`) }))];
    const rows = [];
    for (const finding of found) {
      rows.push(finding.text);
      for (const rule of finding.rules) {
        rows.push('  ' + say('rule.line', { index: rule.index, packets: rule.packets,
                                            comment: rule.comment || say('change.uncaptioned') }));
        if (rule.command) rows.push(`  ${rule.command}`);
      }
    }
    blocks.push(Scroll.list(rows));
    if (kind === 'dead-rule') blocks.push(Scroll.words(say('findings.defconf'), 'quiet'));
    this.scroll.put(say('scroll.title'), ...blocks);
  }

  /**
   * The "who sees the map" tick boxes. A setting of the map, not of the network: the router
   * is untouched. One's own network cannot be unticked — nobody would be left to tick it back.
   */
  async watchers() {
    const box = document.getElementById('watchers');
    if (!this.world.move.allowed) {
      box.hidden = true;
      return;
    }
    let settings;
    try {
      settings = await Api.request('GET', '/api/settings');
    } catch (err) {
      box.hidden = true;
      return;
    }
    const shown = new Set(settings.show);
    const rows = this.world.segments.filter((segment) => !segment.outside).map((segment) => {
      const label = document.createElement('label');
      const tick = document.createElement('input');
      tick.type = 'checkbox';
      tick.value = segment.network;
      tick.checked = shown.has(segment.network);
      label.append(tick, document.createTextNode(` ${segment.title} (${segment.network})`));
      return label;
    });
    const save = document.createElement('button');
    save.type = 'button';
    save.textContent = say('save');
    save.addEventListener('click', async () => {
      const show = rows.map((row) => row.firstChild).filter((tick) => tick.checked)
        .map((tick) => tick.value);
      try {
        await Api.request('PUT', '/api/settings', { show });
        this.warn('');
      } catch (err) {
        this.warn(err.message);
      }
    });
    const title = document.createElement('p');
    title.className = 'quiet';
    title.textContent = say('watchers.title');
    box.replaceChildren(title, ...rows, save);
    box.hidden = false;
  }

  // --- deeds from the menu -----------------------------------------------------------------------
  look(key) {
    return (this.places && this.places.looks[key]) || {};
  }

  async relook(key, fields) {
    this.places.looks[key] = { ...this.look(key), ...fields };
    this.draw();
    await this.keepLayout();
  }

  async repaint(key, fields) {
    try {
      await Api.request('PUT', '/api/segment', { segment: key, ...fields });
    } catch (err) {
      this.warn(say('save.failed', { why: err.message }));
      return;
    }
    await this.load();
  }

  async copy(text) {
    if (!text) {
      this.warn(say('copy.nothing'));
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      this.warn(say('copy.done', { text: text.length > 60 ? `${text.slice(0, 57)}…` : text }));
    } catch (err) {
      this.warn(say('copy.failed', { text }));
    }
  }

  blind() {
    this.eyes = '';
    this.watching = '';
    this.draw();
  }

  //: A shift smaller than this is a click, not a drag: finger and mouse always tremble a little.
  static STILL = 3;

  stayed(panning) {
    return Math.abs(this.eye.x - panning.eye.x) < MapPage.STILL
      && Math.abs(this.eye.y - panning.eye.y) < MapPage.STILL;
  }

  /** A click on empty grass: the choice is dropped, the fog lifted, the scroll waits again. */
  forget() {
    if (!this.eyes && !this.watching && !this.found.size && !this.shown) return;
    this.eyes = '';
    this.watching = '';
    this.shown = '';
    this.found = new Set();
    this.draw();
    this.scroll.put(say('scroll.title'), Scroll.words(say('scroll.hint'), 'quiet'));
  }

  /** Lay out again: the layout is wiped, and the map works the places out for itself. */
  async spread() {
    this.places.places = {};
    this.draw();
    await this.keepLayout();
  }

  async keepLayout() {
    try {
      await Api.request('PUT', '/api/layout', this.places.payload());
      this.warn('');
    } catch (err) {
      this.warn(say('layout.not-saved', { why: err.message }));
    }
  }

  tellAboutShut(corridor, shut) {
    if (!shut.length) {
      this.scroll.put(say('scroll.title'),
                      Scroll.words(say('shut.nobody', { title: corridor.title }), 'quiet'));
      return;
    }
    const rows = [];
    for (const road of shut) {
      rows.push(`${this.titleOf(road.source)} → ${this.titleOf(road.target)}: ${say('road.width.shut')}`);
      for (const rule of road.shutBy) {
        rows.push('  ' + say('rule.line', { index: rule.index, packets: rule.packets,
                                            comment: rule.comment || say('change.uncaptioned') }));
      }
    }
    this.scroll.put(say('scroll.title'), Scroll.words(say('shut.head')), Scroll.list(rows));
  }

  /** The map as a picture: what is on the screen, only as a file. */
  async snapshotPng() {
    const copy = this.map.cloneNode(true);
    copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    const text = new XMLSerializer().serializeToString(copy);
    const image = new Image();
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(text)}`;
    try {
      await image.decode();
    } catch (err) {
      this.warn(say('picture.failed'));
      return;
    }
    const canvas = document.createElement('canvas');
    canvas.width = Look.FIELD.width * 2;
    canvas.height = Look.FIELD.height * 2;
    canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
    const link = document.createElement('a');
    link.download = `${say('picture.file')}-${this.world.taken.slice(0, 16).replace(':', '-')}.png`;
    link.href = canvas.toDataURL('image/png');
    link.click();
  }

  // --- search, hot keys, the shelf of snapshots ---------------------------------------------------
  /** Search by name, address and MAC: the houses found are framed in gold. */
  seek(text) {
    const asked = text.trim().toLowerCase();
    this.found = new Set();
    if (asked) {
      for (const device of this.world.devices) {
        const where = [device.name, device.key, device.kind,
                       ...device.seats.map((seat) => seat.ip)].join(' ').toLowerCase();
        if (where.includes(asked)) this.found.add(device.key);
      }
    }
    this.draw();
    if (!asked) return;
    const names = this.world.devices.filter((device) => this.found.has(device.key))
      .map((device) => `${Castle.label(device)} — ${device.seats.map((seat) => seat.ip).join(', ')}`);
    this.scroll.put(say('scroll.title'), Scroll.words(say('seek.found', { count: names.length })),
                    Scroll.list(names.length ? names : [say('seek.nobody')]));
  }

  keys(event) {
    if (event.target.tagName === 'INPUT') {
      if (event.key === 'Escape') event.target.blur();
      return;
    }
    if (event.key === 'Escape') { this.menu.hide(); this.blind(); }
    // The Cyrillic letters sit on the same keys: a hot key should not depend on the layout.
    if (event.key === 'r' || event.key === 'к') this.refresh();
    if (event.key === 'f' || event.key === 'а') {
      event.preventDefault();
      document.getElementById('seek').focus();
    }
    if (event.key === '+' || event.key === '=') this.scale(1.2);
    if (event.key === '-') this.scale(1 / 1.2);
    if (event.key === '0') this.whole();
    const number = Number(event.key);
    if (number >= 1 && number <= Look.SHOWS.length) {
      this.access = Look.SHOWS[number - 1];
      MapPage.remember('access', this.access);
      this.draw();
    }
  }

  /** The banner of news: what changed since the last snapshot, so nobody has to go looking. */
  banner() {
    const news = document.getElementById('news');
    const changes = this.world.changes;
    if (!changes || !changes.lines.length || this.at) {
      news.hidden = true;
      return;
    }
    // Every change, not the first three: what is left out of sight is as good as not said.
    news.textContent = say('news.since', { clock: changes.before.slice(11, 16), what: changes.lines.join('; ') });
    news.hidden = false;
    news.onclick = () => this.scroll.put(say('scroll.title'),
      Scroll.words(say('changed.head', { clock: changes.before.slice(11, 16) })),
      Scroll.list(changes.lines));
  }

  /** The shelf of snapshots: one may look at how yesterday was. */
  async shelf() {
    const select = document.getElementById('shelf');
    let kept = [];
    try {
      kept = (await Api.request('GET', '/api/history')).kept;
    } catch (err) {
      kept = [];
    }
    const now = document.createElement('option');
    now.value = '';
    now.textContent = say('shelf.now');
    select.replaceChildren(now, ...kept.map((one) => {
      const option = document.createElement('option');
      option.value = one.name;
      option.textContent = one.taken.slice(5, 16).replace('T', ' ');
      return option;
    }));
    select.value = this.at;
    select.hidden = kept.length < 2;
  }

  // --- things are moved with a mouse -------------------------------------------------------------
  watchPointer() {
    this.map.addEventListener('pointermove', (event) => this.peek(event));
    this.map.addEventListener('pointerleave', () => this.peek(null));
    this.map.addEventListener('pointerdown', (event) => {
      const grip = event.target.closest('[data-grip]');
      if (grip && event.button === 0) {
        this.sizing = { from: Svg.point(this.map, event), was: { ...Look.FIELD } };
        this.map.setPointerCapture(event.pointerId);
        event.preventDefault();
        return;
      }
      const held = event.target.closest('[data-move]');
      // Grab a place and pull: on empty grass with the left button, with the middle even by a
      // castle. A house, a road, a cart and a castle's yard are not grass: they are clicked,
      // and a click must not be eaten.
      const busy = event.target.closest('[data-move],[data-grip],.house,.lane,.cart,.castle');
      if (event.button === 1 || (!busy && event.button === 0)) {
        this.panning = { from: Svg.point(this.map, event), eye: { ...this.eye } };
        this.map.classList.add('held');
        this.map.setPointerCapture(event.pointerId);
        event.preventDefault();
        return;
      }
      if (!held || event.button !== 0) return;
      const here = Svg.point(this.map, event);
      const place = this.places.of(held.dataset.move);
      // The pointer is captured not here but once the mouse has actually moved. Capturing
      // also redirects the click — it would land on the map's root, and the castle would
      // never see it.
      this.dragging = { name: held.dataset.move, dx: place.x - here.x, dy: place.y - here.y, caught: false };
      this.hint.hide();
      event.preventDefault();
    });
    this.map.addEventListener('pointermove', (event) => {
      if (this.sizing) {
        const here = Svg.point(this.map, event);
        const island = Look.ISLAND;
        Look.FIELD = {
          width: Math.round(Math.max(island.least.width, Math.min(island.most.width,
            this.sizing.was.width + (here.x - this.sizing.from.x)))),
          height: Math.round(Math.max(island.least.height, Math.min(island.most.height,
            this.sizing.was.height + (here.y - this.sizing.from.y)))),
        };
        this.eye = { x: Look.FIELD.width / 2, y: Look.FIELD.height / 2 };
        if (!this.drawing) this.drawing = requestAnimationFrame(() => { this.drawing = null; this.draw(); });
        return;
      }
      if (this.panning) {
        const box = this.map.getBoundingClientRect();
        const view = this.map.viewBox.baseVal;
        const here = {
          x: view.x + (event.clientX - box.left) * (view.width / box.width),
          y: view.y + (event.clientY - box.top) * (view.height / box.height),
        };
        this.eye = { x: this.panning.eye.x + (this.panning.from.x - here.x),
                     y: this.panning.eye.y + (this.panning.from.y - here.y) };
        this.map.setAttribute('viewBox', this.viewBox());
        return;
      }
      if (!this.dragging) return;
      if (!this.dragging.caught) {
        this.map.setPointerCapture(event.pointerId);
        this.dragging.caught = true;
      }
      const here = Svg.point(this.map, event);
      this.places.put(this.dragging.name, here.x + this.dragging.dx, here.y + this.dragging.dy);
      if (!this.drawing) this.drawing = requestAnimationFrame(() => { this.drawing = null; this.draw(); });
    });
    const drop = () => {
      // Dragging the island and poking the grass are the same movement in pixels. A poke
      // means the chosen dweller is gone, and the scroll waits empty again.
      if (this.panning && this.stayed(this.panning)) this.forget();
      this.panning = null;
      this.map.classList.remove('held');
      if (this.sizing) {
        this.sizing = null;
        this.save();
      }
      if (!this.dragging) return;
      const moved = this.dragging.caught;
      this.dragging = null;
      if (moved) this.save();   // nothing moved, so there is nothing to save
    };
    this.map.addEventListener('pointerup', drop);
    this.map.addEventListener('pointercancel', drop);
  }

  save() {
    clearTimeout(this.saving);
    this.saving = setTimeout(async () => {
      try {
        await Api.request('PUT', '/api/layout', this.places.payload());
        this.warn('');
      } catch (err) {
        this.warn(say('layout.not-saved', { why: err.message }));
      }
    }, 400);
  }

  /**
   * Refresh: the router's snapshot and the NAS's containers, taken anew — the very call any
   * reader can make, POST /api/refresh, which answers once both are written. When one of them
   * could not be taken, the other may well have been: the map is drawn afresh either way, and
   * the reason stays in the line of trouble.
   */
  async refresh() {
    const button = document.getElementById('refresh');
    button.disabled = true;
    this.warn(say('refresh.asking'));
    let trouble = '';
    try {
      await Api.request('POST', '/api/refresh', {});
    } catch (err) {
      trouble = err.message;
    }
    try {
      await this.load();
    } finally {
      button.disabled = false;
    }
    if (trouble) this.warn(trouble);
  }
}

// Words first: nothing may be drawn before the page knows the language it speaks.
Tongue.start().then(() => new MapPage().start());

'use strict';

/* How the roads fall for a given layout: lanes and bridges as numbers, with no browser. */

const path = require('path');
const { Corridor, Bridges } = require(path.join(__dirname, '..', 'web', 'geometry.js'));

const town = { x: 640, y: 450 };
const places = JSON.parse(process.argv[2] || '[]');   // [{key, x, y, houses}, …]
const roads = JSON.parse(process.argv[3] || '[]');    // [[from, to], …]

function castle(place) {
  const columns = Math.min(8, Math.max(3, Math.ceil(place.houses / 4)));
  const rows = Math.max(1, Math.ceil(place.houses / columns));
  const width = columns * 46 + 40;
  const height = rows * 42 + 40;
  return { place: { x: place.x, y: place.y },
           box: { x: place.x - width / 2, y: place.y - height / 2, width, height } };
}

const corridors = new Map(places.map((place) => [place.key, new Corridor(castle(place), town)]));
for (const [from, to] of roads) {
  corridors.get(from).add({ source: from, target: to }, 'out');
  corridors.get(to).add({ source: from, target: to }, 'in');
}
const list = [...corridors.values()];
const size = Corridor.gates(list);
const lanes = list.map((corridor, order) => ({
  corridor: order,
  road: corridor.ways.map((way) => `${way.road.source}|${way.road.target}`).join(','),
  points: corridor.spine,
}));
process.stdout.write(JSON.stringify({
  town: size,
  corridors: list.map((corridor, order) => ({
    order, flat: corridor.flat, side: corridor.side, along: corridor.along, width: corridor.width,
  })),
  lanes,
  bridges: Bridges.find(list).map((mark) => ({ ...mark, deck: Bridges.deck(mark) })),
}));

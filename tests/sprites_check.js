'use strict';

/* What the browser would draw, as plain numbers, so the tests can check it without a browser. */

const path = require('path');
// The draughtsman only says words when something is wrong, and here nothing is: the key
// stands in for the phrase, so the check does not need the dictionary at all.
global.say = (key) => key;
const { Sprites } = require(path.join(__dirname, '..', 'web', 'sprites.js'));

const sprites = new Sprites(require(path.join(__dirname, '..', 'web', 'sprites.json')));
const drawn = {};
for (const kind of sprites.kinds) drawn[kind] = sprites.icon(kind);
process.stdout.write(JSON.stringify({
  kinds: sprites.kinds,
  drawn,
  unknown: sprites.icon('no such kind'),
}));

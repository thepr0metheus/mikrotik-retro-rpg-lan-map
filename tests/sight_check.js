'use strict';

/* What a device or a subnet may reach, as the fog will draw it: verdicts as JSON, no browser. */

const path = require('path');
const { Sight } = require(path.join(__dirname, '..', 'web', 'sight.js'));

const world = JSON.parse(process.argv[2]);
const who = JSON.parse(process.argv[3]);     // {device: key} or {segment: key}
const sight = new Sight(world, { anyPort: 'any port', anyProtocol: 'any' });
const verdicts = who.device
  ? sight.ofDevice(world.devices.find((one) => one.key === who.device))
  : sight.ofSegment(who.segment);
process.stdout.write(JSON.stringify(Object.fromEntries(verdicts)));

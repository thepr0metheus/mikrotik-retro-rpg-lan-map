'use strict';

/* How the page links a text in each language asked for, as plain strings, so the tests can
   check it without a browser. */

const path = require('path');
const { Tongue } = require(path.join(__dirname, '..', 'web', 'lang.js'));

const linked = {};
for (const code of JSON.parse(process.argv[2])) linked[code] = new Tongue(code, {}, {}).href('/llms.txt');
process.stdout.write(JSON.stringify(linked));

// The README's pictures, taken from the made-up network in demo/: node tools/screenshots.mjs
//
// The map runs on a copy of demo/ — it writes into its data folder as it goes — with the
// snapshot dated now, so the page does not go asking a router that is not there. A headless
// Chrome with a profile of its own opens it, and the DevTools protocol, spoken over Node's own
// WebSocket, clicks and takes the pictures: no package to install. They land in
// docs/screenshots/.
//
//   CHROME=<path to Chrome>       Google Chrome on macOS by default
//   LAN_MAP_PYTHON=<python 3.14>  python3 by default

import { spawn } from 'node:child_process';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(ROOT, 'docs', 'screenshots');
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PYTHON = process.env.LAN_MAP_PYTHON || 'python3';
const PORT = 18197;
const WIDTH = 1440;
const HEIGHT = 900;
const SCALE = 1.5;

// The made-up devices the pictures look through: their MAC addresses from tools/make_demo.py.
const OLD_IPAD = '02:00:00:00:01:08';

const sleep = (ms) => new Promise((done) => setTimeout(done, ms));

/** The map on a copy of demo/, the snapshot dated now. */
function startMap() {
  const data = mkdtempSync(join(tmpdir(), 'lan-map-demo-'));
  cpSync(join(ROOT, 'demo'), data, { recursive: true });
  const snapshot = JSON.parse(readFileSync(join(data, 'snapshot.json'), 'utf8'));
  snapshot.taken = new Date().toISOString().replace(/\.\d+Z$/, '+00:00');
  writeFileSync(join(data, 'snapshot.json'), JSON.stringify(snapshot));
  const map = spawn(PYTHON, ['-m', 'lan_map'], {
    cwd: ROOT,
    stdio: 'ignore',
    env: {
      ...process.env, LAN_MAP_DATA_DIR: data, LAN_MAP_PORT: String(PORT), LAN_MAP_HOST: '127.0.0.1',
      LAN_MAP_SHOW_NETWORKS: '127.0.0.0/8', LAN_MAP_MOVE_NETWORKS: '127.0.0.0/8',
      LAN_MAP_REFRESH_MINUTES: '0', LAN_MAP_NAMES_MINUTES: '0',
      // No router to find a way to: the map then cannot tell its own house, whoever's machine
      // takes the pictures, and stands its containers and DSM's gate by the router's square.
      LAN_MAP_ROUTER_HOST: '127.0.0.1',
    },
  });
  return { map, data };
}

async function waitFor(url, tries = 50) {
  for (let i = 0; i < tries; i += 1) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      // not up yet
    }
    await sleep(200);
  }
  throw new Error(`${url} did not answer`);
}

/** A headless Chrome with a profile of its own, and the address of its DevTools. */
function startChrome() {
  const profile = mkdtempSync(join(tmpdir(), 'lan-map-chrome-'));
  const chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--force-color-profile=srgb',
    '--lang=en-US', 'about:blank'], { stdio: ['ignore', 'ignore', 'pipe'] });
  const endpoint = new Promise((done, fail) => {
    let text = '';
    chrome.stderr.on('data', (chunk) => {
      text += chunk;
      const found = text.match(/DevTools listening on (ws:\/\/\S+)/);
      if (found) done(found[1]);
    });
    chrome.on('exit', () => fail(new Error(`Chrome stopped: ${text}`)));
  });
  return { chrome, profile, endpoint };
}

/** The DevTools protocol over one WebSocket: send a command, get its answer. */
class Devtools {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.last = 0;
    this.waiting = new Map();
    this.socket.onmessage = (message) => {
      const answer = JSON.parse(message.data);
      const wait = this.waiting.get(answer.id);
      if (!wait) return;
      this.waiting.delete(answer.id);
      if (answer.error) wait.fail(new Error(answer.error.message));
      else wait.done(answer.result);
    };
  }

  open() {
    return new Promise((done, fail) => {
      this.socket.onopen = done;
      this.socket.onerror = fail;
    });
  }

  send(method, params = {}, sessionId = undefined) {
    this.last += 1;
    const id = this.last;
    this.socket.send(JSON.stringify({ id, method, params, sessionId }));
    return new Promise((done, fail) => this.waiting.set(id, { done, fail }));
  }
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const { map, data } = startMap();
  const { chrome, profile, endpoint } = startChrome();
  try {
    const url = `http://127.0.0.1:${PORT}/`;
    await waitFor(`${url}healthz`);
    const tools = new Devtools(await endpoint);
    await tools.open();
    const { targetId } = await tools.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await tools.send('Target.attachToTarget', { targetId, flatten: true });
    const page = (method, params) => tools.send(method, params, sessionId);
    const run = async (expression) => (await page('Runtime.evaluate', { expression, returnByValue: true })).result.value;
    await page('Page.enable');
    await page('Emulation.setDeviceMetricsOverride', { width: WIDTH, height: HEIGHT, deviceScaleFactor: SCALE, mobile: false });

    const open = async () => {
      await page('Page.navigate', { url });
      for (let i = 0; i < 50 && !(await run("document.querySelectorAll('svg g.castle').length")); i += 1) await sleep(200);
      await sleep(1500);    // the carts take their places on the roads
    };
    // The bar, the map and the scroll: the journal of findings below them stays out of the picture.
    const shoot = async (name) => {
      const clip = { x: 0, y: 0, width: WIDTH, height: 754, scale: 1 };
      const { data: png } = await page('Page.captureScreenshot', { format: 'png', clip });
      writeFileSync(join(OUT, name), Buffer.from(png, 'base64'));
      console.log(`  ${name}`);
    };
    const click = async (selector) => {
      const done = await run(`(() => { const node = document.querySelector(${JSON.stringify(selector)});
        if (!node) return false; node.dispatchEvent(new MouseEvent('click', { bubbles: true })); return true; })()`);
      if (!done) throw new Error(`nothing to click: ${selector}`);
      await sleep(900);
    };
    const clickCastle = async (title) => {
      const done = await run(`(() => { const castle = [...document.querySelectorAll('svg g.castle')]
          .find((one) => (one.querySelector('[data-move]') || {}).textContent?.startsWith(${JSON.stringify(title)}));
        if (!castle) return false;
        castle.querySelector('[data-move]').dispatchEvent(new MouseEvent('click', { bubbles: true })); return true; })()`);
      if (!done) throw new Error(`no castle called ${title}`);
      await sleep(900);
    };

    await open();
    await shoot('map.png');
    await click(`[data-device="${OLD_IPAD}"]`);
    await shoot('device.png');
    await open();
    await clickCastle('Guests');
    await shoot('subnet.png');
    await open();
    await click('#theme');
    await shoot('dark.png');
    await click('#theme');      // the theme is remembered in the profile: back to light
  } finally {
    chrome.kill();
    map.kill();
    await sleep(300);
    rmSync(profile, { recursive: true, force: true });
    rmSync(data, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

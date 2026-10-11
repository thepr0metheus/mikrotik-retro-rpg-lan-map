'use strict';

/*
 * The words the page says out loud, in the language its reader chose.
 *
 * The dictionary is the very same file the server reads: web/lang/<code>.json. One file per
 * language, and adding a language means adding a file — nothing here learns its name. English
 * is what the map is written in, and what every other language falls back to, key by key: a
 * half-translated dictionary shows English in the gaps instead of showing nothing.
 *
 * The choice lives in this browser and nowhere else. It is a habit of whoever is looking, not
 * a fact about the network, so it has no business on the server next to the snapshot.
 */

class Tongue {
  static PLAIN = 'en';
  static KEY = 'lan-map.lang';

  constructor(code, words, plain) {
    this.code = code;
    this.words = words || {};
    this.plain = plain || {};
  }

  /** The phrase behind a key, with its holes filled. An unknown key comes back as itself. */
  say(key, parts) {
    const text = this.words[key] || this.plain[key] || key;
    return text.replace(/\{(\w+)\}/g, (hole, name) => (
      parts && parts[name] !== undefined && parts[name] !== null ? String(parts[name]) : hole));
  }

  /**
   * A text the page links to, in the page's language: /llms.txt?lang=ru. English is what a
   * text says without being asked, so it needs no ?lang= at all.
   */
  href(path) {
    return this.code === Tongue.PLAIN ? path : `${path}?lang=${encodeURIComponent(this.code)}`;
  }

  static async book(code) {
    const response = await fetch(`lang/${encodeURIComponent(code)}.json`, { cache: 'no-cache' });
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  }

  /**
   * What was chosen before, or English.
   *
   * The browser's own list is deliberately not listened to. English is the language the map
   * is written in, and a page that guesses would open differently for every viewer while
   * nobody had asked it to. The picker is in the bar, and one click is remembered for good.
   */
  static wanted() {
    try {
      return window.localStorage.getItem(Tongue.KEY) || Tongue.PLAIN;
    } catch (err) {
      return Tongue.PLAIN;   // a private window: English until the picker is used again
    }
  }

  static remember(code) {
    try {
      window.localStorage.setItem(Tongue.KEY, code);
    } catch (err) {
      // nowhere to keep it: the choice lasts until the page is closed
    }
  }

  /** Which languages there are. The server answers by what lies in web/lang. */
  static async shelf() {
    try {
      const response = await fetch('api/langs', { cache: 'no-cache' });
      if (!response.ok) throw new Error(String(response.status));
      const payload = await response.json();
      if (Array.isArray(payload.langs) && payload.langs.length) return payload.langs;
    } catch (err) {
      // the shelf is unreachable: one language is still better than an empty picker
    }
    return [{ code: Tongue.PLAIN, name: 'English' }];
  }

  /**
   * Put the tongue in place before anything is drawn.
   *
   * English is read first and always: it is the fallback for every other language, so a key
   * missing from a translation still comes out as words.
   */
  static async start(code) {
    const plain = await Tongue.book(Tongue.PLAIN).catch(() => ({}));
    const wanted = code || Tongue.wanted();
    const words = wanted === Tongue.PLAIN ? plain : await Tongue.book(wanted).catch(() => null);
    tongue = new Tongue(words ? wanted : Tongue.PLAIN, words || plain, plain);
    Tongue.dress();
    return tongue;
  }

  /**
   * Say the page's own furniture: whatever carries a data-say.
   *
   * The English is written into the HTML as well, so the page reads correctly in the moment
   * before this runs, and keeps reading correctly if the dictionary never arrives. The tab's
   * name is furniture too: each page's <title> carries its own key.
   */
  static dress(root) {
    const where = root || document;
    document.documentElement.lang = tongue.code;
    for (const node of where.querySelectorAll('[data-say]')) {
      node.textContent = say(node.dataset.say);
    }
    for (const [mark, name] of [['sayTitle', 'title'], ['sayPlaceholder', 'placeholder'],
                                ['sayLabel', 'aria-label']]) {
      for (const node of where.querySelectorAll(`[data-${mark.replace(/[A-Z]/g, (up) => `-${up.toLowerCase()}`)}]`)) {
        node.setAttribute(name, say(node.dataset[mark]));
      }
    }
  }
}

let tongue = new Tongue(Tongue.PLAIN, {}, {});

/** The one way the page asks for words. Short on purpose: it is used everywhere. */
function say(key, parts) {
  return tongue.say(key, parts);
}

if (typeof module === 'object' && module.exports) module.exports = { Tongue };

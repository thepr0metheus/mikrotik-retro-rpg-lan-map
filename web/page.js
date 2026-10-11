'use strict';

/*
 * What every page of the map shares: a viewer's habits, the language picker, the line of
 * trouble, and the plain lines the lists are made of.
 *
 * The map and the page of services each kept a copy of these, and copies drift; a third page
 * was one copy too many. So they live here once, and each page is a Page. A page supplies
 * `load()`; the map, which has far more to wire up, supplies its own `start()` as well.
 */

class Page {
  /** Wiring shared by the plain pages: the theme, the language, then the answer itself. */
  async start() {
    this.theme();
    document.getElementById('theme').addEventListener('click', () => this.flip());
    await this.languages();
    await this.load();
  }

  /**
   * The language picker, filled by whatever lies in web/lang: a new file is a new choice.
   *
   * Switching asks the server again rather than redrawing what is already here. Half of what
   * a page shows is said by the server, and the two halves must never end up in different
   * languages.
   */
  async languages() {
    const picker = document.getElementById('tongue');
    const shelf = await Tongue.shelf();
    picker.replaceChildren(...shelf.map((one) => Object.assign(document.createElement('option'),
                                                               { value: one.code, textContent: one.name })));
    picker.value = tongue.code;
    picker.hidden = shelf.length < 2;
    picker.previousElementSibling.hidden = shelf.length < 2;
    picker.addEventListener('change', async (event) => {
      Tongue.remember(event.target.value);
      await Tongue.start(event.target.value);
      await this.retell();
    });
  }

  /** What a page does once it speaks another language: asks the server again. */
  async retell() {
    await this.load();
  }

  /** A dark theme is a viewer's habit, and lives in their own browser. */
  theme() {
    document.documentElement.dataset.theme = Page.remembered('theme', 'light');
  }

  flip() {
    const dark = document.documentElement.dataset.theme !== 'dark';
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    Page.remember('theme', dark ? 'dark' : 'light');
  }

  /** A line of trouble above the page. Empty clears it: nothing is wrong any more. */
  warn(words) {
    const box = document.getElementById('trouble');
    box.textContent = words;
    box.hidden = !words;
  }

  /** A viewer's small habits live in their own browser: nobody else has a use for them. */
  static remembered(name, fallback) {
    try {
      return window.localStorage.getItem(`lan-map.${name}`) || fallback;
    } catch (err) {
      return fallback;
    }
  }

  static remember(name, value) {
    try {
      window.localStorage.setItem(`lan-map.${name}`, value);
    } catch (err) {
      // a private window, or storage refused: the choice simply will not be remembered
    }
  }

  /** The snapshot's moment as the map's own bar says it: hours and minutes, UTC. */
  static clock(taken) {
    return `${String(taken).slice(11, 16)} UTC`;
  }

  /** One line of a list: what it is, and what is known of it. */
  static line(title, about) {
    const line = document.createElement('div');
    line.className = 'entry flat';
    line.append(Page.span(title, 'name'), Page.span(about, 'work'));
    return line;
  }

  static span(text, cls) {
    const node = document.createElement('span');
    node.className = cls;
    node.textContent = text;
    return node;
  }

  static words(text, cls) {
    const node = document.createElement('p');
    if (cls) node.className = cls;
    node.textContent = text;
    return node;
  }
}

'use strict';

/*
 * The page of cards: what each machine at home is made of, written by the owner or an agent.
 *
 * The device is chosen from the map's own list. The form is built from the fields the server
 * names in /api/specs — their keys, kinds and limits live in one place, lan_map/specs.py — and
 * the lines a card is told in come from the server too, in the page's language. The page
 * decides nothing: an empty field wipes its line, and the server says why it refuses.
 */

class SpecsPage extends Page {
  async start() {
    document.getElementById('device').addEventListener('change', (event) => this.choose(event.target.value));
    document.getElementById('card').addEventListener('submit', (event) => {
      event.preventDefault();
      this.keep();
    });
    await super.start();
  }

  async load() {
    let answer;
    try {
      answer = await Api.request('GET', `/api/specs?lang=${tongue.code}`);
    } catch (err) {
      this.warn(err.message);
      return;
    }
    this.warn(answer.missing || '');
    this.answer = answer;
    this.picker();
    this.cards();
    this.choose(this.wanted());
  }

  /** The device asked for: in the address, as the map's scroll links here, or the one shown before. */
  wanted() {
    const asked = new URLSearchParams(window.location.search).get('device') || this.shown || '';
    return this.answer.devices.some((one) => one.device === asked) ? asked : '';
  }

  /** Every device of the map, with a mark on those that have a card. */
  picker() {
    const picker = document.getElementById('device');
    const none = Object.assign(document.createElement('option'), { value: '', textContent: say('specs.choose') });
    picker.replaceChildren(none, ...this.answer.devices.map((one) => Object.assign(document.createElement('option'), {
      value: one.device, textContent: SpecsPage.title(one) + (one.specs ? ' ✓' : ''),
    })));
    const filled = this.answer.devices.filter((one) => one.specs).length;
    document.getElementById('filled').textContent = say('specs.filled', { count: filled, total: this.answer.devices.length });
  }

  static title(one) {
    const where = one.addresses.length ? one.addresses.join(', ') : say('specs.device.absent');
    return `${one.name || say('specs.nameless')} · ${where}`;
  }

  /** Shows one device's card in the form; nothing chosen hides the form. */
  choose(key) {
    this.shown = key;
    document.getElementById('device').value = key;
    const address = new URL(window.location.href);
    if (key) address.searchParams.set('device', key);
    else address.searchParams.delete('device');
    window.history.replaceState(null, '', address.pathname + address.search);
    const entry = this.answer.devices.find((one) => one.device === key);
    document.getElementById('card').hidden = !entry;
    document.getElementById('status').textContent = '';
    if (entry) this.form(entry);
  }

  /** The form, built from the fields the server names: one place says what a card holds. */
  form(entry) {
    const specs = entry.specs || {};
    const lines = [SpecsPage.input({ key: 'name', kind: 'text', most: this.answer.name_most }, entry.name,
                                   'specs.label.name')];
    for (const field of this.answer.fields) {
      lines.push(field.kind === 'disks' ? SpecsPage.disks(specs.disks || [])
        : SpecsPage.input(field, specs[field.key], `specs.label.${field.key}`));
    }
    document.getElementById('lines').replaceChildren(...lines);
  }

  static input(field, value, label) {
    const part = document.createElement('label');
    part.className = field.kind === 'long' ? 'line wide' : 'line';
    const box = document.createElement(field.kind === 'long' ? 'textarea' : 'input');
    box.name = field.key;
    if (field.kind === 'count' || field.kind === 'size') {
      Object.assign(box, { type: 'number', min: field.kind === 'count' ? 1 : 0, max: field.most,
                           step: field.kind === 'count' ? 1 : 'any' });
    } else {
      box.maxLength = field.most;
      if (field.kind === 'long') box.rows = 3;
    }
    const example = `specs.example.${field.key}`;
    if (say(example) !== example) box.placeholder = say(example);
    box.value = value === undefined || value === null ? '' : String(value);
    part.append(Page.span(say(label), 'label'), box);
    return part;
  }

  /** Disks are rows: a size in GB or TB, and what the disk is. */
  static disks(disks) {
    const part = document.createElement('div');
    part.className = 'line wide';
    const rows = document.createElement('div');
    rows.className = 'rows';
    rows.append(...disks.map((disk) => SpecsPage.disk(disk)));
    const add = Object.assign(document.createElement('button'), { type: 'button', textContent: say('specs.disk.add') });
    add.addEventListener('click', () => rows.append(SpecsPage.disk({})));
    part.append(Page.span(say('specs.label.disks'), 'label'), rows, add);
    return part;
  }

  static disk(disk) {
    const row = document.createElement('div');
    row.className = 'disk';
    const tb = disk.size_gb >= 1000;
    const size = Object.assign(document.createElement('input'), {
      type: 'number', min: 0, step: 'any', className: 'size', placeholder: say('specs.disk.size'),
      value: disk.size_gb ? String(tb ? disk.size_gb / 1000 : disk.size_gb) : '',
    });
    const unit = document.createElement('select');
    unit.className = 'unit';
    unit.append(...['gb', 'tb'].map((one) => Object.assign(document.createElement('option'),
                                                            { value: one, textContent: say(`specs.unit.${one}`) })));
    unit.value = tb ? 'tb' : 'gb';
    const kind = Object.assign(document.createElement('input'), {
      className: 'type', maxLength: 40, placeholder: say('specs.disk.type'), value: disk.type || '',
    });
    const drop = Object.assign(document.createElement('button'), { type: 'button', textContent: say('specs.disk.remove') });
    drop.addEventListener('click', () => row.remove());
    row.append(size, unit, kind, drop);
    return row;
  }

  /**
   * The form as the server takes it: every field sent, an empty one to wipe its line. The name
   * goes only when it changed: from a network that may not move things it would be refused.
   */
  body(entry) {
    const card = document.getElementById('card');
    const body = { device: entry.device };
    const name = card.elements.name.value.trim();
    if (name !== entry.name) body.name = name;
    for (const field of this.answer.fields) {
      if (field.kind === 'disks') {
        body.disks = [...card.querySelectorAll('.disk')].map((row) => {
          const size = row.querySelector('.size').value.trim();
          const times = row.querySelector('.unit').value === 'tb' ? 1000 : 1;
          return size === '' ? null : { size_gb: Number(size) * times, type: row.querySelector('.type').value.trim() };
        }).filter((disk) => disk !== null);
      } else {
        const value = card.elements[field.key].value.trim();
        body[field.key] = field.kind === 'count' || field.kind === 'size'
          ? (value === '' ? null : Number(value)) : value;
      }
    }
    return body;
  }

  async keep() {
    const entry = this.answer.devices.find((one) => one.device === this.shown);
    if (!entry) return;
    const status = document.getElementById('status');
    const button = document.getElementById('keep');
    button.disabled = true;
    status.textContent = say('specs.saving');
    try {
      await Api.request('PUT', '/api/specs', this.body(entry));
    } catch (err) {
      status.textContent = err.message;
      button.disabled = false;
      return;
    }
    button.disabled = false;
    await this.load();
    document.getElementById('status').textContent = say('specs.saved');
  }

  /** Every card written so far, in the server's own words; a click opens it in the form. */
  cards() {
    const filled = this.answer.devices.filter((one) => one.specs);
    const box = document.getElementById('cards');
    if (!filled.length) {
      box.replaceChildren(Page.words(say('specs.cards.none'), 'quiet'));
      return;
    }
    box.replaceChildren(...filled.map((one) => {
      const card = document.createElement('div');
      card.className = 'place';
      const head = document.createElement('h3');
      const open = Object.assign(document.createElement('a'), {
        href: `?device=${encodeURIComponent(one.device)}`, textContent: SpecsPage.title(one),
      });
      open.addEventListener('click', (event) => {
        event.preventDefault();
        this.choose(one.device);
        window.scrollTo(0, 0);
      });
      head.append(open);
      const list = document.createElement('ul');
      list.append(...one.lines.map((line) => Object.assign(document.createElement('li'), { textContent: line })));
      card.append(head, list);
      return card;
    }));
  }
}

// Words first: nothing may be drawn before the page knows the language it speaks.
Tongue.start().then(() => new SpecsPage().start());

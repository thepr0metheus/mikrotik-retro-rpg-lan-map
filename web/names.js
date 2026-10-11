'use strict';

/*
 * The page of names: the router's own static DNS records, and where each of them leads.
 *
 * Every device that asks the router for names gets these answers, so this is the list of
 * names that mean something at home. Nothing here is typed. Every line is a record as the
 * router holds it, grouped by the answer it gives, and every group says who on the map holds
 * that answer — the router, a device, or nobody, which gets a section of its own rather than
 * being passed over. Below them: whom each network's devices ask. Where that is not the
 * router, the names above do not work there.
 *
 * The page holds no words of its own: every line comes from the dictionary in lang.js, by key.
 */

class NamesPage extends Page {
  async load() {
    let answer;
    try {
      answer = await Api.request('GET', `/api/names?lang=${tongue.code}`);
    } catch (err) {
      this.warn(err.message);
      return;
    }
    this.warn(answer.missing || '');
    this.draw(answer);
  }

  /**
   * The names by where they lead, then those leading to nobody, then who asks the router.
   * Empty lists are not "no names" when nothing was read: then the reason stands above them
   * and the list stays silent rather than say "none".
   */
  draw(answer) {
    const places = answer.places || [];
    const askers = answer.askers || [];
    const taken = document.getElementById('taken');
    taken.hidden = !answer.taken;
    if (answer.taken) taken.textContent = say('names.taken', { time: Page.clock(answer.taken) });
    const held = places.filter((place) => place.where !== 'nobody');
    const lost = places.filter((place) => place.where === 'nobody');
    const none = answer.missing ? [] : [Page.words(say('names.none'), 'quiet')];
    document.getElementById('places').replaceChildren(
      ...(held.length ? held.map((place) => NamesPage.place(place)) : none));
    document.getElementById('lost-part').hidden = !lost.length;
    document.getElementById('lost').replaceChildren(...lost.map((place) => NamesPage.place(place)));
    document.getElementById('askers-part').hidden = !askers.length;
    document.getElementById('askers').replaceChildren(...askers.map((asker) => NamesPage.asker(asker)));
  }

  /** One answer: who holds it, where it stands, and every name that gives it. */
  static place(place) {
    const box = document.createElement('div');
    box.className = 'place';
    const head = document.createElement('h3');
    head.append(document.createTextNode(`${NamesPage.holder(place)} `),
                Page.span(NamesPage.address(place), 'quiet'));
    box.append(head, ...place.names.map((record) => NamesPage.record(record)));
    return box;
  }

  /**
   * Who holds an answer, by the kind the server found. A kind this page does not know is
   * shown as it came rather than dressed up as one it does.
   */
  static holder(place) {
    const holders = {
      router: () => say('names.router'),
      device: () => place.who || say('names.unnamed'),
      nobody: () => say('names.nobody'),
      beyond: () => say('names.beyond', { type: place.names[0].type }),
    };
    return (holders[place.where] || (() => place.where))();
  }

  /** The answer itself, and the network it stands in. An address in none of them says so. */
  static address(place) {
    if (place.where === 'beyond') return place.to;
    return `${place.to} · ${place.segment || say('names.outside')}`;
  }

  /** One name, and what else the router says of it: anything unusual first, then its note. */
  static record(record) {
    const parts = [];
    if (record.type !== 'A') parts.push(record.type);
    if (record.pattern) parts.push(say('names.pattern'));
    if (record.subdomains) parts.push(say('names.subdomains'));
    if (record.disabled) parts.push(say('names.disabled'));
    if (record.ttl) parts.push(say('names.ttl', { ttl: record.ttl }));
    if (record.comment) parts.push(record.comment);
    const line = Page.line(record.name, parts.join(' · '));
    line.classList.toggle('off', record.disabled);
    return line;
  }

  /** Whom one network's devices ask for names, as its DHCP tells them. */
  static asker(asker) {
    const servers = asker.servers.join(', ');
    let said;
    if (asker.router === null) said = say('names.asker.unset');
    else if (asker.router) said = say('names.asker.router', { servers });
    else said = say('names.asker.elsewhere', { servers });
    return Page.line(asker.segment || asker.network,
                     asker.segment ? `${asker.network} · ${said}` : said);
  }
}

Tongue.start().then(() => new NamesPage().start());

'use strict';

/*
 * The page of services and networks: who the network is talking to out in the world.
 *
 * Nothing here is typed. Every line is a far end of the live walks in the latest snapshot,
 * named by the router's own answers — now, or remembered — or by the map's table of houses,
 * and whatever none of them could name is listed as unknown rather than passed over. The page
 * used to be a form for a table of one's own; the one reader it had wanted the answer, not the
 * form.
 *
 * The page holds no words of its own: every line comes from the dictionary in lang.js, by key.
 */

class HousesPage extends Page {
  async load() {
    let answer;
    try {
      answer = await Api.request('GET', `/api/houses?lang=${tongue.code}`);
    } catch (err) {
      this.warn(err.message);
      return;
    }
    this.warn(answer.missing || '');
    this.draw(answer);
  }

  /**
   * Both lists. Two empty ones are not "nobody out there" when there was nothing to look at:
   * then the reason stands above them and the known list stays silent rather than say "none".
   */
  draw(answer) {
    const known = answer.known || [];
    const unknown = answer.unknown || [];
    const taken = document.getElementById('taken');
    taken.hidden = !answer.taken;
    if (answer.taken) taken.textContent = say('houses.taken', { time: Page.clock(answer.taken) });
    const none = answer.missing ? [] : [Page.words(say('houses.known.none'), 'quiet')];
    document.getElementById('known').replaceChildren(
      ...(known.length ? known.map((one) => Page.line(one.who, HousesPage.about(one))) : none));
    document.getElementById('unknown-part').hidden = !unknown.length;
    document.getElementById('unknown').replaceChildren(
      ...unknown.map((one) => Page.line(one.ip, say('houses.connections', { count: one.count }))));
  }

  /** How much of the traffic a line carries, and how it is known when that is not a plain fact. */
  static about(one) {
    const parts = [say('houses.connections', { count: one.count })];
    if (one.addresses > 1) parts.push(say('houses.addresses', { count: one.addresses }));
    if (one.by !== 'name') parts.push(say(`houses.by.${one.by}`));
    return parts.join(' · ');
  }
}

Tongue.start().then(() => new HousesPage().start());

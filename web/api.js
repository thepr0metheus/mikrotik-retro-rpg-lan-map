'use strict';

/*
 * One way of talking to the server, for every page there is.
 *
 * Errors come back already said in the reader's language — the server says its own refusals —
 * and what the page has to say for itself, when there is no answer at all to quote, it says
 * out of the dictionary like everything else.
 */

class Api {
  static async request(method, path, body) {
    const init = { method, cache: 'no-store', headers: {} };
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, init);
    } catch (err) {
      throw new Error(say('api.no-answer'));
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch (err) {
      payload = null;
    }
    if (!response.ok) {
      const failed = new Error((payload && payload.error) || say('api.error', { status: response.status }));
      failed.status = response.status;
      throw failed;
    }
    if (payload === null) throw new Error(say('api.not-json'));
    return payload;
  }
}

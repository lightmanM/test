'use strict';

// Minimal stand-in for @slack/bolt: records handlers so tests can call them.
const handlers = { event: {}, command: {} };

class App {
  constructor() {
    this.client = { auth: { test: async () => ({ user_id: 'UBOT' }) } };
  }
  event(name, fn) {
    handlers.event[name] = fn;
  }
  command(name, fn) {
    handlers.command[name] = fn;
  }
  async start() {}
}

module.exports = { App, handlers };

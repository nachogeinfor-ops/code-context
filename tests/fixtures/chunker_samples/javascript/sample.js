// Sample JS file for tree-sitter chunker tests.

const GREETING = "hello";

function formatMessage(name) {
  return `${GREETING}, ${name}!`;
}

class Storage {
  constructor() {
    this._data = {};
  }

  put(key, value) {
    this._data[key] = value;
  }

  get(key) {
    return this._data[key];
  }
}

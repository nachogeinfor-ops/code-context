// Sample TS file for tree-sitter chunker tests.

const GREETING: string = "hello";

interface User {
  id: number;
  name: string;
}

type GreetingFn = (name: string) => string;

function formatMessage(name: string): string {
  return `${GREETING}, ${name}!`;
}

class Storage {
  private data: Record<string, string> = {};

  put(key: string, value: string): void {
    this.data[key] = value;
  }

  get(key: string): string | undefined {
    return this.data[key];
  }
}

import { createApiClient } from '../src/services/api';

const bindingSensitiveFetch = function (this: typeof globalThis) {
  if (this !== globalThis) {
    throw new TypeError("Failed to execute 'fetch' on 'Window': Illegal invocation");
  }
  return Promise.resolve(new Response(JSON.stringify({ ok: true }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }));
} as typeof fetch;

async function main() {
  const api = createApiClient({
    baseUrl: 'http://127.0.0.1:8765',
    fetchImpl: bindingSensitiveFetch,
  });

  await api.sampleCore();
  console.log(JSON.stringify({ ok: true, fetchBoundToGlobalThis: true }));
}

void main();

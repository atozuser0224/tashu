import AsyncStorage from '@react-native-async-storage/async-storage';
import { Linking } from 'react-native';

const STORAGE_KEY = 'ridego:test-phone-binding';

export type DriverBinding = {
  deviceId: string;
  driverId: string;
  planId?: string;
  scenarioId?: string;
  revision?: number;
};

export async function loadInitialDriverBinding(
  defaults: DriverBinding,
): Promise<DriverBinding> {
  const stored = await loadStoredDriverBinding();
  const initialUrl = await Linking.getInitialURL();
  return applyDriverBindingUrl({ ...defaults, ...stored }, initialUrl);
}

export function applyDriverBindingUrl(
  current: DriverBinding,
  url: string | null,
): DriverBinding {
  if (!url) return current;
  const params = queryParams(url);
  const driver = firstParam(params, ['driver_id', 'driverId']);
  const plan = firstParam(params, ['plan_id', 'planId']);
  const device = firstParam(params, ['device_id', 'deviceId']);
  if (!driver.present && !plan.present && !device.present) return current;

  const next = { ...current };
  if (device.value) next.deviceId = device.value;
  if (driver.value) {
    if (driver.value !== current.driverId && !plan.present) delete next.planId;
    next.driverId = driver.value;
  }
  if (plan.present) {
    if (plan.value) next.planId = plan.value;
    else delete next.planId;
  }
  return next;
}

export async function saveDriverBinding(binding: DriverBinding): Promise<void> {
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(binding));
}

async function loadStoredDriverBinding(): Promise<Partial<DriverBinding>> {
  const raw = await AsyncStorage.getItem(STORAGE_KEY);
  if (!raw) return {};
  try {
    const value = JSON.parse(raw) as unknown;
    if (!isRecord(value)) return {};
    const binding: Partial<DriverBinding> = {};
    if (isIdentifier(value.deviceId)) binding.deviceId = value.deviceId.trim();
    if (isIdentifier(value.driverId)) binding.driverId = value.driverId.trim();
    if (isIdentifier(value.planId)) binding.planId = value.planId.trim();
    if (isIdentifier(value.scenarioId)) binding.scenarioId = value.scenarioId.trim();
    if (typeof value.revision === 'number' && Number.isFinite(value.revision)) {
      binding.revision = value.revision;
    }
    return binding;
  } catch {
    return {};
  }
}

function queryParams(url: string): Map<string, string> {
  const result = new Map<string, string>();
  const queryStart = url.indexOf('?');
  if (queryStart < 0) return result;
  const hashStart = url.indexOf('#', queryStart);
  const query = url.slice(queryStart + 1, hashStart < 0 ? undefined : hashStart);
  for (const pair of query.split('&')) {
    if (!pair) continue;
    const separator = pair.indexOf('=');
    const rawKey = separator < 0 ? pair : pair.slice(0, separator);
    const rawValue = separator < 0 ? '' : pair.slice(separator + 1);
    try {
      result.set(
        decodeURIComponent(rawKey.replace(/\+/g, ' ')),
        decodeURIComponent(rawValue.replace(/\+/g, ' ')).trim(),
      );
    } catch {
      // Ignore malformed URL parameters and retain the last known assignment.
    }
  }
  return result;
}

function firstParam(
  params: Map<string, string>,
  names: string[],
): { present: boolean; value?: string } {
  for (const name of names) {
    if (!params.has(name)) continue;
    const value = params.get(name);
    return isIdentifier(value) ? { present: true, value: value.trim() } : { present: true };
  }
  return { present: false };
}

function isIdentifier(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0 && value.trim().length <= 160;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

import AsyncStorage from '@react-native-async-storage/async-storage';

import type { Coordinate, StopAction } from '../types/api';

const ROOT_PREFIX = 'ridego:';

export type PendingBikeStop = {
  missionId: string;
  sequence: number;
  action: StopAction;
  location: Coordinate;
  actualQuantity: number;
  scannedBikeCodes: string[];
  beforeCodes: string[];
  afterCodes: string[];
  createdAt: string;
};

function missionPrefix(driverId: string, missionId: string) {
  return `${ROOT_PREFIX}${driverId}:${missionId}`;
}

function inventoryKey(driverId: string, missionId: string) {
  return `${missionPrefix(driverId, missionId)}:bike-codes`;
}

function journalKey(driverId: string, missionId: string) {
  return `${missionPrefix(driverId, missionId)}:pending-stop`;
}

export async function loadBikeCodes(driverId: string, missionId: string): Promise<string[]> {
  const raw = await AsyncStorage.getItem(inventoryKey(driverId, missionId));
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === 'string') : [];
  } catch {
    return [];
  }
}

export async function saveBikeCodes(driverId: string, missionId: string, codes: string[]) {
  await AsyncStorage.setItem(inventoryKey(driverId, missionId), JSON.stringify(codes));
}

export async function loadPendingBikeStop(driverId: string, missionId: string): Promise<PendingBikeStop | null> {
  const raw = await AsyncStorage.getItem(journalKey(driverId, missionId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as PendingBikeStop;
    if (parsed.missionId !== missionId || !Number.isInteger(parsed.sequence) || !Array.isArray(parsed.afterCodes)) return null;
    return parsed;
  } catch {
    return null;
  }
}

export async function savePendingBikeStop(driverId: string, journal: PendingBikeStop) {
  await AsyncStorage.setItem(journalKey(driverId, journal.missionId), JSON.stringify(journal));
}

export async function commitPendingBikeStop(driverId: string, journal: PendingBikeStop) {
  await saveBikeCodes(driverId, journal.missionId, journal.afterCodes);
  await AsyncStorage.removeItem(journalKey(driverId, journal.missionId));
}

export async function discardPendingBikeStop(driverId: string, missionId: string) {
  await AsyncStorage.removeItem(journalKey(driverId, missionId));
}

export async function clearMissionBikeState(driverId: string, missionId: string) {
  await AsyncStorage.multiRemove([
    inventoryKey(driverId, missionId),
    journalKey(driverId, missionId),
  ]);
}

export async function clearDriverBikeState(driverId: string) {
  const keys = await AsyncStorage.getAllKeys();
  const prefix = `${ROOT_PREFIX}${driverId}:`;
  const owned = keys.filter((key) => key.startsWith(prefix));
  if (owned.length) await AsyncStorage.multiRemove(owned);
}

export async function clearAllBikeState() {
  const keys = await AsyncStorage.getAllKeys();
  const owned = keys.filter((key) => key.startsWith(ROOT_PREFIX));
  if (owned.length) await AsyncStorage.multiRemove(owned);
}

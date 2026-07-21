import { Platform } from 'react-native';

const platformDefault =
  Platform.OS === 'android'
    ? 'http://10.0.2.2:8765'
    : 'http://127.0.0.1:8765';

export const DEFAULT_API_BASE_URL = (
  process.env.EXPO_PUBLIC_API_BASE_URL || platformDefault
).replace(/\/$/, '');

const TEST_TMAP_APP_KEY = 'L46IMLQYRu11AZhUXWRkz9Qarp01Bpm86xObCORB';

export const DEFAULT_TMAP_APP_KEY =
  process.env.EXPO_PUBLIC_TMAP_APP_KEY || TEST_TMAP_APP_KEY;
export const DEFAULT_DRIVER_ID = 'DRIVER-01';
export const DEFAULT_DEVICE_ID = 'RIDEGO-TEST-DEVICE-01';

export const TEST_MODE = true;

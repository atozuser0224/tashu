import { useCallback, useMemo, useState } from 'react';
import { Platform, StyleSheet, Text, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';
import { useFonts } from 'expo-font';
import {
  Archivo_400Regular,
  Archivo_500Medium,
  Archivo_600SemiBold,
  Archivo_700Bold,
  Archivo_800ExtraBold,
} from '@expo-google-fonts/archivo';

import { AppDrawer, type AppSection } from './src/components/AppDrawer';
import {
  DEFAULT_API_BASE_URL,
  DEFAULT_DEVICE_ID,
  DEFAULT_DRIVER_ID,
  DEFAULT_TMAP_APP_KEY,
} from './src/config';
import { createApiClient } from './src/services/api';
import { LoginScreen } from './src/screens/LoginScreen';
import { MissionNavigationScreen } from './src/screens/MissionNavigationScreen';
import { ProfileSetupScreen, type DriverProfile } from './src/screens/ProfileSetupScreen';
import { RewardsScreen } from './src/screens/RewardsScreen';
import { SettingsScreen } from './src/screens/SettingsScreen';
import { SplashScreen } from './src/screens/SplashScreen';
import { colors, fonts } from './src/theme';
import type { RewardTransaction, Wallet } from './src/types/api';

type Gate = 'splash' | 'login' | 'profile' | 'app';

const initialSettings = {
  apiBaseUrl: DEFAULT_API_BASE_URL,
  driverId: DEFAULT_DRIVER_ID,
  tmapKey: DEFAULT_TMAP_APP_KEY,
};

export default function App() {
  const [fontsLoaded] = useFonts({
    Archivo_400Regular,
    Archivo_500Medium,
    Archivo_600SemiBold,
    Archivo_700Bold,
    Archivo_800ExtraBold,
  });
  const [gate, setGate] = useState<Gate>('splash');
  const [profile, setProfile] = useState<DriverProfile | null>(null);
  const settings = initialSettings;
  const [section, setSection] = useState<AppSection>('mission');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [transactions, setTransactions] = useState<RewardTransaction[]>([]);
  const [rewardsLoading, setRewardsLoading] = useState(false);

  const api = useMemo(
    () => createApiClient({
      baseUrl: settings.apiBaseUrl,
      driverId: settings.driverId,
      deviceId: DEFAULT_DEVICE_ID,
    }),
    [settings.apiBaseUrl, settings.driverId],
  );

  const refreshRewards = useCallback(async () => {
    setRewardsLoading(true);
    try {
      const [nextWallet, nextTransactions] = await Promise.all([
        api.getWallet(),
        api.getTransactions(),
      ]);
      setWallet(nextWallet);
      setTransactions(nextTransactions);
    } catch {
      setWallet(null);
      setTransactions([]);
    } finally {
      setRewardsLoading(false);
    }
  }, [api]);

  const selectSection = (next: AppSection) => {
    setDrawerOpen(false);
    setSection(next);
    if (next === 'rewards') void refreshRewards();
  };

  const completeProfile = (next: DriverProfile) => {
    setProfile(next);
    setGate('app');
  };

  const logout = () => {
    setDrawerOpen(false);
    setGate('login');
    setSection('mission');
    setProfile(null);
  };

  let content;
  if (gate === 'splash') {
    content = <SplashScreen onDone={() => setGate('login')} />;
  } else if (gate === 'login') {
    content = <LoginScreen onLogin={() => setGate('profile')} />;
  } else if (gate === 'profile') {
    content = <ProfileSetupScreen onComplete={completeProfile} />;
  } else {
    content = (
      <View style={styles.safeArea}>
        {section === 'mission' ? (
          <MissionNavigationScreen
            api={api}
            tmapKey={settings.tmapKey}
            refreshToken={refreshToken}
            onMenu={() => setDrawerOpen(true)}
            onOpenRewards={() => selectSection('rewards')}
          />
        ) : null}
        {section === 'rewards' ? (
          <RewardsScreen
            driverId={settings.driverId}
            wallet={wallet}
            transactions={transactions}
            loading={rewardsLoading}
            onRefresh={refreshRewards}
            onMenu={() => setDrawerOpen(true)}
          />
        ) : null}
        {section === 'settings' ? (
          <SettingsScreen
            profile={profile}
            onLogout={logout}
            onMenu={() => setDrawerOpen(true)}
          />
        ) : null}
        <AppDrawer
          visible={drawerOpen}
          active={section}
          driverId={settings.driverId}
          onClose={() => setDrawerOpen(false)}
          onSelect={selectSection}
          onLogout={logout}
        />
      </View>
    );
  }

  if (!fontsLoaded) return <View style={styles.fontLoader} />;

  const webPreview = Platform.OS === 'web';
  return (
    <SafeAreaProvider style={styles.provider}>
      <StatusBar style="dark" />
      <View style={[styles.stage, webPreview && styles.webStage]}>
        <View style={webPreview ? styles.webDevice : styles.device}>
          <View
            style={styles.root}
            testID="ridego-app"
            accessibilityLabel={profile ? `${profile.name} 기사 앱` : '타슈캐스트 기사 앱'}
          >
            {content}
          </View>
          {webPreview ? <PrototypeStatusBar /> : null}
        </View>
      </View>
    </SafeAreaProvider>
  );
}

function PrototypeStatusBar() {
  return (
    <View pointerEvents="none" style={styles.prototypeStatus}>
      <Text style={styles.prototypeTime}>11:32</Text>
      <View style={styles.prototypeSignals}>
        <View style={styles.signalBars}>
          {[4, 7, 10, 13].map((height, index) => (
            <View
              key={height}
              style={[styles.signalBar, { height, opacity: index === 3 ? 0.35 : 1 }]}
            />
          ))}
        </View>
        <Text style={styles.prototypeLte}>LTE</Text>
        <View style={styles.battery}>
          <View style={styles.batteryFill} />
          <View style={styles.batteryTip} />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  provider: { flex: 1, backgroundColor: '#D3CEC8' },
  stage: { flex: 1, backgroundColor: colors.canvas },
  webStage: {
    minHeight: 896,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 26,
    backgroundColor: '#D3CEC8',
  },
  device: { flex: 1, overflow: 'hidden', backgroundColor: colors.paper },
  webDevice: {
    flexGrow: 0,
    flexShrink: 0,
    flexBasis: 844,
    width: 390,
    height: 844,
    minHeight: 844,
    maxHeight: 844,
    overflow: 'hidden',
    backgroundColor: colors.paper,
    borderWidth: 11,
    borderColor: '#0C0C0C',
    borderRadius: 46,
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 34 },
    shadowOpacity: 0.38,
    shadowRadius: 45,
  },
  root: { flex: 1, backgroundColor: colors.canvas },
  safeArea: { flex: 1, backgroundColor: colors.paper },
  fontLoader: { flex: 1, backgroundColor: colors.orange },
  prototypeStatus: {
    position: 'absolute',
    zIndex: 200,
    top: 0,
    left: 0,
    right: 0,
    height: 54,
    paddingTop: 14,
    paddingHorizontal: 30,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  prototypeTime: {
    color: colors.ink,
    fontFamily: fonts.bold,
    fontSize: 17,
    letterSpacing: -0.34,
  },
  prototypeSignals: { flexDirection: 'row', alignItems: 'center', gap: 7 },
  signalBars: { height: 13, flexDirection: 'row', alignItems: 'flex-end', gap: 2 },
  signalBar: { width: 3, borderRadius: 1, backgroundColor: colors.ink },
  prototypeLte: { color: colors.ink, fontFamily: fonts.bold, fontSize: 13 },
  battery: {
    width: 23,
    height: 14,
    padding: 2,
    borderWidth: 1.4,
    borderColor: 'rgba(32,30,29,.45)',
    borderRadius: 3,
  },
  batteryFill: { width: 16, height: 8, borderRadius: 1.5, backgroundColor: colors.ink },
  batteryTip: {
    position: 'absolute',
    right: -4,
    top: 3.5,
    width: 2,
    height: 5,
    borderRadius: 1,
    backgroundColor: 'rgba(32,30,29,.45)',
  },
});

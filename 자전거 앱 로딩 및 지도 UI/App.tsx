import { useCallback, useEffect, useMemo, useState } from 'react';
import { Linking, StyleSheet, View } from 'react-native';
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
import {
  applyDriverBindingUrl,
  loadInitialDriverBinding,
  saveDriverBinding,
  type DriverBinding,
} from './src/services/driverBinding';
import { LoginScreen } from './src/screens/LoginScreen';
import { MissionNavigationScreen } from './src/screens/MissionNavigationScreen';
import { ProfileSetupScreen, type DriverProfile } from './src/screens/ProfileSetupScreen';
import { RewardsScreen } from './src/screens/RewardsScreen';
import { SettingsScreen } from './src/screens/SettingsScreen';
import { SplashScreen } from './src/screens/SplashScreen';
import { colors } from './src/theme';
import type { RewardTransaction, Wallet } from './src/types/api';

type Gate = 'splash' | 'login' | 'profile' | 'app';

const initialSettings = {
  apiBaseUrl: DEFAULT_API_BASE_URL,
  tmapKey: DEFAULT_TMAP_APP_KEY,
};

const defaultBinding: DriverBinding = {
  deviceId: DEFAULT_DEVICE_ID,
  driverId: DEFAULT_DRIVER_ID,
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
  const [binding, setBinding] = useState<DriverBinding>(defaultBinding);
  const [bindingReady, setBindingReady] = useState(false);
  const [section, setSection] = useState<AppSection>('mission');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [transactions, setTransactions] = useState<RewardTransaction[]>([]);
  const [rewardsLoading, setRewardsLoading] = useState(false);

  const api = useMemo(
    () => createApiClient({
      baseUrl: settings.apiBaseUrl,
      driverId: binding.driverId,
      deviceId: binding.deviceId,
    }),
    [binding.deviceId, binding.driverId, settings.apiBaseUrl],
  );

  useEffect(() => {
    let active = true;
    void loadInitialDriverBinding(defaultBinding)
      .then((next) => {
        if (active) setBinding(next);
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setBindingReady(true);
      });
    const subscription = Linking.addEventListener('url', ({ url }) => {
      setBinding((current) => applyDriverBindingUrl(current, url));
    });
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    if (!bindingReady) return;
    void saveDriverBinding(binding).catch(() => undefined);
  }, [binding, bindingReady]);

  useEffect(() => {
    if (!bindingReady) return undefined;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const pollAssignment = async () => {
      try {
        const assignment = await api.getDeviceAssignment(binding.deviceId);
        if (!active) return;
        if (!assignment) {
          setBinding((current) => current.planId || current.scenarioId || current.revision
            ? { deviceId: current.deviceId, driverId: current.driverId }
            : current);
          return;
        }
        setBinding((current) => {
          if (current.deviceId !== assignment.device_id) return current;
          if (
            current.driverId === assignment.driver_id
            && current.planId === assignment.plan_id
            && current.scenarioId === assignment.scenario_id
            && current.revision === assignment.revision
          ) return current;
          return {
            deviceId: assignment.device_id,
            driverId: assignment.driver_id,
            planId: assignment.plan_id,
            scenarioId: assignment.scenario_id,
            revision: assignment.revision,
          };
        });
      } catch {
        // An unassigned device keeps its URL or persisted fallback identity.
      } finally {
        if (active) timer = setTimeout(pollAssignment, 3_000);
      }
    };

    void pollAssignment();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [api, binding.deviceId, bindingReady]);

  useEffect(() => {
    setWallet(null);
    setTransactions([]);
  }, [api]);

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
            key={`${binding.driverId}:${binding.planId ?? ''}:${binding.revision ?? 0}`}
            api={api}
            tmapKey={settings.tmapKey}
            refreshToken={binding.revision ?? 0}
            preferredPlanId={binding.planId}
            onMenu={() => setDrawerOpen(true)}
            onOpenRewards={() => selectSection('rewards')}
          />
        ) : null}
        {section === 'rewards' ? (
          <RewardsScreen
            driverId={binding.driverId}
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
          driverId={binding.driverId}
          onClose={() => setDrawerOpen(false)}
          onSelect={selectSection}
          onLogout={logout}
        />
      </View>
    );
  }

  if (!fontsLoaded) return <View style={styles.fontLoader} />;

  return (
    <SafeAreaProvider style={styles.provider}>
      <StatusBar style="dark" />
      <View style={styles.stage}>
        <View style={styles.device}>
          <View
            style={styles.root}
            testID="ridego-app"
            accessibilityLabel={profile ? `${profile.name} 기사 앱` : '타슈캐스트 기사 앱'}
          >
            {content}
          </View>
        </View>
      </View>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  provider: { flex: 1, backgroundColor: colors.canvas },
  stage: { flex: 1, backgroundColor: colors.canvas },
  device: { flex: 1, overflow: 'hidden', backgroundColor: colors.paper },
  root: { flex: 1, backgroundColor: colors.canvas },
  safeArea: { flex: 1, backgroundColor: colors.paper },
  fontLoader: { flex: 1, backgroundColor: colors.orange },
});

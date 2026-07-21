import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { LinearGradient } from 'expo-linear-gradient';
import {
  ActivityIndicator,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { QrScannerModal } from '../components/QrScannerModal';
import { TmapMissionMap, type MapPoint, type MapRoute } from '../components/TmapMissionMap';
import { ApiError, type ApiClient } from '../services/api';
import {
  clearMissionBikeState,
  commitPendingBikeStop,
  discardPendingBikeStop,
  loadBikeCodes,
  loadPendingBikeStop,
  saveBikeCodes,
  savePendingBikeStop,
  type PendingBikeStop,
} from '../services/bikeInventory';
import type { Coordinate, MissionDetail, MissionStop, TestDriverState } from '../types/api';

type Props = {
  api: ApiClient;
  tmapKey: string;
  refreshToken: number;
  preferredPlanId?: string;
  onMenu: () => void;
  onOpenRewards: () => void;
};

type ScanJob =
  | { kind: 'pickup'; stop: MissionStop; location: Coordinate }
  | { kind: 'dropoff-station'; stop: MissionStop; location: Coordinate; challengeId: string }
  | { kind: 'dropoff-bikes'; stop: MissionStop; location: Coordinate }
  | { kind: 'inventory-recovery'; expectedCount: number };

export function MissionNavigationScreen({ api, tmapKey, refreshToken, preferredPlanId, onMenu, onOpenRewards }: Props) {
  const [mission, setMission] = useState<MissionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanJob, setScanJob] = useState<ScanJob | null>(null);
  const [bikeCodes, setBikeCodes] = useState<string[]>([]);
  const [rewardVisible, setRewardVisible] = useState(false);
  const [recoveryBlocked, setRecoveryBlocked] = useState(false);
  const [inventoryMismatch, setInventoryMismatch] = useState<number | null>(null);
  const [noMissionDismissed, setNoMissionDismissed] = useState(false);
  const [driverState, setDriverState] = useState<TestDriverState | null>(null);

  const loadMission = useCallback(async () => {
    setLoading(true); setError(null); setRecoveryBlocked(true); setInventoryMismatch(null);
    try {
      const bootstrap = await api.bootstrap();
      const rank = { in_progress: 0, accepted: 1, offered: 2, completed: 3, cancelled: 4 } as const;
      const selected = preferredPlanId
        ? bootstrap.missions.find((item) => item.plan_id === preferredPlanId)
        : [...bootstrap.missions].sort((a, b) => {
            const statusOrder = rank[a.status] - rank[b.status];
            return statusOrder || new Date(b.offered_at).getTime() - new Date(a.offered_at).getTime();
          })[0];
      if (preferredPlanId && !selected) {
        setMission(null);
        setBikeCodes([]);
        setRecoveryBlocked(false);
        setError(`계획 ${preferredPlanId}에 ${api.driverId} 미션이 없습니다.`);
        return;
      }
      if (!selected) { setMission(null); setRecoveryBlocked(false); return; }
      let detail = await api.getMission(selected.mission_id);
      let stored: string[];
      if (detail.status === 'offered' || detail.status === 'accepted' || detail.status === 'cancelled') {
        await clearMissionBikeState(api.driverId, detail.mission_id);
        stored = [];
      } else {
        stored = await loadBikeCodes(api.driverId, detail.mission_id);
      }
      setMission(detail);
      setBikeCodes(stored);
      try {
        const recovered = await recoverPendingStop(api, detail, stored);
        detail = recovered.mission;
        stored = recovered.bikeCodes;
        setMission(detail);
        setBikeCodes(stored);
        const expectedLoad = expectedVehicleLoad(detail);
        if (detail.status === 'in_progress' && stored.length !== expectedLoad) {
          if (expectedLoad === 0) {
            await saveBikeCodes(api.driverId, detail.mission_id, []);
            setBikeCodes([]);
            setRecoveryBlocked(false);
          } else {
            setInventoryMismatch(expectedLoad);
            setRecoveryBlocked(true);
            setError(`서버 적재 수량은 ${expectedLoad}대지만 이 기기의 QR 목록은 ${stored.length}대입니다. 차량 QR을 다시 스캔하세요.`);
          }
        } else {
          setRecoveryBlocked(false);
        }
      } catch (cause) {
        setRecoveryBlocked(true);
        setError(`이전 QR 처리 복구 대기: ${messageOf(cause)}`);
      }
    } catch (cause) { setError(messageOf(cause)); }
    finally { setLoading(false); }
  }, [api, preferredPlanId]);

  useEffect(() => { void loadMission(); }, [loadMission, refreshToken]);
  useEffect(() => { if (mission) setNoMissionDismissed(false); }, [mission]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const pollDriverState = async () => {
      try {
        const next = await api.getTestDriverState();
        if (active) {
          setDriverState((current) => sameDriverState(current, next) ? current : next);
        }
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 404 && active) {
          setDriverState(null);
          setMission(null);
        }
      } finally {
        if (active) timer = setTimeout(pollDriverState, 3_000);
      }
    };

    setDriverState(null);
    void pollDriverState();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [api, refreshToken]);
  useEffect(() => {
    const localStopSequence = mission?.stops.find((stop) => stop.status === 'pending')?.sequence;
    if (driverState?.mission_id && (
      mission?.mission_id !== driverState.mission_id
      || (driverState.mission_status && mission.status !== driverState.mission_status)
      || localStopSequence !== driverState.next_stop?.sequence
    )) {
      void loadMission();
    }
  }, [
    driverState?.mission_id,
    driverState?.mission_status,
    driverState?.movement_version,
    driverState?.next_stop?.sequence,
    loadMission,
    mission,
  ]);
  useEffect(() => {
    let active = true;

    const requestLocationPermission = async () => {
      try {
        const current = await Location.getForegroundPermissionsAsync();
        const permission = current.granted
          ? current
          : await Location.requestForegroundPermissionsAsync();
        if (active && !permission.granted) {
          setError('경로 안내를 위해 위치 권한을 허용해 주세요.');
        }
      } catch {
        if (active) {
          setError('브라우저에서 위치 권한을 사용할 수 없습니다.');
        }
      }
    };

    void requestLocationPermission();
    return () => { active = false; };
  }, []);

  const currentStop = mission?.stops.find((stop) => stop.status === 'pending') ?? null;
  const currentDriverLocation = driverState?.driver_id === api.driverId
    ? driverState.current_location
    : null;
  const arrivedAtCurrentStop = Boolean(
    mission
    && currentStop
    && currentDriverLocation
    && driverState?.mission_id === mission.mission_id
    && driverState.arrived
    && driverState.next_stop?.sequence === currentStop.sequence,
  );
  const routeCoordinates = useMemo(() => {
    if (!mission) return [];
    const road = mission.route.navigation?.coordinates ?? [];
    return road.length > 1 ? road : [mission.route.start_location, ...mission.stops.map((stop) => stop.location)];
  }, [mission]);
  const routes: MapRoute[] = mission ? [{ id: mission.driver_id, color: mission.route.route_color || '#F7941D', coordinates: routeCoordinates }] : [];
  const markers: MapPoint[] = mission ? [
    { ...(currentDriverLocation ?? mission.route.start_location), label: '기사', kind: 'driver' as const },
    ...mission.stops.map((stop) => ({ ...stop.location, label: `${stop.sequence}`, kind: stop.action as 'pickup' | 'dropoff' })),
  ] : [];

  const runMissionAction = async (action: 'accept' | 'start') => {
    if (!mission || loading || busy !== null || recoveryBlocked) return;
    setBusy(action); setError(null);
    try {
      const next = action === 'accept' ? await api.acceptMission(mission.mission_id) : await api.startMission(mission.mission_id);
      setMission(next);
    } catch (cause) { setError(messageOf(cause)); }
    finally { setBusy(null); }
  };

  const beginStop = async (stop: MissionStop, useRealGps = false) => {
    if (!mission) return;
    if (loading || busy !== null || recoveryBlocked) {
      setError('미확정 QR 처리가 남아 있습니다. 먼저 QR 상태 자동 복구를 실행하세요.');
      return;
    }
    setBusy(useRealGps ? 'gps' : 'arrive'); setError(null);
    try {
      let location: Coordinate;
      if (useRealGps) {
        const permission = await Location.requestForegroundPermissionsAsync();
        if (!permission.granted) throw new Error('실제 위치 확인을 위해 위치 권한이 필요합니다.');
        const current = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
        location = { lat: current.coords.latitude, lng: current.coords.longitude };
        await api.reportLocation(location, { accuracyMeters: 15 });
      } else {
        if (!arrivedAtCurrentStop || !currentDriverLocation) {
          throw new Error('현재 정차 지점에 도착한 뒤 QR을 확인해 주세요.');
        }
        location = currentDriverLocation;
      }
      if (stop.action === 'pickup') {
        setScanJob({ kind: 'pickup', stop, location });
      } else {
        if (bikeCodes.length < stop.planned_quantity) throw new Error(`차량에 적재된 QR이 ${bikeCodes.length}개뿐입니다. 앞선 회수 정차를 확인하세요.`);
        const challenge = await api.createQrChallenge(mission.mission_id, stop.sequence);
        setScanJob({ kind: 'dropoff-station', stop, location, challengeId: challenge.challenge_id });
      }
    } catch (cause) { setError(messageOf(cause)); }
    finally { setBusy(null); }
  };

  const completeScan = async (codes: string[]) => {
    if (!mission || !scanJob) return;
    const job = scanJob;
    setError(null);

    if (job.kind === 'inventory-recovery') {
      const recoveredCodes = [...new Set(codes)];
      setScanJob(null);
      if (recoveredCodes.length !== job.expectedCount) {
        setError(`차량에 적재된 서로 다른 자전거 QR ${job.expectedCount}개가 필요합니다.`);
        return;
      }
      setBusy('recover-inventory');
      try {
        const pendingStop = await loadPendingBikeStop(api.driverId, mission.mission_id);
        if (pendingStop) {
          setInventoryMismatch(null);
          throw new Error('먼저 미확정 정차 QR 처리를 자동 복구해야 합니다.');
        }
        await saveBikeCodes(api.driverId, mission.mission_id, recoveredCodes);
        setBikeCodes(recoveredCodes);
        setInventoryMismatch(null);
        setRecoveryBlocked(false);
        setError(null);
      } catch (cause) {
        setRecoveryBlocked(true);
        setError(`적재 QR 복구값을 저장하지 못했습니다: ${messageOf(cause)}`);
      } finally { setBusy(null); }
      return;
    }

    if (job.kind === 'dropoff-station') {
      setScanJob(null); setBusy('verify-station');
      try {
        const verified = await api.verifyStationQr(mission.mission_id, job.stop.sequence, {
          location: job.location,
          qrPayload: codes[0] ?? '',
          challengeId: job.challengeId,
          integrityProvider: 'development',
        });
        setMission(verified);
        setScanJob({ kind: 'dropoff-bikes', stop: job.stop, location: job.location });
      } catch (cause) {
        try {
          const latest = await api.getMission(mission.mission_id);
          setMission(latest);
          const latestStop = latest.stops.find((item) => item.sequence === job.stop.sequence);
          if (latestStop?.qr_verification === 'verified') {
            setScanJob({ kind: 'dropoff-bikes', stop: latestStop, location: job.location });
          } else {
            setError(messageOf(cause));
          }
        } catch {
          setError(messageOf(cause));
        }
      } finally { setBusy(null); }
      return;
    }

    const uniqueCodes = [...new Set(codes)];
    if (uniqueCodes.length !== job.stop.planned_quantity) {
      setScanJob(null);
      setError(`서로 다른 자전거 QR ${job.stop.planned_quantity}개가 필요합니다.`);
      return;
    }
    if (job.kind === 'pickup' && uniqueCodes.some((code) => bikeCodes.includes(code))) {
      setScanJob(null);
      setError('이미 차량에 적재된 자전거 QR이 포함되어 있습니다.');
      return;
    }
    if (job.kind === 'dropoff-bikes' && uniqueCodes.some((code) => !bikeCodes.includes(code))) {
      setScanJob(null);
      const expectedLoad = expectedVehicleLoad(mission);
      setInventoryMismatch(expectedLoad || bikeCodes.length);
      setRecoveryBlocked(true);
      setError('차량 적재 목록과 실제 자전거 QR이 다릅니다. 적재 자전거를 다시 스캔하세요.');
      return;
    }

    const deployed = new Set(uniqueCodes);
    const nextCodes = job.kind === 'pickup'
      ? [...bikeCodes, ...uniqueCodes]
      : bikeCodes.filter((code) => !deployed.has(code));
    const journal: PendingBikeStop = {
      missionId: mission.mission_id,
      sequence: job.stop.sequence,
      action: job.stop.action,
      location: job.location,
      actualQuantity: uniqueCodes.length,
      scannedBikeCodes: uniqueCodes,
      beforeCodes: bikeCodes,
      afterCodes: nextCodes,
      createdAt: new Date().toISOString(),
    };

    setBusy('complete-stop');
    let journalSaved = false;
    try {
      await savePendingBikeStop(api.driverId, journal);
      journalSaved = true;
      setScanJob(null);
      const detail = await api.completeStop(mission.mission_id, job.stop.sequence, {
        location: job.location,
        actualQuantity: journal.actualQuantity,
        bikeQrCodes: journal.scannedBikeCodes,
      });
      await commitPendingBikeStop(api.driverId, journal);
      setRecoveryBlocked(false);
      setBikeCodes(journal.afterCodes);
      setMission(detail);
      if (detail.status === 'completed') setRewardVisible(true);
    } catch (cause) {
      if (!journalSaved) {
        setScanJob(null);
        setRecoveryBlocked(false);
        setError(`QR 처리 기록을 안전하게 저장하지 못했습니다: ${messageOf(cause)}`);
        setBusy(null);
        return;
      }
      try {
        const latest = await api.getMission(mission.mission_id);
        const latestStop = latest.stops.find((item) => item.sequence === job.stop.sequence);
        if (latestStop?.status === 'completed') {
          await commitPendingBikeStop(api.driverId, journal);
          setRecoveryBlocked(false);
          setBikeCodes(journal.afterCodes);
          setMission(latest);
          if (latest.status === 'completed') setRewardVisible(true);
        } else if (cause instanceof ApiError && [400, 409, 422].includes(cause.status)) {
          await discardPendingBikeStop(api.driverId, mission.mission_id);
          const inventoryRejected = job.kind === 'dropoff-bikes'
            && cause.status === 422
            && /적재|실린 자전거/.test(cause.detail);
          if (inventoryRejected) {
            setInventoryMismatch(expectedVehicleLoad(latest));
            setRecoveryBlocked(true);
            setError(`차량 적재 QR을 다시 확인해 주세요: ${messageOf(cause)}`);
          } else {
            setRecoveryBlocked(false);
            setError(`QR을 다시 확인해 주세요: ${messageOf(cause)}`);
          }
        } else {
          setRecoveryBlocked(true);
          setError(`정차 완료를 재시도할 수 있습니다: ${messageOf(cause)}`);
        }
      } catch {
        setRecoveryBlocked(true);
        setError(`정차 처리 결과를 확인하지 못했습니다. 새로고침하면 자동 복구합니다: ${messageOf(cause)}`);
      }
    }
    finally { setBusy(null); }
  };

  const displayStop = currentStop ?? mission?.stops.find((stop) => stop.status === 'pending') ?? null;
  const pickupPhase = displayStop?.action !== 'dropoff';
  const accent = pickupPhase ? '#1FA35C' : '#F7941D';
  const accentDark = pickupPhase ? '#178B4C' : '#EC7C15';
  const accentSoft = pickupPhase ? '#DCF3E6' : '#FDECD6';
  const expectedLoad = mission ? expectedVehicleLoad(mission) : 0;
  const plannedStop = mission?.route.stops.find((stop) => stop.sequence === displayStop?.sequence) ?? null;
  const priorStop = mission?.route.stops.find((stop) => stop.sequence === (displayStop?.sequence ?? 0) - 1) ?? null;
  const travelMinutes = plannedStop
    ? minutesBetween(priorStop?.etd ?? mission?.route.start_at ?? null, plannedStop.eta)
    : mission?.route.navigation ? Math.ceil(mission.route.navigation.total_duration_seconds / 60) : 0;
  const distanceKm = plannedStop?.leg_distance_km
    ?? (mission?.route.navigation ? mission.route.navigation.total_distance_meters / 1000 : 0);
  const phaseStops = mission?.stops.filter((stop) => stop.action === displayStop?.action) ?? [];
  const phaseTotal = phaseStops.reduce((sum, stop) => sum + stop.planned_quantity, 0);
  const phaseCompleted = phaseStops
    .filter((stop) => stop.status === 'completed')
    .reduce((sum, stop) => sum + (stop.actual_quantity ?? stop.planned_quantity), 0);
  const stationRemaining = plannedStop
    ? Math.max(0, plannedStop.capacity - (plannedStop.available_bikes_at_plan_time ?? 0))
    : bikeCodes.length;
  const mapRoutes = routes.map((route) => ({ ...route, color: accent }));
  const mapMarkers: MapPoint[] = mission ? [
    { ...(currentDriverLocation ?? mission.route.start_location), label: '현재 위치', kind: 'driver' },
    ...(displayStop ? [{
      ...displayStop.location,
      label: displayStop.action === 'pickup' ? '회수 지점' : displayStop.station_name,
      kind: displayStop.action,
    }] satisfies MapPoint[] : []),
  ] : markers;

  const cardLabel = recoveryBlocked
    ? 'QR 상태 복구'
    : mission?.status === 'offered'
        ? '배정된 미션'
        : mission?.status === 'accepted'
          ? '출발 준비'
          : mission?.status === 'cancelled'
            ? '취소된 미션'
          : mission?.status === 'completed'
            ? '재배치 완료'
            : pickupPhase ? '회수 지점' : '재배치 필요';
  const cardTitle = displayStop?.station_name
    ?? (mission?.status === 'completed' ? '오늘의 재배치를 완료했어요' : '배정된 미션이 없습니다');
  const cardActionIcon: keyof typeof Ionicons.glyphMap = recoveryBlocked
    ? (inventoryMismatch ? 'scan' : 'refresh')
    : mission?.status === 'offered'
        ? 'checkmark'
        : mission?.status === 'accepted'
          ? 'play'
          : mission?.status === 'cancelled'
            ? 'refresh'
          : mission?.status === 'completed'
            ? 'gift'
            : 'qr-code';
  const cardActionDisabled = loading || busy !== null
    || (mission?.status === 'in_progress' && (!currentStop || !arrivedAtCurrentStop) && !recoveryBlocked);

  const handleCardAction = () => {
    if (loading || busy !== null) return;
    if (recoveryBlocked) {
      if (inventoryMismatch) setScanJob({ kind: 'inventory-recovery', expectedCount: inventoryMismatch });
      else void loadMission();
      return;
    }
    if (!mission) return;
    if (mission.status === 'offered') { void runMissionAction('accept'); return; }
    if (mission.status === 'accepted') { void runMissionAction('start'); return; }
    if (mission.status === 'cancelled') { void loadMission(); return; }
    if (mission.status === 'completed') { onOpenRewards(); return; }
    if (mission.status === 'in_progress' && currentStop) void beginStop(currentStop, false);
  };

  const rescanInventory = () => {
    if (!mission || expectedLoad === 0 || busy !== null || loading) return;
    setInventoryMismatch(expectedLoad);
    setRecoveryBlocked(true);
    setScanJob({ kind: 'inventory-recovery', expectedCount: expectedLoad });
  };

  return (
    <View style={styles.root}>
      <View style={StyleSheet.absoluteFill}>
        <TmapMissionMap tmapKey={tmapKey} routes={mapRoutes} markers={mapMarkers} height="100%" />
      </View>
      <LinearGradient
        pointerEvents="none"
        colors={['rgba(232,232,232,.97)', 'rgba(232,232,232,.72)', 'rgba(232,232,232,0)']}
        locations={[0, .52, 1]}
        style={styles.topShade}
      />

      <Pressable accessibilityLabel="메뉴 열기" onPress={onMenu} style={({ pressed }) => [styles.menuButton, pressed && styles.buttonPressed]}>
        <Ionicons name="menu" size={23} color="#201E1D" />
      </Pressable>

      <View pointerEvents="none" style={styles.locationCopy}>
        <Text style={styles.city}>대전광역시</Text>
        <Text style={styles.address} numberOfLines={1}>
          {displayStop ? `${displayStop.station_name} 방면 · ${statusLabel(mission?.status)}` : `${api.driverId} · ${statusLabel(mission?.status)}`}
        </Text>
      </View>

      <View style={styles.mapTools}>
        <Pressable
          accessibilityLabel="미션과 경로 새로고침"
          disabled={loading}
          onPress={() => void loadMission()}
          style={({ pressed }) => [styles.mapToolButton, pressed && styles.buttonPressed, loading && styles.disabled]}
        >
          {loading ? <ActivityIndicator size="small" color="#201E1D" /> : <Ionicons name="refresh" size={20} color="#201E1D" />}
        </Pressable>
        <Pressable
          accessibilityLabel="내 실제 GPS로 도착 확인"
          disabled={!currentStop || busy !== null || recoveryBlocked}
          onPress={() => currentStop && void beginStop(currentStop, true)}
          style={({ pressed }) => [styles.mapToolButton, pressed && styles.buttonPressed, (!currentStop || busy !== null || recoveryBlocked) && styles.disabled]}
        >
          {busy === 'gps' ? <ActivityIndicator size="small" color={accent} /> : <Ionicons name="locate" size={22} color={accent} />}
        </Pressable>
      </View>

      {error ? (
        <View style={styles.notice}>
          <Ionicons name="alert-circle" size={18} color="#D0442A" />
          <Text style={styles.noticeText} numberOfLines={3}>{error}</Text>
        </View>
      ) : null}

      {loading && !mission ? (
        <View pointerEvents="none" style={styles.loadingOverlay}>
          <ActivityIndicator size="large" color="#F7941D" />
          <Text style={styles.loadingText}>기사 미션을 불러오는 중…</Text>
        </View>
      ) : null}

      {mission ? <View style={styles.missionCard}>
        <View style={styles.cardTop}>
          <View style={[styles.stopIcon, { backgroundColor: accentSoft }]}>
            <Ionicons name={pickupPhase ? 'cube-outline' : 'bicycle'} size={30} color={accentDark} />
          </View>
          <View style={styles.cardCopy}>
            <View style={styles.tagRow}>
              <View style={[styles.phaseTag, { backgroundColor: accentSoft }]}>
                <Text style={[styles.phaseTagText, { color: accentDark }]}>{cardLabel}</Text>
              </View>
              {mission?.status === 'in_progress' && expectedLoad > 0 ? (
                <Pressable
                  accessibilityLabel="차량 적재 자전거 QR 다시 스캔"
                  disabled={busy !== null || loading || (recoveryBlocked && inventoryMismatch === null)}
                  onPress={rescanInventory}
                  style={styles.loadPill}
                >
                  <Ionicons name="bicycle" size={12} color="#605D5D" />
                  <Text style={styles.loadPillText}>{bikeCodes.length}대 적재</Text>
                </Pressable>
              ) : null}
            </View>
            <Text style={styles.cardTitle} numberOfLines={1}>{cardTitle}</Text>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={cardLabel}
            disabled={cardActionDisabled}
            onPress={handleCardAction}
            style={({ pressed }) => [styles.cardAction, { backgroundColor: accent }, pressed && styles.actionPressed, cardActionDisabled && styles.disabled]}
          >
            {busy !== null || (loading && mission !== null)
              ? <ActivityIndicator size="small" color="#FFFFFF" />
              : <Ionicons name={cardActionIcon} size={23} color="#FFFFFF" />}
          </Pressable>
        </View>

        <View style={styles.metrics}>
          <MissionMetric label="거리" value={mission ? `${distanceKm.toFixed(1)} km` : '경로 대기'} />
          <MissionMetric
            divided
            label={pickupPhase ? '예상 시간' : '재배치'}
            value={pickupPhase ? (mission ? `${travelMinutes} 분` : '-') : `${phaseCompleted} / ${phaseTotal || 0}`}
          />
          <MissionMetric
            divided
            accent={accent}
            label={pickupPhase ? '회수 완료' : '잔여 가능'}
            value={pickupPhase ? `${phaseCompleted} / ${phaseTotal || 0}` : `${stationRemaining}대`}
          />
        </View>
      </View> : null}

      <InAppModal
        visible={!loading && !mission && !noMissionDismissed}
        onRequestClose={() => setNoMissionDismissed(true)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.noMissionModal}>
            <View style={styles.noMissionIcon}>
              <Ionicons name="location-outline" size={44} color="#D0442A" />
              <View style={styles.noMissionSlash} />
            </View>
            <Text style={styles.noMissionTitle}>재배치 가능한 대여소가 없습니다</Text>
            <Text style={styles.noMissionBody}>근처 대여소가 모두 가득 찼어요.{`\n`}잠시 후 다시 시도하거나 고객센터로 문의해 주세요.</Text>
            <Pressable onPress={() => setNoMissionDismissed(true)} style={styles.noMissionConfirm}>
              <Text style={styles.noMissionConfirmText}>확인</Text>
            </Pressable>
          </View>
        </View>
      </InAppModal>

      <QrScannerModal
        key={!scanJob ? 'closed' : scanJob.kind === 'inventory-recovery' ? 'inventory-recovery' : `${scanJob.kind}-${scanJob.stop.sequence}`}
        visible={scanJob !== null}
        title={!scanJob ? '' : scanJob.kind === 'inventory-recovery'
          ? `적재 자전거 ${scanJob.expectedCount}대 QR 복구`
          : scanJob.kind === 'pickup'
          ? `${scanJob.stop.planned_quantity}대 회수 자전거 QR`
          : scanJob.kind === 'dropoff-station'
            ? `${scanJob.stop.station_name} 대여소 QR`
            : `${scanJob.stop.planned_quantity}대 하차 자전거 QR`}
        description={!scanJob ? '' : scanJob.kind === 'inventory-recovery'
          ? '서버의 적재 수량과 맞도록 현재 차량에 실린 실제 자전거 QR을 모두 다시 확인합니다.'
          : scanJob.kind === 'pickup'
          ? '차량에 싣는 자전거의 QR을 하나씩 확인합니다.'
          : scanJob.kind === 'dropoff-station'
            ? '현장 대여소 QR과 서버 challenge를 먼저 대조합니다.'
            : '실제로 내리는 자전거 QR을 다시 확인해 해당 대여소의 이력으로 기록합니다.'}
        expectedCount={!scanJob ? 1 : scanJob.kind === 'inventory-recovery'
          ? scanJob.expectedCount
          : scanJob.kind === 'dropoff-station' ? 1 : scanJob.stop.planned_quantity}
        onComplete={completeScan}
        onClose={() => setScanJob(null)}
      />

      <InAppModal visible={rewardVisible} onRequestClose={() => setRewardVisible(false)}>
        <View style={styles.modalOverlay}>
          <View style={styles.rewardModal}>
            <View style={styles.coinOuter}>
              <View style={styles.coinInner}><Text style={styles.coinText}>P</Text></View>
            </View>
            <Text style={styles.rewardTitle}>리워드가 지급되었습니다</Text>
            <Text style={styles.rewardBody}>재배치를 완료해 주셔서 감사합니다</Text>
            <View style={styles.rewardPointsBox}>
              <Ionicons name="cash" size={25} color="#E08A16" />
              <Text style={styles.rewardPoints}>+ {mission?.awarded_reward?.total_points ?? mission?.estimated_reward.total_points ?? 0} P</Text>
            </View>
            <Pressable onPress={() => setRewardVisible(false)} style={styles.rewardConfirm}>
              <Text style={styles.rewardConfirmText}>확인</Text>
            </Pressable>
          </View>
        </View>
      </InAppModal>
    </View>
  );
}

function InAppModal({
  visible,
  onRequestClose,
  children,
}: {
  visible: boolean;
  onRequestClose: () => void;
  children: ReactNode;
}) {
  if (Platform.OS === 'web') {
    return visible ? <View style={styles.webModal}>{children}</View> : null;
  }
  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      statusBarTranslucent
      onRequestClose={onRequestClose}
    >
      {children}
    </Modal>
  );
}

function MissionMetric({
  label,
  value,
  divided = false,
  accent,
}: {
  label: string;
  value: string;
  divided?: boolean;
  accent?: string;
}) {
  return (
    <View style={[styles.metric, divided && styles.metricDivided]}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={[styles.metricValue, accent ? { color: accent } : null]}>{value}</Text>
    </View>
  );
}

function minutesBetween(start: string | null, end: string | null) {
  if (!start || !end) return 0;
  const startMs = new Date(start).getTime();
  const endMs = new Date(end).getTime();
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return 0;
  return Math.max(0, Math.ceil((endMs - startMs) / 60_000));
}

async function recoverPendingStop(
  api: ApiClient,
  mission: MissionDetail,
  bikeCodes: string[],
): Promise<{ mission: MissionDetail; bikeCodes: string[] }> {
  const journal = await loadPendingBikeStop(api.driverId, mission.mission_id);
  if (!journal) return { mission, bikeCodes };

  const stop = mission.stops.find((item) => item.sequence === journal.sequence);
  if (!stop || mission.status === 'offered' || mission.status === 'accepted' || mission.status === 'cancelled') {
    await clearMissionBikeState(api.driverId, mission.mission_id);
    return { mission, bikeCodes: [] };
  }
  if (stop.status === 'completed') {
    await commitPendingBikeStop(api.driverId, journal);
    return { mission, bikeCodes: journal.afterCodes };
  }
  if (journal.action === 'dropoff' && stop.qr_verification !== 'verified') {
    await discardPendingBikeStop(api.driverId, mission.mission_id);
    return { mission, bikeCodes: journal.beforeCodes };
  }

  try {
    const recovered = await api.completeStop(mission.mission_id, journal.sequence, {
      location: journal.location,
      actualQuantity: journal.actualQuantity,
      bikeQrCodes: journal.scannedBikeCodes,
    });
    await commitPendingBikeStop(api.driverId, journal);
    return { mission: recovered, bikeCodes: journal.afterCodes };
  } catch (cause) {
    const latest = await api.getMission(mission.mission_id);
    const latestStop = latest.stops.find((item) => item.sequence === journal.sequence);
    if (latestStop?.status === 'completed') {
      await commitPendingBikeStop(api.driverId, journal);
      return { mission: latest, bikeCodes: journal.afterCodes };
    }
    if (cause instanceof ApiError && [400, 409, 422].includes(cause.status)) {
      await discardPendingBikeStop(api.driverId, mission.mission_id);
      return { mission: latest, bikeCodes: journal.beforeCodes };
    }
    if (journal.action === 'dropoff' && latestStop?.qr_verification !== 'verified') {
      await discardPendingBikeStop(api.driverId, mission.mission_id);
    }
    throw cause;
  }
}

function expectedVehicleLoad(mission: MissionDetail) {
  return mission.stops.reduce((load, stop) => {
    if (stop.status !== 'completed') return load;
    const quantity = stop.actual_quantity ?? 0;
    return stop.action === 'pickup' ? load + quantity : Math.max(0, load - quantity);
  }, 0);
}

function sameDriverState(current: TestDriverState | null, next: TestDriverState) {
  return current?.scenario_id === next.scenario_id
    && current.driver_id === next.driver_id
    && current.mission_id === next.mission_id
    && current.mission_status === next.mission_status
    && current.arrived === next.arrived
    && current.movement_version === next.movement_version
    && current.next_stop?.sequence === next.next_stop?.sequence
    && current.current_location?.lat === next.current_location?.lat
    && current.current_location?.lng === next.current_location?.lng;
}

function messageOf(cause: unknown) {
  if (cause instanceof ApiError) return cause.detail;
  return cause instanceof Error ? cause.message : '알 수 없는 오류가 발생했습니다.';
}

function statusLabel(status?: MissionDetail['status']) {
  return status ? ({ offered: '배정 대기', accepted: '출발 준비', in_progress: '운행 중', completed: '완료', cancelled: '취소' }[status]) : '미션 없음';
}

const styles = StyleSheet.create({
  root: { flex: 1, overflow: 'hidden', backgroundColor: '#E8E8E8' },
  topShade: { position: 'absolute', top: 0, left: 0, right: 0, height: 200 },
  menuButton: {
    position: 'absolute', zIndex: 40, top: 58, left: 22,
    width: 46, height: 46, borderRadius: 14,
    alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF',
    shadowColor: '#000000', shadowOpacity: .14, shadowRadius: 8, shadowOffset: { width: 0, height: 4 }, elevation: 7,
  },
  buttonPressed: { transform: [{ scale: .96 }], opacity: .9 },
  actionPressed: { transform: [{ scale: .94 }] },
  disabled: { opacity: .42 },
  locationCopy: { position: 'absolute', zIndex: 10, top: 120, left: 24, right: 84 },
  city: { color: '#201E1D', fontSize: 27, lineHeight: 31, fontWeight: '800', letterSpacing: -.8 },
  address: { marginTop: 4, color: '#7D7979', fontSize: 12, fontWeight: '600', letterSpacing: -.1 },
  mapTools: { position: 'absolute', zIndex: 18, right: 22, bottom: 212, gap: 10 },
  mapToolButton: {
    width: 44, height: 44, borderRadius: 14,
    alignItems: 'center', justifyContent: 'center', backgroundColor: '#FFFFFF',
    shadowColor: '#000000', shadowOpacity: .16, shadowRadius: 9, shadowOffset: { width: 0, height: 6 }, elevation: 7,
  },
  notice: {
    position: 'absolute', zIndex: 30, left: 16, right: 76, bottom: 191,
    flexDirection: 'row', alignItems: 'flex-start', gap: 8,
    paddingHorizontal: 12, paddingVertical: 10, borderRadius: 13,
    backgroundColor: 'rgba(255,255,255,.96)',
    shadowColor: '#000000', shadowOpacity: .12, shadowRadius: 8, shadowOffset: { width: 0, height: 4 }, elevation: 6,
  },
  noticeText: { flex: 1, color: '#A73320', fontSize: 10, lineHeight: 15, fontWeight: '700' },
  loadingOverlay: {
    position: 'absolute', zIndex: 24, top: '38%', alignSelf: 'center',
    alignItems: 'center', paddingHorizontal: 22, paddingVertical: 17, borderRadius: 18,
    backgroundColor: 'rgba(255,255,255,.94)',
  },
  loadingText: { marginTop: 10, color: '#605D5D', fontSize: 12, fontWeight: '700' },
  missionCard: {
    position: 'absolute', zIndex: 20, left: 16, right: 16, bottom: 34,
    padding: 17, borderRadius: 22, backgroundColor: '#FFFFFF',
    shadowColor: '#000000', shadowOpacity: .2, shadowRadius: 20, shadowOffset: { width: 0, height: 14 }, elevation: 12,
  },
  cardTop: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  stopIcon: { flex: 0, width: 60, height: 60, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  cardCopy: { flex: 1, minWidth: 0 },
  tagRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 5 },
  phaseTag: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  phaseTagText: { fontSize: 10, lineHeight: 12, fontWeight: '800', letterSpacing: .35 },
  loadPill: {
    flexDirection: 'row', alignItems: 'center', gap: 3,
    paddingHorizontal: 7, paddingVertical: 4, borderRadius: 7, backgroundColor: '#F3F2F2',
  },
  loadPillText: { color: '#605D5D', fontSize: 9, fontWeight: '700' },
  cardTitle: { color: '#201E1D', fontSize: 18, lineHeight: 22, fontWeight: '800', letterSpacing: -.35 },
  cardAction: { flex: 0, width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center' },
  metrics: { flexDirection: 'row', marginTop: 15, paddingTop: 14, borderTopWidth: 1.5, borderTopColor: '#C4BFB8' },
  metric: { flex: 1 },
  metricDivided: { borderLeftWidth: 1.5, borderLeftColor: '#C4BFB8', paddingLeft: 16 },
  metricLabel: { marginBottom: 2, color: '#9B9797', fontSize: 11, fontWeight: '600' },
  metricValue: { color: '#201E1D', fontSize: 16, fontWeight: '800' },
  modalOverlay: {
    flex: 1, alignItems: 'center', justifyContent: 'center', padding: 30,
    backgroundColor: 'rgba(25,18,6,.55)',
  },
  webModal: { position: 'absolute', zIndex: 90, top: 0, right: 0, bottom: 0, left: 0 },
  noMissionModal: {
    width: '100%', maxWidth: 310, alignItems: 'center',
    paddingHorizontal: 26, paddingTop: 34, paddingBottom: 24,
    borderRadius: 28, backgroundColor: '#FFFFFF',
    shadowColor: '#000000', shadowOpacity: .35, shadowRadius: 30, shadowOffset: { width: 0, height: 24 }, elevation: 18,
  },
  noMissionIcon: {
    width: 88, height: 88, borderRadius: 44, alignItems: 'center', justifyContent: 'center',
    backgroundColor: '#FBECE9',
  },
  noMissionSlash: {
    position: 'absolute', width: 42, height: 3, borderRadius: 2,
    backgroundColor: '#D0442A', transform: [{ rotate: '-45deg' }],
  },
  noMissionTitle: { marginTop: 20, color: '#201E1D', fontSize: 20, lineHeight: 25, fontWeight: '800', letterSpacing: -.4, textAlign: 'center' },
  noMissionBody: { marginTop: 8, color: '#9B9797', fontSize: 13, lineHeight: 20, fontWeight: '500', textAlign: 'center' },
  noMissionConfirm: { width: '100%', marginTop: 24, alignItems: 'center', paddingVertical: 16, borderRadius: 14, backgroundColor: '#201E1D' },
  noMissionConfirmText: { color: '#FFFFFF', fontSize: 16, fontWeight: '800' },
  rewardModal: {
    width: '100%', maxWidth: 310, alignItems: 'center',
    paddingHorizontal: 26, paddingTop: 36, paddingBottom: 24,
    borderRadius: 28, backgroundColor: '#FFFFFF',
    shadowColor: '#000000', shadowOpacity: .35, shadowRadius: 30, shadowOffset: { width: 0, height: 24 }, elevation: 18,
  },
  coinOuter: {
    width: 96, height: 96, borderRadius: 48, alignItems: 'center', justifyContent: 'center',
    borderWidth: 3, borderColor: '#C87608', backgroundColor: '#E08A16',
    shadowColor: '#E8951B', shadowOpacity: .4, shadowRadius: 8, shadowOffset: { width: 0, height: 10 }, elevation: 8,
  },
  coinInner: {
    width: 66, height: 66, borderRadius: 33, alignItems: 'center', justifyContent: 'center',
    borderWidth: 2.5, borderColor: '#FFD277', backgroundColor: '#FBB733',
  },
  coinText: { color: '#B96A06', fontSize: 31, fontWeight: '900' },
  rewardTitle: { marginTop: 22, color: '#201E1D', fontSize: 20, fontWeight: '800', letterSpacing: -.35 },
  rewardBody: { marginTop: 8, color: '#9B9797', fontSize: 13, fontWeight: '500' },
  rewardPointsBox: {
    width: '100%', marginTop: 22, marginBottom: 24,
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 9,
    paddingHorizontal: 20, paddingVertical: 13, borderRadius: 16, backgroundColor: '#FDF0DC',
  },
  rewardPoints: { color: '#EC7C15', fontSize: 25, fontWeight: '800', letterSpacing: -.5 },
  rewardConfirm: { width: '100%', alignItems: 'center', paddingVertical: 16, borderRadius: 14, backgroundColor: '#F7941D' },
  rewardConfirmText: { color: '#FFFFFF', fontSize: 16, fontWeight: '800' },
});
